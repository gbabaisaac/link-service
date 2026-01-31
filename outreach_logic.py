"""Outreach workflow logic for Link."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from config import settings
from link_logic import llm_json, normalize_entities
import supabase_client as db


@dataclass
class CandidateScore:
    user_id: str
    confidence: float
    evidence: list[str]
    support_count: int
    consent: bool


def build_message_template(question: str, entities: list[str]) -> str:
    """Create a consistent outreach message template."""
    activity = entities[0] if entities else "this"
    return (
        "hey! quick question from Link - someone asked: "
        f"\"{question}\". do you {activity}? "
        "if yes and you're open to an intro, reply YES. if not, reply NO."
    )


def build_consent_request(question: str, entities: list[str]) -> str:
    """Message to get candidate consent."""
    activity = entities[0] if entities else "this"
    return (
        "hey! someone is looking for people who "
        f"{activity}. want me to connect you? reply YES or NO."
    )


def _score_reply(reply_type: str, consent: str) -> float:
    if reply_type == "self_claim":
        return 0.85 if consent == "yes" else 0.65
    if reply_type == "referral":
        return 0.55
    return 0.0


def interpret_reply(text: str) -> tuple[str, str, list[str]]:
    """Infer reply type + consent from a raw message (heuristic + LLM fallback)."""
    t = (text or "").strip().lower()
    evidence: list[str] = []
    if not t:
        return "unknown", "unknown", evidence

    consent = "unknown"
    if any(x in t for x in ["yes", "yep", "yeah", "sure", "im down", "i'm down", "ok"]):
        consent = "yes"
    if any(x in t for x in ["no", "nah", "not really"]):
        consent = "no"

    if any(x in t for x in ["i play", "i do", "me", "i'm", "i am"]):
        evidence.append("self_claim")
        return "self_claim", consent, evidence

    if "@" in t or any(x in t for x in ["my friend", "ask", "you should ask", "they play"]):
        evidence.append("referral")
        return "referral", consent, evidence

    # LLM fallback for ambiguous replies
    prompt = f"""Classify this reply.

Reply: \"{text}\"

