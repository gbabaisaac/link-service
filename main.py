"""Link AI - FastAPI Application."""

from fastapi import FastAPI, Header, HTTPException
from typing import Optional

from config import settings
from schemas import (
    QueryRequest,
    QueryResponse,
    HealthResponse,
    OutreachStartRequest,
    OutreachStartResponse,
    OutreachProcessRequest,
    OutreachProcessResponse,
    ConnectRequest,
    ConnectResponse,
    StyleLearnRequest,
    StyleLearnResponse,
    StyleProfileResponse,
    ReindexRequest,
)
import link_logic
import rag_index
import supabase_client as db

app = FastAPI(
    title="Link AI",
    description="Intelligent AI agent for campus communities",
    version="1.0.0",
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
        )
        return QueryResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============ Outreach Endpoints ============

@app.post("/outreach/start", response_model=OutreachStartResponse)
async def outreach_start(request: OutreachStartRequest):
    """Start an outreach campaign to find information."""
    # TODO: Implement full outreach logic
    from datetime import datetime, timedelta
    import uuid
    
    # For now, return a placeholder response
    return OutreachStartResponse(
        outreach_request_id=str(uuid.uuid4()),
        status="in_progress",
        targets=[],
        message_template="hey! 👋 quick question from link - someone's looking for {activity}. do you {activity}?",
        estimated_completion=(datetime.utcnow() + timedelta(minutes=settings.OUTREACH_WAIT_MINUTES)).isoformat() + "Z",
    )


@app.post("/outreach/process", response_model=OutreachProcessResponse)
async def outreach_process(request: OutreachProcessRequest):
    """Process outreach responses."""
    # TODO: Implement full outreach processing
    return OutreachProcessResponse(
        status="completed",
        responses_received=0,
        positive_responses=0,
        facts_created=0,
        matches_found=[],
        updated_confidence=0.0,
    )


# ============ Connection Endpoint ============

@app.post("/connect", response_model=ConnectResponse)
async def connect_users(request: ConnectRequest):
    """Create a connection between users."""
    import uuid
    
    # TODO: Implement full connection logic (create group chat, etc.)
    return ConnectResponse(
        connection_id=str(uuid.uuid4()),
        conversation_id=str(uuid.uuid4()),
        intro_message=f"hey! Link here - i connected you because {request.connection_reason}! 🎉",
    )


# ============ Style Learning Endpoints ============

@app.post("/style/learn", response_model=StyleLearnResponse)
async def learn_style(request: StyleLearnRequest):
    """Learn user's communication style from a message."""
    # TODO: Implement style analyzer
    return StyleLearnResponse(
        style_updated=True,
        current_archetype="neutral",
        archetype_confidence=0.0,
        messages_analyzed=1,
        detected_features={},
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
