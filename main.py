"""Link AI - FastAPI Application."""

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
from datetime import datetime
from uuid import UUID

from config import settings
from schemas import (
    QueryRequest,
    QueryResponse,
    HealthResponse,
    OutreachStartRequest,
    OutreachStartResponse,
    OutreachProcessRequest,
    OutreachProcessResponse,
    OutreachRequesterConsentRequest,
    OutreachConsentResponse,
    OutreachReplyRequest,
    ConnectRequest,
    ConnectResponse,
    StyleLearnRequest,
    StyleLearnResponse,
    StyleProfileResponse,
    ReindexRequest,
    LinkAgentRequest,
    LinkAgentResponse,
    LinkOutreachCollectRequest,
    LinkOutreachCollectResponse,
    LinkConsentResolveRequest,
    LinkConsentResolveResponse,
)
import link_logic
import link_orchestrator
import outreach_logic
import rag_index
import supabase_client as db

app = FastAPI(
    title="Link AI",
    description="Intelligent AI agent for campus communities",
    version="1.0.0",
)

def validate_uuid(value: str, field_name: str) -> None:
    """Validate UUID input and raise 400 on failure."""
    if value is None or value == "":
        raise HTTPException(status_code=400, detail=f"{field_name} is required")
    try:
        UUID(str(value))
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{field_name} must be a valid UUID")


@app.on_event("startup")
async def startup_tasks():
    """Optional startup tasks."""
    if settings.REINDEX_ON_START:
        try:
            rag_index.build_index()
        except Exception:
            pass

# CORS (dev-friendly; tighten in prod)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============ Health & Status ============

@app.get("/")
async def root():
    """Root endpoint."""
    return {"service": "link-ai", "status": "running"}


@app.get("/health", response_model=HealthResponse)
async def health():
    """Health check endpoint with system status."""
    missing_config = settings.validate()
    
    # Get facts count if possible
    facts_count = 0
    try:
        facts_count = db.get_facts_count()
    except Exception:
        pass
    
    return HealthResponse(
        status="ok" if not missing_config else "degraded",
        rag_indexed=rag_index.is_indexed(),
        facts_count=facts_count,
        missing_config=missing_config,
    )


# ============ Main Query Endpoint ============

@app.post("/query", response_model=QueryResponse)
async def query(request: QueryRequest):
    """Main query endpoint - Link's brain."""
    try:
        result = link_logic.process_query(
            user_id=request.user_id,
            university_id=request.university_id,
            question=request.question,
            conversation_history=request.conversation_history,
            session_id=request.session_id,
        )
        if result.get("need_outreach") and not result.get("outreach_request_id"):
            intent = result.get("intent")
            outreach_payload = {
                "university_id": request.university_id,
                "requesting_user_id": request.user_id,
                "original_question": request.question,
                "parsed_intent": intent.dict() if intent else {},
                "search_category": (intent.type if intent else "unknown"),
                "search_criteria": {"entities": (intent.entities if intent else [])},
                "status": "pending",
                "batch_size": settings.OUTREACH_BATCH_SIZE,
                "max_attempts": settings.MAX_OUTREACH_BATCHES,
                "time_per_round_minutes": settings.OUTREACH_WAIT_MINUTES,
                "target_confidence_threshold": settings.OUTREACH_CONFIDENCE_THRESHOLD,
                "hard_cap": settings.OUTREACH_HARD_CAP,
                "excluded_user_ids": [request.user_id],
            }
            outreach = outreach_logic.start_outreach(outreach_payload)
            result["outreach_request_id"] = outreach["request"]["id"]
            result["data"] = {
                "need_outreach": True,
                "outreach_request_id": outreach["request"]["id"],
                "status": "collecting",
                "message": "I'm not confident yet. I can ask a few relevant students.",
            }
        return QueryResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============ Link Orchestrator Endpoints ============

