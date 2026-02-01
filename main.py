"""Link AI - FastAPI Application."""

from fastapi import FastAPI, Header, HTTPException
import re
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
    LinkRelayStartRequest,
    LinkRelayCollectRequest,
    LinkRelayResponse,
)
import link_logic
import link_orchestrator
import outreach_logic
import rag_index
import supabase_client as db
from intent_classifier import classify_intent, Intent
from state_machine import determine_transition

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


def resolve_task_state(state: dict, status: str, query: Optional[str] = None) -> None:
    """Append to resolved_tasks and clear active task."""
    if not state:
        return
    resolved = state.get("resolved_tasks") or []
    if query:
        resolved.append(
            {
                "id": state.get("active_task", {}).get("id"),
                "type": state.get("active_task", {}).get("type"),
                "query": query,
                "status": status,
                "resolved_at": datetime.utcnow().isoformat() + "Z",
            }
        )
    db.update_link_conversation_state(
        state["id"],
        {
            "mode": "conversation",
            "active_task": None,
            "resolved_tasks": resolved,
            "updated_at": datetime.utcnow().isoformat() + "Z",
        },
    )


def get_display_name(profile: Optional[dict], user_memory: Optional[dict]) -> Optional[str]:
    """Choose preferred name if available, else profile first name."""
    prefs = (user_memory or {}).get("known_preferences") or {}
    preferred = prefs.get("preferred_name")
    if preferred:
        return preferred
    if profile:
        full_name = profile.get("full_name") or ""
        if full_name.strip():
            return full_name.split()[0]
    return None


def build_task_state(active_task: Optional[dict]) -> Optional[dict]:
    if not active_task:
        return None
    return {
        "id": active_task.get("id"),
        "type": active_task.get("type"),
        "status": active_task.get("status"),
        "run_id": active_task.get("run_id"),
    }


def build_ui_hints(mode: str, active_task: Optional[dict]) -> dict:
    return {
        "show_status_button": mode == "outreach",
        "show_cancel_button": mode == "outreach",
        "show_consent_buttons": mode == "awaiting_consent",
    }