Return JSON:
{{
  \"reply_type\": \"self_claim|referral|unknown\",
  \"consent\": \"yes|no|unknown\"
}}"""
    try:
        result = llm_json(prompt, temperature=0)
        reply_type = result.get("reply_type", "unknown")
        consent = result.get("consent", consent)
        if reply_type == "self_claim":
            evidence = ["self_claim"]
        elif reply_type == "referral":
            evidence = ["referral"]
        return reply_type, consent, evidence
    except Exception:
        return "unknown", consent, evidence


def select_outreach_targets(
    requester_id: str,
    university_id: str,
    entities: list[str],
    batch_size: int,
    excluded_ids: list[str],
) -> list[dict]:
    """Select a prioritized batch of recipients."""
    excluded = set(excluded_ids + [requester_id])
    entities = normalize_entities(entities)

    targets: list[dict] = []

    def _add(user_id: str, reason: str) -> None:
        if user_id and user_id not in excluded and user_id not in {t["user_id"] for t in targets}:
            targets.append({"user_id": user_id, "reason": reason})

    # 1) Friends
    for friend_id in db.get_friends(requester_id):
        _add(friend_id, "friend")
        if len(targets) >= batch_size:
            return targets[:batch_size]

    # 2) Classmates
    for classmate_id in db.get_classmates(requester_id):
        _add(classmate_id, "classmate")
        if len(targets) >= batch_size:
            return targets[:batch_size]

    # 3) Prior opt-in facts from Link knowledge
    for entity in entities:
        facts = db.get_link_facts_by_value(university_id, f"%{entity}%")
        for fact in facts:
            _add(fact.get("entity_id"), "link_fact")
            if len(targets) >= batch_size:
                return targets[:batch_size]

    # 4) Interest match
    profiles = db.get_profiles(university_id, limit=200)
    if entities:
        for p in profiles:
            interests = p.get("interests") or []
            if isinstance(interests, str):
                interests = [interests]
            haystack = " ".join([
                p.get("bio") or "",
                p.get("major") or "",
                " ".join([str(i).lower() for i in interests]),
            ]).lower()
            if any(e in haystack for e in entities):
                _add(p.get("id"), "interest_match")
                if len(targets) >= batch_size:
                    return targets[:batch_size]

    # 5) Fallback: active profiles
    for p in profiles:
        _add(p.get("id"), "campus_active")
        if len(targets) >= batch_size:
            return targets[:batch_size]

    return targets[:batch_size]


def send_outreach_messages(
    university_id: str,
    outreach_request_id: str,
    targets: list[dict],
    message_template: str,
) -> list[dict]:
    """Send outreach messages and record them."""
    sent: list[dict] = []
    link_profile = db.get_link_system_profile(university_id)
    sender_id = link_profile.get("link_user_id") if link_profile else None

    for target in targets:
        user_id = target["user_id"]
        convo = db.get_or_create_link_conversation(user_id)
        if not convo:
            continue
        session = db.get_or_create_link_session(user_id, university_id)
        if session:
            db.set_link_conversation_session(convo["id"], session["id"])
        message_text = message_template
        message = db.insert_link_message(
            convo["id"],
            sender_id,
            message_text,
            {"shareType": "text"},
            session_id=session["id"] if session else None,
        )
        outreach_msg = db.create_outreach_message(
            {
                "outreach_request_id": outreach_request_id,
                "target_user_id": user_id,
                "message_template": message_template,
                "message_sent": message_text,
                "conversation_id": convo["id"],
                "message_id": message.get("id") if message else None,
                "response_status": "sent",
                "sent_at": datetime.utcnow().isoformat() + "Z",
            }
        )
        sent.append(outreach_msg)
    return sent


def process_outreach_round(outreach_request: dict) -> dict:
    """Process replies and decide whether to expand outreach or surface candidates."""
    request_id = outreach_request["id"]
    entities = outreach_request.get("parsed_intent", {}).get("entities") or []
    threshold = outreach_request.get("target_confidence_threshold") or settings.OUTREACH_CONFIDENCE_THRESHOLD
    batch_size = outreach_request.get("batch_size") or settings.OUTREACH_BATCH_SIZE
    max_attempts = outreach_request.get("max_attempts") or settings.MAX_OUTREACH_BATCHES
    hard_cap = outreach_request.get("hard_cap") or settings.OUTREACH_HARD_CAP

    messages = db.list_outreach_messages(request_id)

    candidates: dict[str, CandidateScore] = {}
    responses_received = 0
    positive_responses = 0

    for msg in messages:
        response_text = msg.get("response_text")
        if not response_text:
            continue
        responses_received += 1
        reply_type, consent, evidence = interpret_reply(response_text)
        if reply_type == "unknown":
            continue
        positive_responses += 1
        candidate_id = msg.get("target_user_id")
        base_conf = _score_reply(reply_type, consent)
        if candidate_id not in candidates:
            candidates[candidate_id] = CandidateScore(
                user_id=candidate_id,
                confidence=base_conf,
                evidence=evidence,
                support_count=1,
                consent=(consent == "yes"),
            )
        else:
            c = candidates[candidate_id]
            c.support_count += 1
            c.confidence = min(0.95, c.confidence + 0.05)
            c.evidence = list(set(c.evidence + evidence))
            c.consent = c.consent or (consent == "yes")

    candidate_list = sorted(candidates.values(), key=lambda c: c.confidence, reverse=True)

    # Determine status transitions
    status = outreach_request.get("status", "collecting")
    selected_candidates = [c for c in candidate_list if c.confidence >= threshold]

    if selected_candidates:
        status = "candidate_found"
    else:
        total_asked = len({m.get("target_user_id") for m in messages if m.get("target_user_id")})
        attempts = outreach_request.get("batch_number") or 1
        if attempts < max_attempts and total_asked < hard_cap:
            status = "collecting"
        else:
            status = "expired"

    update = {
        "status": status,
        "responses_received": responses_received,
        "positive_responses": positive_responses,
        "last_round_completed_at": datetime.utcnow().isoformat() + "Z",
    }
    db.update_outreach_request(request_id, update)

    return {
        "status": status,
        "responses_received": responses_received,
        "positive_responses": positive_responses,
        "candidates": candidate_list,
        "entities": entities,
        "batch_size": batch_size,
        "max_attempts": max_attempts,
    }


def start_outreach(outreach_request: dict) -> dict:
    """Create an outreach request and send the first batch."""
    question = outreach_request.get("original_question")
    intent = outreach_request.get("parsed_intent") or {}
    entities = intent.get("entities") or []

    message_template = build_message_template(question, entities)

    created = db.create_outreach_request(outreach_request)
    targets = select_outreach_targets(
        requester_id=created["requesting_user_id"],
        university_id=created["university_id"],
        entities=entities,
        batch_size=created.get("batch_size") or settings.OUTREACH_BATCH_SIZE,
        excluded_ids=created.get("excluded_user_ids") or [],
    )

    if targets:
        send_outreach_messages(created["university_id"], created["id"], targets, message_template)

    db.update_outreach_request(
        created["id"],
        {
            "status": "collecting",
            "target_user_ids": [t["user_id"] for t in targets],
            "batch_number": 1,
            "started_at": datetime.utcnow().isoformat() + "Z",
            "last_round_started_at": datetime.utcnow().isoformat() + "Z",
        },
    )

    return {
        "request": created,
        "targets": targets,
        "message_template": message_template,
        "estimated_completion": (datetime.utcnow() + timedelta(minutes=settings.OUTREACH_WAIT_MINUTES)).isoformat() + "Z",
    }


def expand_outreach(outreach_request: dict) -> list[dict]:
    """Send another batch if allowed."""
    request_id = outreach_request["id"]
    entities = outreach_request.get("parsed_intent", {}).get("entities") or []
    excluded = outreach_request.get("excluded_user_ids") or []
    already = outreach_request.get("target_user_ids") or []
    excluded = list(set(excluded + already))

    batch_number = (outreach_request.get("batch_number") or 1) + 1

    targets = select_outreach_targets(
        requester_id=outreach_request["requesting_user_id"],
        university_id=outreach_request["university_id"],
        entities=entities,
        batch_size=outreach_request.get("batch_size") or settings.OUTREACH_BATCH_SIZE,
        excluded_ids=excluded,
    )

    if targets:
        message_template = build_message_template(outreach_request.get("original_question"), entities)
        send_outreach_messages(outreach_request["university_id"], request_id, targets, message_template)
        db.update_outreach_request(
            request_id,
            {
                "batch_number": batch_number,
                "target_user_ids": already + [t["user_id"] for t in targets],
                "excluded_user_ids": excluded,
                "last_round_started_at": datetime.utcnow().isoformat() + "Z",
            },
        )

    return targets


def request_candidate_consent(outreach_request: dict, candidate_user_id: str) -> Optional[dict]:
    """Ask candidate for consent to connect."""
    entities = outreach_request.get("parsed_intent", {}).get("entities") or []
    message = build_consent_request(outreach_request.get("original_question"), entities)
    sent = send_outreach_messages(
        outreach_request["university_id"],
        outreach_request["id"],
        [{"user_id": candidate_user_id, "reason": "consent_request"}],
        message,
    )
    db.update_outreach_request(
        outreach_request["id"],
        {
            "status": "consent_pending",
            "selected_candidate_id": candidate_user_id,
            "requester_consent": True,
        },
    )
    return sent[0] if sent else None


def evaluate_candidate_consent(outreach_request: dict) -> Optional[str]:
    """Check latest consent reply from selected candidate."""
    selected_id = outreach_request.get("selected_candidate_id")
    if not selected_id:
        return None
    messages = db.list_outreach_messages(outreach_request["id"], target_user_id=selected_id)
    for msg in messages:
        response_text = msg.get("response_text")
        if not response_text:
            continue
        reply_type, consent, _ = interpret_reply(response_text)
        if reply_type != "unknown" and consent in {"yes", "no"}:
            db.update_outreach_request(
                outreach_request["id"],
                {"candidate_consent": consent == "yes"},
            )
            return consent
    return None
