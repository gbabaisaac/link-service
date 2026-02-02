from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from intent_classifier import Intent, IntentResult

@dataclass
class Transition:
    mode: str
    active_task: Dict[str, Any] = field(default_factory=dict)
    reason: str = "default"

def determine_transition(
    current_mode: str,
    active_task: Dict[str, Any],
    intent_result: IntentResult
) -> Transition:
    """
    Determine the next state of the conversation based on the user's intent.
    This is the core logic of the 'Runner'.
    """
    intent = intent_result.intent
    
    # 1. Global Exits (Cancel, Stop)
    if intent == Intent.CANCEL_TASK:
        return Transition(mode="idle", reason="user_cancelled")

    # 2. State: AWAITING_CONSENT
    if current_mode == "awaiting_consent":
        if intent == Intent.CONSENT_RESPONSE:
            # We stay in awaiting_consent until the logic handles the specific yes/no action
            # The LinkInstance will process the action and THEN set us back to idle or agent
            return Transition(mode="awaiting_consent", active_task=active_task, reason="processing_consent")
        # If unrelated message, maybe we assume implicit decline or just simple chat?
        # For now, strict state machine: any other text is treated as chat but we stay in consent mode?
        # Better: Fallback to chat but warn user?
        return Transition(mode="awaiting_consent", active_task=active_task, reason="awaiting_clarification")

    # 3. State: AGENT / OUTREACH (Active Task)
    if current_mode in {"agent", "outreach"}:
        if intent == Intent.FOLLOWUP or intent in {Intent.YES, Intent.NO}: # Assuming YES/NO handles followups
             return Transition(mode=current_mode, active_task=active_task, reason="task_followup")
        
        # If user switches topic substantially, we might exit mode
        if intent in {Intent.GREETING, Intent.SMALL_TALK}:
             # Soft exit? Or just chat while task runs?
             # For "Runner" model, tasks are ephemeral. If we are waiting for async, we are "idle" with a background job.
             # If we are in synchronous agent loop, small talk interrupts it.
             return Transition(mode="conversation", reason="interruption")

    # 4. State: IDLE / CONVERSATION
    # Default entry point
    
    # Priority A: Direct DB Queries (Runner Logic)
    if intent in {
        Intent.DB_QUERY, 
        Intent.EVENT_SEARCH, 
        Intent.CLUB_SEARCH, 
        Intent.CAMPUS_INFO,
        Intent.COUNT_QUERY,
        Intent.FOOD,
        Intent.HOUSING,
        Intent.TECH,
        Intent.SAFETY
    }:
        return Transition(
            mode="agent", 
            active_task={"type": "db_query", "intent": intent.value, "entities": intent_result.entities}, 
            reason="db_intent"
        )

    # Priority B: Distributed Queries (Outreach)
    if intent in {Intent.PEOPLE_SEARCH}:
        # Check if entities suggest a specific person or general search?
        # For Phase 1, treating all people search as outreach candidate
        return Transition(
            mode="outreach",
            active_task={"type": "people_search", "intent": intent.value},
            reason="people_intent"
        )
        
    # Priority C: Private Memory
    if intent in {Intent.PROFILE_QUESTION, Intent.PROFILE_CLASSES, Intent.ACTIVITY_RECALL}:
         return Transition(
            mode="agent",
            active_task={"type": "memory", "intent": intent.value},
            reason="memory_intent"
        )
         
    # Priority D: Chat
    return Transition(mode="conversation", reason="chat_default")
