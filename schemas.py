"""Pydantic models for Link AI API."""

from typing import Optional
from pydantic import BaseModel


# ============ Request Models ============

class QueryRequest(BaseModel):
    """Request body for /query endpoint."""
    user_id: str
    university_id: str
    question: str
    conversation_history: list[dict] = []
    session_id: Optional[str] = None


class OutreachStartRequest(BaseModel):
    """Request body for /outreach/start endpoint."""
    user_id: str
    university_id: str
    question: str
    intent: dict


class OutreachProcessRequest(BaseModel):
    """Request body for /outreach/process endpoint."""
    outreach_request_id: str


class OutreachRequesterConsentRequest(BaseModel):
    """Requester decision on a candidate."""
    outreach_request_id: str
    candidate_user_id: str
    decision: str  # yes | no | show_other | ask_more


class OutreachReplyRequest(BaseModel):
    """Inbound reply from a target user."""
    outreach_request_id: str
    responder_user_id: str
    response_text: str


class ConnectRequest(BaseModel):
    """Request body for /connect endpoint."""
    requesting_user_id: str
    target_user_ids: list[str]
    connection_reason: str
    create_group_chat: bool = True


class StyleLearnRequest(BaseModel):
    """Request body for /style/learn endpoint."""
    user_id: str
    message: str


class CheckinSendRequest(BaseModel):
    """Request body for /checkins/send endpoint."""
    checkin_id: str


class CheckinRespondRequest(BaseModel):
    """Request body for /checkins/respond endpoint."""
    checkin_id: str
    user_response: str


class JournalEntryRequest(BaseModel):
    """Request body for /journal/entry endpoint."""
    user_id: str
    content: str
    type: str = "user_freeform"


class CheckinTriggerRequest(BaseModel):
    """Request body for /checkin/trigger endpoint."""
    university_id: str


class ReindexRequest(BaseModel):
    """Request body for /reindex endpoint (optional university filter)."""
    university_id: Optional[str] = None


# ============ Link Orchestrator (New) ============

class LinkAgentRequest(BaseModel):
    """Request body for /link/agent endpoint."""
    user_id: str
    university_id: str
    message_text: str
    session_id: Optional[str] = None
    access_token: Optional[str] = None


class LinkOutreachCollectRequest(BaseModel):
    """Request body for /link/outreach/collect endpoint."""
    run_id: str
    university_id: str
    session_id: Optional[str] = None
    access_token: Optional[str] = None


class LinkConsentResolveRequest(BaseModel):
    """Request body for /link/consent/resolve endpoint."""
    run_id: str
    requester_user_id: str
    target_user_id: str
    requester_ok: bool
    target_ok: bool


class LinkRelayStartRequest(BaseModel):
    requester_user_id: str
    requester_conversation_id: str
    target_user_id: str
    university_id: str
    question: str
    session_id: Optional[str] = None


class LinkRelayCollectRequest(BaseModel):
    run_id: str
    university_id: str
    session_id: Optional[str] = None


# ============ Response Models ============

class Intent(BaseModel):
    """Parsed intent from user query."""
    type: str  # find_people, find_info, find_event, find_org, general_question, checkin_response
    entities: list[str] = []
    filters: dict = {}


class ValidationInfo(BaseModel):
    """Confidence validation info."""
    system_confidence: float
    agreement_score: float
    sources_count: int
    verified_facts_used: int


class ResultItem(BaseModel):
    """A single result from RAG retrieval."""
    type: str  # profile, organization, event, link_fact
    id: str
    name: str
    match_reason: str
    confidence: float


class SourceItem(BaseModel):
    """Source citation for a result."""
    type: str
    id: str
    detail: str


class ResponseContent(BaseModel):
    """Link's response content."""
    message: str
    tone: str = "friendly"
    suggestions: list[str] = []


class QueryResponse(BaseModel):
    """Response from /query endpoint."""
    intent: Intent
    response: ResponseContent
    results: list[ResultItem] = []
    data: Optional[dict] = None
    session_id: Optional[str] = None
    need_outreach: bool = False
    outreach_request_id: Optional[str] = None
    validation: ValidationInfo
    sources: list[SourceItem] = []
    memory_updated: bool = False
    journal_entry_created: bool = False


class HealthResponse(BaseModel):
    """Response from /health endpoint."""
    status: str
    rag_indexed: bool
    facts_count: int
    missing_config: list[str] = []


class OutreachTarget(BaseModel):
    """Target user for outreach."""
    user_id: str
    name: str
    reason: str


class OutreachStartResponse(BaseModel):
    """Response from /outreach/start endpoint."""
    outreach_request_id: str
    status: str
    targets: list[OutreachTarget] = []
    message_template: str
    estimated_completion: str


class OutreachMatch(BaseModel):
    """Match found from outreach."""
    user_id: str
    name: str
    consent: bool = False
    confidence: float = 0.0
    evidence: list[str] = []


class OutreachProcessResponse(BaseModel):
    """Response from /outreach/process endpoint."""
    status: str
    responses_received: int
    positive_responses: int
    facts_created: int
    matches_found: list[OutreachMatch] = []
    updated_confidence: float
    profile_card: Optional[dict] = None
    next_actions: list[str] = []


class OutreachConsentResponse(BaseModel):
    """Response from requester consent action."""
    status: str
    action: str
    message: str = ""


class ConnectResponse(BaseModel):
    """Response from /connect endpoint."""
    connection_id: str
    conversation_id: str
    intro_message: str


class TaskState(BaseModel):
    """Active task state for Link UI."""
    id: Optional[str] = None
    type: Optional[str] = None
    status: Optional[str] = None
    run_id: Optional[str] = None


class UIHints(BaseModel):
    """UI rendering hints for frontend."""
    show_status_button: bool = False
    show_cancel_button: bool = False
    show_consent_buttons: bool = False


class LinkAgentResponse(BaseModel):
    """Response from /link/agent endpoint."""
    mode: str
    confidence: float
    run_id: Optional[str] = None
    answer_text: Optional[str] = None
    cards: Optional[dict] = None
    citations: list[dict] = []
    task: Optional[TaskState] = None
    ui: Optional[UIHints] = None


class LinkOutreachCollectResponse(BaseModel):
    """Response from /link/outreach/collect endpoint."""
    status: str
    confidence: Optional[float] = None
    message: Optional[str] = None


class LinkConsentResolveResponse(BaseModel):
    """Response from /link/consent/resolve endpoint."""
    status: str
    conversation_id: Optional[str] = None


class LinkRelayResponse(BaseModel):
    status: str
    run_id: Optional[str] = None


class StyleLearnResponse(BaseModel):
    """Response from /style/learn endpoint."""
    style_updated: bool
    current_archetype: str
    archetype_confidence: float
    messages_analyzed: int
    detected_features: dict


class StyleProfileResponse(BaseModel):
    """Response from /style/{user_id} endpoint."""
    archetype: str
    confidence: float
    detected_style: dict
    vocabulary_patterns: dict
    sample_messages: list[str]
    messages_analyzed: int