@app.post("/link/agent", response_model=LinkAgentResponse)
async def link_agent(request: LinkAgentRequest):
    """Handle Link chat message with grounded answer or outreach."""
    try:
        validate_uuid(request.user_id, "user_id")
        validate_uuid(request.university_id, "university_id")
        convo = db.get_or_create_link_conversation(request.user_id)
        if not convo:
            raise HTTPException(status_code=404, detail="Link conversation not found")

        session = None
        if request.session_id:
            session = db.get_link_session_for_user(request.session_id, request.user_id)
        if not session:
            session = db.get_or_create_link_session(request.user_id, request.university_id)
        if session:
            db.set_link_conversation_session(convo["id"], session["id"])

        db.insert_link_message(
            convo["id"],
            request.user_id,
            request.message_text,
            {"shareType": "text"},
            session_id=session["id"] if session else None,
            sender_type="user",
        )

        user_memory = link_orchestrator.update_user_style_memory(
            request.user_id, request.university_id, request.message_text
        )
        style_instructions = link_orchestrator.build_style_instructions(user_memory)

        intent = link_orchestrator.route_intent(request.message_text)
        mode = link_orchestrator.determine_mode(request.message_text, intent)
        if mode == "conversation":
            reply = link_orchestrator.generate_small_talk_response(
                request.message_text, user_memory
            )
            link_orchestrator.insert_link_response(
                convo["id"],
                request.university_id,
                reply,
                citations=[],
                cards={},
                confidence=0.2,
                session_id=session["id"] if session else None,
            )
            return LinkAgentResponse(mode="answered", confidence=0.2, answer_text=reply, citations=[])

        records = link_orchestrator.retrieve_candidates(
            intent["intent"],
            intent["tags"],
            intent["time_window"],
            request.university_id,
            access_token=request.access_token,
        )
        cached_facts = records.get("facts") or []
        if cached_facts:
            cached_answer = link_orchestrator.compose_cached_answer(
                request.message_text, cached_facts, style_instructions=style_instructions
            )
            if (
                cached_answer["answer_mode"] == "direct"
                and cached_answer.get("citations")
                and link_orchestrator.validate_cached_citations(cached_answer.get("citations"), cached_facts)
            ):
                link_orchestrator.insert_link_response(
                    convo["id"],
                    request.university_id,
                    cached_answer.get("answer_text") or "Here's what I found.",
                    citations=cached_answer.get("citations") or [],
                    cards={},
                    confidence=cached_answer.get("confidence", 0.0),
                    session_id=session["id"] if session else None,
                )
                return LinkAgentResponse(
                    mode="answered",
                    confidence=cached_answer.get("confidence", 0.0),
                    answer_text=cached_answer.get("answer_text"),
                    cards={},
                    citations=cached_answer.get("citations") or [],
                )
        answer = link_orchestrator.compose_grounded_answer(
            request.message_text, records, style_instructions=style_instructions
        )
        if answer.get("answer_mode") == "direct" and not answer.get("citations"):
            answer["answer_mode"] = "ask_clarifying"
        db_confidence = link_orchestrator.compute_db_confidence(records, intent["tags"], intent["time_window"])
        confidence = min(max(answer["confidence"], 0.0), db_confidence)

        if (
            answer["answer_mode"] == "direct"
            and answer.get("citations")
            and link_orchestrator.validate_record_citations(answer.get("citations"), records)
            and confidence >= settings.CONFIDENCE_THRESHOLD
        ):
            cards = answer.get("cards") or {}
            valid_event_ids = {e.get("id") for e in records.get("events", []) if e.get("id")}
            valid_user_ids = {p.get("id") for p in records.get("profiles", []) if p.get("id")}
            valid_club_ids = {o.get("id") for o in records.get("orgs", []) if o.get("id")}
            cards = {
                "event_ids": [cid for cid in cards.get("event_ids", []) if cid in valid_event_ids],
                "user_ids": [cid for cid in cards.get("user_ids", []) if cid in valid_user_ids],
                "club_ids": [cid for cid in cards.get("club_ids", []) if cid in valid_club_ids],
            }
            link_orchestrator.insert_link_response(
                convo["id"],
                request.university_id,
                answer.get("answer_text") or "Here's what I found.",
                citations=answer.get("citations") or [],
                cards=cards,
                confidence=confidence,
                session_id=session["id"] if session else None,
            )
            link_orchestrator.write_verified_facts_from_records(
                request.university_id,
                records,
                answer.get("citations") or [],
                answer.get("answer_text") or "",
                confidence,
            )
            follow_up = link_orchestrator.generate_friend_checkin(user_memory)
            if follow_up:
                link_orchestrator.insert_link_response(
                    convo["id"],
                    request.university_id,
                    follow_up,
                    citations=[],
                    cards={},
                    confidence=0.2,
                    session_id=session["id"] if session else None,
                )
            return LinkAgentResponse(
                mode="answered",
                confidence=confidence,
                answer_text=answer.get("answer_text"),
                cards=cards,
                citations=answer.get("citations") or [],
            )

        if answer["answer_mode"] == "ask_clarifying":
            clarifying = answer.get("answer_text") or "Can you share a bit more detail so I can look this up?"
            link_orchestrator.insert_link_response(
                convo["id"],
                request.university_id,
                clarifying,
                citations=[],
                cards={},
                confidence=confidence,
                session_id=session["id"] if session else None,
            )
            follow_up = link_orchestrator.generate_friend_checkin(user_memory)
            if follow_up:
                link_orchestrator.insert_link_response(
                    convo["id"],
                    request.university_id,
                    follow_up,
                    citations=[],
                    cards={},
                    confidence=0.2,
                    session_id=session["id"] if session else None,
                )
            return LinkAgentResponse(mode="answered", confidence=confidence, answer_text=clarifying, citations=[])

        outreach = link_orchestrator.start_outreach(
            request.user_id,
            request.university_id,
            convo["id"],
            request.message_text,
            intent,
            session_id=session["id"] if session else None,
            access_token=request.access_token,
        )
        return LinkAgentResponse(mode="outreach_started", confidence=confidence, run_id=outreach["run_id"])
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/link/outreach/collect", response_model=LinkOutreachCollectResponse)
async def link_outreach_collect(request: LinkOutreachCollectRequest):
    """Collect outreach replies and respond in Link chat."""
    try:
        result = link_orchestrator.collect_outreach(
            request.run_id,
            request.university_id,
            session_id=request.session_id,
            access_token=request.access_token,
        )
        return LinkOutreachCollectResponse(
            status=result.get("status"),
            confidence=result.get("confidence"),
            message=result.get("message"),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/link/consent/resolve", response_model=LinkConsentResolveResponse)
async def link_consent_resolve(request: LinkConsentResolveRequest):
    """Resolve two-sided consent and create intro chat."""
    try:
        result = link_orchestrator.resolve_consent(
            request.run_id,
            request.requester_user_id,
            request.target_user_id,
            request.requester_ok,
            request.target_ok,
        )
        return LinkConsentResolveResponse(
            status=result.get("status"),
            conversation_id=result.get("conversation_id"),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============ Outreach Endpoints ============

@app.post("/outreach/start", response_model=OutreachStartResponse)
async def outreach_start(request: OutreachStartRequest):
    """Start an outreach campaign to find information."""
    payload = {
        "university_id": request.university_id,
        "requesting_user_id": request.user_id,
        "original_question": request.question,
        "parsed_intent": request.intent,
        "search_category": request.intent.get("type", "unknown"),
        "search_criteria": request.intent,
        "status": "pending",
        "batch_size": settings.OUTREACH_BATCH_SIZE,
        "max_attempts": settings.MAX_OUTREACH_BATCHES,
        "time_per_round_minutes": settings.OUTREACH_WAIT_MINUTES,
        "target_confidence_threshold": settings.OUTREACH_CONFIDENCE_THRESHOLD,
        "hard_cap": settings.OUTREACH_HARD_CAP,
        "excluded_user_ids": [request.user_id],
    }
    outreach = outreach_logic.start_outreach(payload)
    target_profiles = db.get_profiles_by_ids([t["user_id"] for t in outreach["targets"]])
    name_map = {p.get("id"): p.get("full_name") for p in target_profiles}

    return OutreachStartResponse(
        outreach_request_id=outreach["request"]["id"],
        status="collecting",
        targets=[
            {"user_id": t["user_id"], "name": name_map.get(t["user_id"], ""), "reason": t["reason"]}
            for t in outreach["targets"]
        ],
        message_template=outreach["message_template"],
        estimated_completion=outreach["estimated_completion"],
    )


@app.post("/outreach/process", response_model=OutreachProcessResponse)
async def outreach_process(request: OutreachProcessRequest):
    """Process outreach responses."""
    outreach_request = db.get_outreach_request(request.outreach_request_id)
    if not outreach_request:
        raise HTTPException(status_code=404, detail="Outreach request not found")

    # If waiting on candidate consent, check for reply
    if outreach_request.get("status") == "consent_pending":
        consent = outreach_logic.evaluate_candidate_consent(outreach_request)
        if consent == "yes":
            db.update_outreach_request(outreach_request["id"], {"status": "connecting"})
            candidate_id = outreach_request.get("selected_candidate_id")
            profile = db.get_profile(candidate_id, enforce_public=True) if candidate_id else None
            entities = (outreach_request.get("parsed_intent") or {}).get("entities") or []
            if candidate_id and entities:
                db.create_link_fact(
                    {
                        "entity_type": "profile",
                        "entity_id": candidate_id,
                        "university_id": outreach_request.get("university_id"),
                        "fact_category": "activity",
                        "fact_key": "activity",
                        "fact_value": entities[0],
                        "consent_status": "opt_in",
                        "consent_given_at": datetime.utcnow().isoformat() + "Z",
                        "confidence_score": settings.OUTREACH_CONFIDENCE_THRESHOLD,
                        "source_type": "outreach_reply",
                        "source_id": outreach_request.get("id"),
                        "provenance_chain": [{"outreach_request_id": outreach_request.get("id")}],
                    }
                )
            return OutreachProcessResponse(
                status="candidate_approved",
                responses_received=outreach_request.get("responses_received", 0),
                positive_responses=outreach_request.get("positive_responses", 0),
                facts_created=1 if (candidate_id and entities) else 0,
                matches_found=[],
                updated_confidence=settings.OUTREACH_CONFIDENCE_THRESHOLD,
                profile_card=profile,
                next_actions=["create_chat"],
            )
        if consent == "no":
            db.update_outreach_request(outreach_request["id"], {"status": "collecting"})

    result = outreach_logic.process_outreach_round(outreach_request)

    # If no candidates yet and still collecting, expand outreach
    if result["status"] == "collecting" and not result["candidates"]:
        outreach_request = db.get_outreach_request(request.outreach_request_id)
        outreach_logic.expand_outreach(outreach_request)

    matches = []
    for c in result["candidates"]:
        profile = db.get_profile(c.user_id, enforce_public=True)
        matches.append(
            {
                "user_id": c.user_id,
                "name": profile.get("full_name") if profile else "",
                "consent": c.consent,
                "confidence": c.confidence,
                "evidence": c.evidence,
            }
        )

    return OutreachProcessResponse(
        status=result["status"],
        responses_received=result["responses_received"],
        positive_responses=result["positive_responses"],
        facts_created=0,
        matches_found=matches,
        updated_confidence=max([c.confidence for c in result["candidates"]] + [0.0]),
    )


@app.get("/outreach/status/{outreach_request_id}")
async def outreach_status(outreach_request_id: str):
    """Get current status for an outreach request."""
    outreach_request = db.get_outreach_request(outreach_request_id)
    if not outreach_request:
        raise HTTPException(status_code=404, detail="Outreach request not found")
    return {
        "status": outreach_request.get("status"),
        "responses_received": outreach_request.get("responses_received", 0),
        "positive_responses": outreach_request.get("positive_responses", 0),
        "batch_number": outreach_request.get("batch_number", 1),
        "max_attempts": outreach_request.get("max_attempts", settings.MAX_OUTREACH_BATCHES),
    }


@app.post("/outreach/reply")
async def outreach_reply(request: OutreachReplyRequest):
    """Ingest a reply from a target user."""
    outreach_request = db.get_outreach_request(request.outreach_request_id)
    if not outreach_request:
        raise HTTPException(status_code=404, detail="Outreach request not found")

    # Update the most recent outreach message for this responder
    messages = db.list_outreach_messages(request.outreach_request_id, target_user_id=request.responder_user_id)
    if not messages:
        raise HTTPException(status_code=404, detail="Outreach message not found for responder")

    latest = messages[-1]
    db.update_outreach_message(
        latest["id"],
        {
            "response_text": request.response_text,
            "response_status": "replied",
            "responded_at": datetime.utcnow().isoformat() + "Z",
        },
    )
    return {"status": "ok"}


@app.post("/outreach/requester-consent", response_model=OutreachConsentResponse)
async def outreach_requester_consent(request: OutreachRequesterConsentRequest):
    """Handle requester decision on a candidate."""
    outreach_request = db.get_outreach_request(request.outreach_request_id)
    if not outreach_request:
        raise HTTPException(status_code=404, detail="Outreach request not found")

    decision = request.decision.lower()
    if decision == "ask_more":
        outreach_logic.expand_outreach(outreach_request)
        db.update_outreach_request(outreach_request["id"], {"status": "collecting"})
        return OutreachConsentResponse(status="collecting", action="ask_more", message="Asking a few more people.")
    if decision == "no":
        db.update_outreach_request(outreach_request["id"], {"status": "resolved", "requester_consent": False})
        return OutreachConsentResponse(status="resolved", action="no", message="Got it - no intro sent.")
    if decision == "show_other":
        return OutreachConsentResponse(status="candidate_found", action="show_other", message="Here are other options.")
    if decision == "yes":
        outreach_logic.request_candidate_consent(outreach_request, request.candidate_user_id)
        return OutreachConsentResponse(
            status="consent_pending",
            action="waiting_for_candidate_consent",
            message="Waiting for the candidate to confirm.",
        )

    raise HTTPException(status_code=400, detail="Invalid decision")


# ============ Connection Endpoint ============

@app.post("/connect", response_model=ConnectResponse)
async def connect_users(request: ConnectRequest):
    """Create a connection between users."""
    if not request.target_user_ids:
        raise HTTPException(status_code=400, detail="No target users provided")

    requester_profile = db.get_profile(request.requesting_user_id, enforce_public=False)
    university_id = requester_profile.get("university_id") if requester_profile else None
    link_profile = db.get_link_system_profile(university_id) if university_id else None
    link_sender_id = link_profile.get("link_user_id") if link_profile else None

    convo = db.create_conversation(
        {
            "type": "group" if request.create_group_chat or len(request.target_user_ids) > 1 else "direct",
            "created_by": request.requesting_user_id,
            "is_system_generated": True,
        }
    )

    db.add_conversation_participants(convo["id"], [request.requesting_user_id] + request.target_user_ids)

    intro = f"hey! Link here - i connected you because {request.connection_reason}!"
    if link_sender_id:
        db.insert_message(convo["id"], link_sender_id, intro, {"shareType": "text"})

    connection = db.create_connection(
        {
            "university_id": university_id,
            "user1_id": request.requesting_user_id,
            "user2_id": request.target_user_ids[0],
            "connection_reason": request.connection_reason,
            "conversation_id": convo["id"],
            "status": "introduced",
        }
    )

    return ConnectResponse(
        connection_id=connection["id"],
        conversation_id=convo["id"],
        intro_message=intro,
    )


# ============ Style Learning Endpoints ============

@app.post("/style/learn", response_model=StyleLearnResponse)
async def learn_style(request: StyleLearnRequest):
    """Learn user's communication style from a message."""
    validate_uuid(request.user_id, "user_id")
    profile = db.get_profile(request.user_id, enforce_public=False) or {}
    university_id = profile.get("university_id")
    if not university_id:
        raise HTTPException(status_code=400, detail="university_id is required")
    memory = link_orchestrator.update_user_style_memory(
        request.user_id,
        university_id,
        request.message,
    )
    return StyleLearnResponse(
        style_updated=True,
        current_archetype=memory.get("communication_archetype", "genz_casual"),
        archetype_confidence=float(memory.get("style_confidence") or 0.0),
        messages_analyzed=int(memory.get("messages_analyzed") or 0),
        detected_features=memory.get("detected_style") or {},
    )


@app.get("/style/{user_id}", response_model=StyleProfileResponse)
async def get_style_profile(user_id: str):
    """Get user's detected communication style profile."""
    memory = db.get_user_memory(user_id)
    
    if not memory:
        return StyleProfileResponse(
            archetype="neutral",
            confidence=0.0,
            detected_style={},
            vocabulary_patterns={},
            sample_messages=[],
            messages_analyzed=0,
        )
    
    return StyleProfileResponse(
        archetype=memory.get("communication_archetype", "neutral"),
        confidence=memory.get("style_confidence", 0.0),
        detected_style=memory.get("detected_style", {}),
        vocabulary_patterns=memory.get("vocabulary_patterns", {}),
        sample_messages=memory.get("style_examples", []),
        messages_analyzed=memory.get("messages_analyzed", 0),
    )


# ============ Journal Endpoints ============

@app.get("/journal/{user_id}")
async def get_journal(user_id: str, limit: int = 10):
    """Get journal entries for a user."""
    try:
        entries = db.get_journal_entries(user_id, limit)
        return {"entries": entries}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============ Admin Endpoints ============

@app.post("/reindex")
async def reindex(
    request: ReindexRequest = None,
    x_admin_token: Optional[str] = Header(None),
):
    """Rebuild the RAG index. Requires admin token."""
    if settings.ADMIN_TOKEN and x_admin_token != settings.ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid admin token")
    
    university_id = request.university_id if request else None
    counts = rag_index.build_index(university_id)
    
    return {
        "status": "completed",
        "documents_indexed": counts,
    }


# ============ Evaluation Endpoint ============

@app.get("/eval/run")
async def run_evaluation():
    """Run evaluation suite."""
    # TODO: Implement evaluation harness
    return {
        "metrics": {
            "precision_at_3": 0.0,
            "recall_at_5": 0.0,
            "hallucination_rate": 0.0,
            "abstention_accuracy": 0.0,
            "outreach_trigger_precision": 0.0,
        },
        "test_cases_run": 0,
        "timestamp": None,
    }