def build_conversation_history(conversation_id: str, limit: int = 20) -> str:
    rows = db.list_link_messages(conversation_id, limit=limit)
    parts = []
    for row in rows:
        role = "User" if row.get("sender_type") == "user" else "Link"
        content = row.get("content") or ""
        parts.append(f"{role}: {content}")
    return "\n".join(parts)


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

        user_context = None
        if request.access_token:
            user_context = db.get_user_context_rls(request.access_token, request.user_id)
        if not user_context:
            user_context = db.get_user_context(request.user_id)
        resolved_university_id = request.university_id
        if not resolved_university_id and user_context:
            resolved_university_id = (user_context.get("profile") or {}).get("university_id")
        user_memory = link_orchestrator.update_user_style_memory(
            request.user_id, resolved_university_id, request.message_text
        )
        style_instructions = link_orchestrator.build_style_instructions(user_memory)
        memory_context = db.get_user_memory(request.user_id) or {}
        convo_state = db.get_or_create_link_conversation_state(request.user_id, convo["id"])
        active_task = convo_state.get("active_task")
        intent_result = classify_intent(request.message_text, active_task=active_task)
        lower = (request.message_text or "").lower().strip()
        active_run = db.get_latest_active_outreach_run(request.user_id)
        # If this is a follow-up to a recent org/club query, treat it as club search.
        if intent_result.intent == Intent.FOLLOWUP:
            resolved = convo_state.get("resolved_tasks") or []
            last = resolved[-1] if resolved else None
            if last and (last.get("type") in {"db_query", "club_search"} or "club" in (last.get("query") or "")):
                intent_result = classify_intent("club", active_task=active_task)
        intent_map = {
            Intent.EVENT_SEARCH: "event_search",
            Intent.PEOPLE_SEARCH: "person_search",
            Intent.CLUB_SEARCH: "club_search",
            Intent.CAMPUS_INFO: "campus_info",
            Intent.DB_QUERY: "campus_info",
            Intent.COUNT_QUERY: "campus_info",
            Intent.FOOD: "campus_info",
            Intent.HOUSING: "campus_info",
            Intent.TECH: "campus_info",
            Intent.SAFETY: "campus_info",
            Intent.TRANSPORT: "campus_info",
            Intent.HEALTH: "campus_info",
            Intent.CAREER: "campus_info",
            Intent.SPORTS: "campus_info",
            Intent.STUDY: "campus_info",
            Intent.SOCIAL: "campus_info",
            Intent.MARKETPLACE: "campus_info",
            Intent.PROFILE_QUESTION: "casual_chat",
            Intent.PROFILE_CLASSES: "casual_chat",
            Intent.ACTIVITY_RECALL: "casual_chat",
        }
        intent_name = intent_map.get(intent_result.intent, "casual_chat")
        intent = {
            "intent": intent_name,
            "tags": intent_result.entities,
            "time_window": None,
        }
        intent["user_context"] = {"profile": user_context.get("profile"), "classes": user_context.get("classes"), "clubs": user_context.get("clubs"), "memory": memory_context}
        pre_records = None
        db_answerable = False
        if intent_result.intent == Intent.PEOPLE_SEARCH:
            pre_records = link_orchestrator.retrieve_candidates(
                "person_search",
                intent_result.entities,
                None,
                request.university_id,
                access_token=request.access_token,
            )
            db_answerable = bool(pre_records.get("profiles"))
        elif intent_result.intent in {
            Intent.CLUB_SEARCH,
            Intent.EVENT_SEARCH,
            Intent.CAMPUS_INFO,
            Intent.DB_QUERY,
            Intent.COUNT_QUERY,
            Intent.FOOD,
            Intent.HOUSING,
            Intent.TECH,
            Intent.SAFETY,
            Intent.TRANSPORT,
            Intent.HEALTH,
            Intent.CAREER,
            Intent.SPORTS,
            Intent.STUDY,
            Intent.SOCIAL,
            Intent.MARKETPLACE,
        }:
            pre_records = link_orchestrator.retrieve_candidates(
                intent_map.get(intent_result.intent, "campus_info"),
                intent_result.entities,
                None,
                request.university_id,
                access_token=request.access_token,
            )
            # Avoid outreach for non-people intents; stay in conversation mode.
            db_answerable = True
        transition = determine_transition(
            convo_state.get("mode") or "idle",
            intent_result,
            request.message_text,
            active_task=active_task,
            db_answerable=db_answerable,
        )
        mode = transition.mode
        active_task = transition.active_task
        # If user starts a new non-followup question, clear any old outreach UI state.
        if mode == "outreach" and intent_result.intent not in {Intent.FOLLOWUP, Intent.CONSENT_RESPONSE}:
            mode = "conversation"
            active_task = None
            db.update_link_conversation_state(
                convo_state["id"],
                {
                    "mode": "conversation",
                    "active_task": None,
                    "updated_at": datetime.utcnow().isoformat() + "Z",
                },
            )
        db.update_link_conversation_state(
            convo_state["id"],
            {
                "mode": mode,
                "active_task": active_task,
                "updated_at": datetime.utcnow().isoformat() + "Z",
            },
        )
        if intent_result.intent == Intent.PROFILE_QUESTION:
            profile = user_context.get("profile") if user_context else None
            prefs = (user_memory or {}).get("known_preferences") or {}
            preferred = prefs.get("preferred_name")
            likes = prefs.get("likes") or []
            name = preferred or (profile.get("full_name") if profile else None) or "friend"
            major = profile.get("major") if profile else None
            interests = profile.get("interests") or []
            if isinstance(interests, str):
                interests = [interests]
            parts = [f"you're {name}"]
            if major:
                parts.append(f"{major} major")
            if interests:
                parts.append(f"into {', '.join(interests[:3])}")
            if likes and not interests:
                parts.append(f"you like {likes[0]}")
            reply = ", ".join(parts) + ". want me to update anything?"
            link_orchestrator.insert_link_response(
                convo["id"],
                request.university_id,
                reply,
                citations=[],
                cards={},
                confidence=0.8,
                session_id=session["id"] if session else None,
                task_state="answered",
            )
            resolve_task_state(convo_state, "resolved", query=request.message_text)
            return LinkAgentResponse(
                mode="answered",
                confidence=0.8,
                answer_text=reply,
                citations=[],
                task=None,
                ui=build_ui_hints("conversation", None),
            )

        if intent_result.intent == Intent.ACTIVITY_RECALL:
            convo_history_rows = db.list_link_messages(convo["id"], limit=20)
            recent_user_msgs = [
                r.get("content") for r in convo_history_rows if r.get("sender_type") == "user" and r.get("content")
            ]
            memories = ((user_memory or {}).get("conversation_state") or {}).get("memories") or []
            recall = link_orchestrator.recall_recent_activity(request.message_text, recent_user_msgs, memories)
            reply = recall or "i don't think you told me yet — what'd you do?"
            link_orchestrator.insert_link_response(
                convo["id"],
                request.university_id,
                reply,
                citations=[],
                cards={},
                confidence=0.6 if recall else 0.2,
                session_id=session["id"] if session else None,
                task_state="answered",
            )
            resolve_task_state(convo_state, "resolved", query=request.message_text)
            return LinkAgentResponse(
                mode="answered",
                confidence=0.6 if recall else 0.2,
                answer_text=reply,
                citations=[],
                task=None,
                ui=build_ui_hints("conversation", None),
            )

        if intent_result.intent == Intent.PROFILE_CLASSES:
            classes = (user_context or {}).get("classes") or []
            if classes:
                if isinstance(classes[0], str):
                    names = classes
                else:
                    names = [c.get("name") or c.get("title") or c.get("code") for c in classes]
                names = [n for n in names if n]
                if names:
                    reply = "you're taking: " + ", ".join(names[:6]) + "."
                else:
                    reply = "i don't see your schedule yet. want me to pull it in?"
            else:
                reply = "i don't see your schedule yet. want me to pull it in?"
            link_orchestrator.insert_link_response(
                convo["id"],
                request.university_id,
                reply,
                citations=[],
                cards={},
                confidence=0.8,
                session_id=session["id"] if session else None,
                task_state="answered",
            )
            resolve_task_state(convo_state, "resolved", query=request.message_text)
            return LinkAgentResponse(
                mode="answered",
                confidence=0.8,
                answer_text=reply,
                citations=[],
                task=None,
                ui=build_ui_hints("conversation", None),
            )

        if mode == "awaiting_consent" and intent_result.intent == Intent.CONSENT_RESPONSE:
            active_run = db.get_latest_active_outreach_run(request.user_id)
            if active_run and active_run.get("status") == "awaiting_consent":
                suggested = active_run.get("suggested_connection_user_id")
                if lower in {"yes", "yep", "yeah", "yup", "ok", "okay", "sure"} and suggested:
                    consent = link_orchestrator.resolve_consent(
                        active_run["id"],
                        request.user_id,
                        suggested,
                        requester_ok=True,
                        target_ok=True,
                    )
                    reply = "connected. i made a chat."
                    db.update_link_conversation_state(
                        convo_state["id"],
                        {
                            "mode": "conversation",
                            "active_task": None,
                            "updated_at": datetime.utcnow().isoformat() + "Z",
                        },
                    )
                    link_orchestrator.insert_link_response(
                        convo["id"],
                        request.university_id,
                        reply,
                        citations=[],
                        cards={},
                        confidence=0.6,
                        session_id=session["id"] if session else None,
                        task_state="resolved",
                    )
                    return LinkAgentResponse(
                        mode="answered",
                        confidence=0.6,
                        answer_text=reply,
                        citations=[],
                        task=None,
                        ui=build_ui_hints("conversation", None),
                    )
                # requester declined
                db.update_link_outreach_run(
                    active_run["id"],
                    {"status": "collecting", "updated_at": datetime.utcnow().isoformat() + "Z"},
                )
                reply = "all good. i won’t connect you. want me to keep looking?"
                db.update_link_conversation_state(
                    convo_state["id"],
                    {
                        "mode": "conversation",
                        "active_task": None,
                        "updated_at": datetime.utcnow().isoformat() + "Z",
                    },
                )
                link_orchestrator.insert_link_response(
                    convo["id"],
                    request.university_id,
                    reply,
                    citations=[],
                    cards={},
                    confidence=0.4,
                    session_id=session["id"] if session else None,
                    task_state="resolved",
                )
            return LinkAgentResponse(
                mode="answered",
                confidence=0.4,
                answer_text=reply,
                citations=[],
                task=None,
                ui=build_ui_hints("conversation", None),
            )

        # DB-first: answer simple queries before any LLM calls.
        if intent["intent"] != "casual_chat":
            pre_records = pre_records or link_orchestrator.retrieve_candidates(
                intent["intent"],
                intent["tags"],
                intent["time_window"],
                request.university_id,
                access_token=request.access_token,
            )
        else:
            pre_records = pre_records or {"events": [], "orgs": [], "profiles": [], "facts": []}
        db_first = link_orchestrator.try_db_query(request.message_text, intent["intent"], pre_records, tags=intent.get("tags") or [])
        if db_first:
            if db_first.get("type") == "count_orgs":
                count = db.get_organizations_count(request.university_id)
                reply = f"looks like there are {count} orgs on campus."
                link_orchestrator.insert_link_response(
                    convo["id"],
                    request.university_id,
                    reply,
                    citations=[],
                    cards={},
                    confidence=0.8,
                    session_id=session["id"] if session else None,
                    task_state="answered",
                )
                resolve_task_state(convo_state, "resolved", query=request.message_text)
                return LinkAgentResponse(
                    mode="answered",
                    confidence=0.8,
                    answer_text=reply,
                    citations=[],
                    task=None,
                    ui=build_ui_hints("conversation", None),
                )
            if db_first.get("type") == "count_events":
                count = db.get_events_count(request.university_id)
                reply = f"looks like there are {count} events on campus."
                link_orchestrator.insert_link_response(
                    convo["id"],
                    request.university_id,
                    reply,
                    citations=[],
                    cards={},
                    confidence=0.8,
                    session_id=session["id"] if session else None,
                    task_state="answered",
                )
                resolve_task_state(convo_state, "resolved", query=request.message_text)
                return LinkAgentResponse(
                    mode="answered",
                    confidence=0.8,
                    answer_text=reply,
                    citations=[],
                    task=None,
                    ui=build_ui_hints("conversation", None),
                )
            if db_first.get("type") == "count_users":
                count = db.get_profiles_count(request.university_id)
                reply = f"looks like there are {count} users on the app."
                link_orchestrator.insert_link_response(
                    convo["id"],
                    request.university_id,
                    reply,
                    citations=[],
                    cards={},
                    confidence=0.8,
                    session_id=session["id"] if session else None,
                    task_state="answered",
                )
                resolve_task_state(convo_state, "resolved", query=request.message_text)
                return LinkAgentResponse(
                    mode="answered",
                    confidence=0.8,
                    answer_text=reply,
                    citations=[],
                    task=None,
                    ui=build_ui_hints("conversation", None),
                )
            if db_first.get("type") == "count_major":
                major_query = db_first.get("major_query") or "computer science"
                count = db.get_profiles_count_by_major(major_query, request.university_id)
                reply = f"looks like there are {count} {major_query} majors on campus."
                link_orchestrator.insert_link_response(
                    convo["id"],
                    request.university_id,
                    reply,
                    citations=[],
                    cards={},
                    confidence=0.8,
                    session_id=session["id"] if session else None,
                    task_state="answered",
                )
                resolve_task_state(convo_state, "resolved", query=request.message_text)
                return LinkAgentResponse(
                    mode="answered",
                    confidence=0.8,
                    answer_text=reply,
                    citations=[],
                    task=None,
                    ui=build_ui_hints("conversation", None),
                )
            reply = db_first.get("answer_text") or "here's what i found:"
            link_orchestrator.insert_link_response(
                convo["id"],
                request.university_id,
                reply,
                citations=db_first.get("citations") or [],
                cards={},
                confidence=db_first.get("confidence", 0.7),
                session_id=session["id"] if session else None,
                task_state="answered",
            )
            cards_payload = {}
            if db_first.get("type") == "list_orgs":
                cards_payload = {"club_ids": [o.get("id") for o in (db_first.get("items") or []) if o.get("id")]}
                link_orchestrator.insert_cards_from_items(
                    convo["id"],
                    request.university_id,
                    db_first.get("items") or [],
                    "organization",
                    session_id=session["id"] if session else None,
                )
            if db_first.get("type") == "list_events":
                cards_payload = {"event_ids": [e.get("id") for e in (db_first.get("items") or []) if e.get("id")]}
                link_orchestrator.insert_cards_from_items(
                    convo["id"],
                    request.university_id,
                    db_first.get("items") or [],
                    "event",
                    session_id=session["id"] if session else None,
                )
            if db_first.get("type") == "list_people":
                cards_payload = {"user_ids": [p.get("id") for p in (db_first.get("items") or []) if p.get("id")]}
                link_orchestrator.insert_cards_from_items(
                    convo["id"],
                    request.university_id,
                    db_first.get("items") or [],
                    "profile",
                    session_id=session["id"] if session else None,
                )
            resolve_task_state(convo_state, "resolved", query=request.message_text)
            return LinkAgentResponse(
                mode="answered",
                confidence=db_first.get("confidence", 0.7),
                answer_text=reply,
                cards=cards_payload,
                citations=db_first.get("citations") or [],
                task=None,
                ui=build_ui_hints("conversation", None),
            )
        # If it's a non-people query and we didn't find anything, ask to clarify rather than outreach.
        if intent_result.intent in {
            Intent.CLUB_SEARCH,
            Intent.EVENT_SEARCH,
            Intent.CAMPUS_INFO,
            Intent.DB_QUERY,
            Intent.COUNT_QUERY,
            Intent.FOOD,
            Intent.HOUSING,
            Intent.TECH,
            Intent.SAFETY,
            Intent.TRANSPORT,
            Intent.HEALTH,
            Intent.CAREER,
            Intent.SPORTS,
            Intent.STUDY,
            Intent.SOCIAL,
            Intent.MARKETPLACE,
        }:
            reply = "i don't see that in campus data yet. want me to ask around?"
            link_orchestrator.insert_link_response(
                convo["id"],
                request.university_id,
                reply,
                citations=[],
                cards={},
                confidence=0.4,
                session_id=session["id"] if session else None,
                task_state="clarifying",
            )
            resolve_task_state(convo_state, "resolved", query=request.message_text)
            return LinkAgentResponse(
                mode="answered",
                confidence=0.4,
                answer_text=reply,
                citations=[],
                task=None,
                ui=build_ui_hints("conversation", None),
            )

        capability = link_orchestrator.route_capability(request.message_text, intent)

        if mode == "conversation":
            profile = user_context.get("profile") if user_context else None
            recent_link_msgs = db.list_recent_link_messages(convo["id"], sender_type="link", limit=3)
            last_link_text = " ".join([m.get("content") or "" for m in recent_link_msgs]).lower()
            if "update anything" in last_link_text and "?" not in lower:
                prefs = (user_memory or {}).get("known_preferences") or {}
                likes = prefs.get("likes") or []
                for part in re.split(r",| and |/|&", request.message_text):
                    value = (part or "").strip()
                    if value and value.lower() not in [x.lower() for x in likes]:
                        likes.append(value)
                if likes:
                    prefs["likes"] = likes[-5:]
                    db.upsert_user_memory(request.user_id, {"known_preferences": prefs})
                    reply = "bet, i’ll remember that."
                else:
                    reply = "gotchu. want me to add anything specific?"
                link_orchestrator.insert_link_response(
                    convo["id"],
                    request.university_id,
                    reply,
                    citations=[],
                    cards={},
                    confidence=0.4,
                    session_id=session["id"] if session else None,
                    task_state="conversation",
                )
                return LinkAgentResponse(
                    mode="answered",
                    confidence=0.4,
                    answer_text=reply,
                    citations=[],
                    task=None,
                    ui=build_ui_hints("conversation", None),
                )
            if any(x in lower for x in ["end that task", "stop asking", "cancel that", "drop that", "stop that"]):
                if active_run:
                    db.update_link_outreach_run(
                        active_run["id"],
                        {"status": "failed", "updated_at": datetime.utcnow().isoformat() + "Z"},
                    )
                reply = "got it - i'll stop that and just chat."
            elif "call me" in lower or "i go by" in lower:
                preferred = None
                for token in ["call me", "i go by", "you can call me"]:
                    if token in lower:
                        preferred = lower.split(token, 1)[-1].strip().split(" ")[0]
                        break
                if preferred:
                    db.upsert_user_memory(
                        request.user_id,
                        {"known_preferences": {"preferred_name": preferred}},
                    )
                    reply = f"gotchu. i'll call you {preferred}."
                else:
                    reply = "gotchu. what should i call you?"
            elif any(x in lower for x in ["who am i", "do you know me", "what do you know about me", "tell me about myself", "about myself"]):
                if profile:
                    display = get_display_name(profile, user_memory) or "friend"
                    username = profile.get("username")
                    major = profile.get("major")
                    interests = profile.get("interests") or []
                    if isinstance(interests, str):
                        interests = [interests]
                    summary_parts = [f"you're {display}"]
                    if username:
                        summary_parts.append(f"(@{username})")
                    if major:
                        summary_parts.append(f"majoring in {major}")
                    if interests:
                        summary_parts.append(f"into {', '.join(interests[:3])}")
                    reply = "i know that " + " ".join(summary_parts) + "."
                else:
                    reply = "i don't see your profile yet. want to fill it in?"
            elif "what are you asking" in lower or "what are you asking them" in lower:
                if active_run and active_run.get("query"):
                    reply = f"i'm asking about: \"{active_run.get('query')}\". want me to check in?"
                else:
                    reply = "no active asks right now. want me to find something?"
            elif "did you text" in lower or "did you message" in lower:
                if active_run and active_run.get("query"):
                    reply = f"yep. i texted a few people about \"{active_run.get('query')}\"."
                else:
                    reply = "not yet. want me to ask around?"
            elif "that's not me" in lower or "thats not me" in lower:
                reply = "oops, my bad. want me to update what i know about you?"
            else:
                smalltalk_type = link_orchestrator.classify_smalltalk(request.message_text)
                convo_history = build_conversation_history(convo["id"], limit=20)
                if smalltalk_type == "capabilities":
                    reply = link_orchestrator.generate_capabilities_response(
                        request.message_text, user_memory, conversation_history=convo_history
                    )
                else:
                    recent_user_msgs = [
                        m.get("content")
                        for m in db.list_recent_link_messages(convo["id"], sender_type="user", limit=5)
                        if m.get("content")
                    ]
                    reply = link_orchestrator.generate_small_talk_response(
                        request.message_text,
                        user_memory,
                        recent_user_messages=recent_user_msgs,
                        conversation_history=convo_history,
                    )
            if any(x in lower for x in ["end that task", "stop asking", "cancel that", "drop that", "stop that"]):
                db.update_link_conversation_state(
                    convo_state["id"],
                    {
                        "mode": "conversation",
                        "active_task": None,
                        "updated_at": datetime.utcnow().isoformat() + "Z",
                    },
                )
            link_orchestrator.insert_link_response(
                convo["id"],
                request.university_id,
                reply,
                citations=[],
                cards={},
                confidence=0.2,
                session_id=session["id"] if session else None,
                task_state="conversation",
            )
            # Optional class check-in only when user is already in a check-in vibe.
            if smalltalk_type == "checkin":
                class_to_check = link_orchestrator.should_ask_class_checkin(user_memory)
                if class_to_check and not active_run:
                    checkin = f"how was {class_to_check.upper()} today? what'd you learn?"
                    link_orchestrator.insert_link_response(
                        convo["id"],
                        request.university_id,
                        checkin,
                        citations=[],
                        cards={},
                        confidence=0.2,
                        session_id=session["id"] if session else None,
                    )
                    db.upsert_user_memory(
                        request.user_id,
                        {"last_class_checkin": datetime.utcnow().isoformat() + "Z"},
                    )
            return LinkAgentResponse(
                mode="answered",
                confidence=0.2,
                answer_text=reply,
                citations=[],
                task=None,
                ui=build_ui_hints("conversation", None),
            )

        if capability.get("clarify_question"):
            clarifying = capability.get("clarify_question")
            link_orchestrator.insert_link_response(
                convo["id"],
                request.university_id,
                clarifying,
                citations=[],
                cards={},
                confidence=0.4,
                session_id=session["id"] if session else None,
                task_state="clarifying",
            )
            return LinkAgentResponse(
                mode="answered",
                confidence=0.4,
                answer_text=clarifying,
                citations=[],
                task=build_task_state(active_task),
                ui=build_ui_hints("agent", active_task),
            )

        if (
            mode != "agent"
            and not capability.get("can_answer_from_db")
            and capability.get("needs_outreach")
            and intent_result.intent == Intent.PEOPLE_SEARCH
        ):
            lower = (request.message_text or "").lower()
            if lower.strip() in {"yo", "hey", "hi", "sup", "what's up", "whats up"} or len(lower.strip()) <= 3:
                reply = link_orchestrator.generate_small_talk_response(request.message_text, user_memory)
                link_orchestrator.insert_link_response(
                    convo["id"],
                    request.university_id,
                    reply,
                    citations=[],
                    cards={},
                    confidence=0.2,
                    session_id=session["id"] if session else None,
                )
                return LinkAgentResponse(
                    mode="answered",
                    confidence=0.2,
                    answer_text=reply,
                    citations=[],
                    task=None,
                    ui=build_ui_hints("conversation", None),
                )
            outreach = link_orchestrator.start_outreach(
                request.user_id,
                request.university_id,
                convo["id"],
                request.message_text,
                intent,
                session_id=session["id"] if session else None,
                access_token=request.access_token,
            )
            if active_task:
                active_task = dict(active_task)
                active_task["status"] = "outreach_sent"
                active_task["run_id"] = outreach.get("run_id")
            db.update_link_conversation_state(
                convo_state["id"],
                {
                    "mode": "outreach",
                    "active_task": active_task,
                    "updated_at": datetime.utcnow().isoformat() + "Z",
                },
            )
            return LinkAgentResponse(
                mode="outreach_started",
                confidence=0.4,
                run_id=outreach["run_id"],
                task=build_task_state(active_task),
                ui=build_ui_hints("outreach", active_task),
            )
        elif (
            mode != "agent"
            and not capability.get("can_answer_from_db")
            and capability.get("needs_outreach")
            and intent_result.intent != Intent.PEOPLE_SEARCH
        ):
            clarifying = "can you be a lil more specific so i can check the db?"
            link_orchestrator.insert_link_response(
                convo["id"],
                request.university_id,
                clarifying,
                citations=[],
                cards={},
                confidence=0.4,
                session_id=session["id"] if session else None,
                task_state="clarifying",
            )
            return LinkAgentResponse(
                mode="answered",
                confidence=0.4,
                answer_text=clarifying,
                citations=[],
                task=None,
                ui=build_ui_hints("conversation", None),
            )

        # Handle simple count questions directly (no outreach)
        q_lower = (request.message_text or "").lower()
        if "how many" in q_lower:
            if any(x in q_lower for x in ["org", "organization", "organizations", "club", "clubs"]):
                count = db.get_organizations_count(request.university_id)
                reply = f"looks like there are {count} orgs on campus."
                link_orchestrator.insert_link_response(
                    convo["id"],
                    request.university_id,
                    reply,
                    citations=[],
                    cards={},
                    confidence=0.8,
                    session_id=session["id"] if session else None,
                )
                resolve_task_state(convo_state, "resolved", query=request.message_text)
                return LinkAgentResponse(
                    mode="answered",
                    confidence=0.8,
                    answer_text=reply,
                    citations=[],
                    task=None,
                    ui=build_ui_hints("conversation", None),
                )
            if any(x in q_lower for x in ["event", "events"]):
                count = db.get_events_count(request.university_id)
                reply = f"looks like there are {count} events on campus."
                link_orchestrator.insert_link_response(
                    convo["id"],
                    request.university_id,
                    reply,
                    citations=[],
                    cards={},
                    confidence=0.8,
                    session_id=session["id"] if session else None,
                )
                resolve_task_state(convo_state, "resolved", query=request.message_text)
                return LinkAgentResponse(
                    mode="answered",
                    confidence=0.8,
                    answer_text=reply,
                    citations=[],
                    task=None,
                    ui=build_ui_hints("conversation", None),
                )

        records = pre_records or {"events": [], "orgs": [], "profiles": [], "facts": []}
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
                resolve_task_state(convo_state, "resolved", query=request.message_text)
                return LinkAgentResponse(
                    mode="answered",
                    confidence=cached_answer.get("confidence", 0.0),
                    answer_text=cached_answer.get("answer_text"),
                    cards={},
                    citations=cached_answer.get("citations") or [],
                    task=None,
                    ui=build_ui_hints("conversation", None),
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
            more_options = False
            if intent.get("intent") == "person_search":
                all_people = [p.get("id") for p in records.get("profiles", []) if p.get("id")]
                if len(all_people) > 2:
                    cards["user_ids"] = (cards.get("user_ids") or all_people)[:2]
                    more_options = True
            link_orchestrator.insert_link_response(
                convo["id"],
                request.university_id,
                answer.get("answer_text") or "Here's what I found.",
                citations=answer.get("citations") or [],
                cards=cards,
                confidence=confidence,
                session_id=session["id"] if session else None,
                task_state="answered",
            )
            if more_options:
                link_orchestrator.insert_link_response(
                    convo["id"],
                    request.university_id,
                    "i found a couple options. want more?",
                    citations=[],
                    cards={},
                    confidence=0.4,
                    session_id=session["id"] if session else None,
                )
            link_orchestrator.write_verified_facts_from_records(
                request.university_id,
                records,
                answer.get("citations") or [],
                answer.get("answer_text") or "",
                confidence,
            )
            resolve_task_state(convo_state, "resolved", query=request.message_text)
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
                task=None,
                ui=build_ui_hints("conversation", None),
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
                task_state="clarifying",
            )
            if active_task:
                active_task = dict(active_task)
                active_task["status"] = "awaiting_user"
            db.update_link_conversation_state(
                convo_state["id"],
                {
                    "mode": "agent",
                    "active_task": active_task,
                    "updated_at": datetime.utcnow().isoformat() + "Z",
                },
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
                answer_text=clarifying,
                citations=[],
                task=build_task_state(active_task),
                ui=build_ui_hints("agent", active_task),
            )

        if intent_result.intent != Intent.PEOPLE_SEARCH:
            clarifying = "i don't see that in campus data yet. want me to ask around?"
            link_orchestrator.insert_link_response(
                convo["id"],
                request.university_id,
                clarifying,
                citations=[],
                cards={},
                confidence=0.4,
                session_id=session["id"] if session else None,
                task_state="clarifying",
            )
            resolve_task_state(convo_state, "resolved", query=request.message_text)
            return LinkAgentResponse(
                mode="answered",
                confidence=0.4,
                answer_text=clarifying,
                citations=[],
                task=None,
                ui=build_ui_hints("conversation", None),
            )

        outreach = link_orchestrator.start_outreach(
            request.user_id,
            request.university_id,
            convo["id"],
            request.message_text,
            intent,
            session_id=session["id"] if session else None,
            access_token=request.access_token,
        )
        if active_task:
            active_task = dict(active_task)
            active_task["status"] = "outreach_sent"
            active_task["run_id"] = outreach.get("run_id")
        db.update_link_conversation_state(
            convo_state["id"],
            {
                "mode": "outreach",
                "active_task": active_task,
                "updated_at": datetime.utcnow().isoformat() + "Z",
            },
        )
        return LinkAgentResponse(
            mode="outreach_started",
            confidence=confidence,
            run_id=outreach["run_id"],
            task=build_task_state(active_task),
            ui=build_ui_hints("outreach", active_task),
        )
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


@app.post("/link/relay/start", response_model=LinkRelayResponse)
async def link_relay_start(request: LinkRelayStartRequest):
    try:
        validate_uuid(request.requester_user_id, "requester_user_id")
        validate_uuid(request.target_user_id, "target_user_id")
        result = link_orchestrator.start_link_relay(
            request.requester_user_id,
            request.requester_conversation_id,
            request.target_user_id,
            request.question,
            request.university_id,
            session_id=request.session_id,
        )
        return LinkRelayResponse(status="awaiting_target", run_id=result.get("run_id"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/link/relay/collect", response_model=LinkRelayResponse)
async def link_relay_collect(request: LinkRelayCollectRequest):
    try:
        result = link_orchestrator.collect_link_relay(
            request.run_id,
            request.university_id,
            session_id=request.session_id,
        )
        return LinkRelayResponse(status=result.get("status"), run_id=request.run_id)
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
