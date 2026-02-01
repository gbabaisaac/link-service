from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from intent_classifier import Intent, IntentResult


@dataclass
class Transition:
    mode: str
    active_task: Optional[dict]
    note: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_task(task_type: str, query: str) -> dict:
    return {
        "id": str(uuid4()),
        "type": task_type,
        "query": query,
        "status": "pending",
        "started_at": _now_iso(),
        "outreach_targets": [],
        "responses": [],
        "result": None,
    }


def determine_transition(
    current_mode: str,
    intent: IntentResult,
    message_text: str,
    active_task: Optional[dict] = None,
    db_answerable: bool = False,
) -> Transition:
    text = (message_text or "").strip()

    if intent.intent == Intent.CANCEL_TASK:
        if active_task:
            active_task = dict(active_task)
            active_task["status"] = "failed"
            active_task["result"] = {"reason": "cancelled"}
        return Transition(mode="conversation", active_task=None, note="cancel_task")

    if intent.intent in {Intent.GREETING, Intent.SMALL_TALK}:
        return Transition(mode="conversation", active_task=active_task, note="smalltalk")

    if intent.intent == Intent.CONSENT_RESPONSE:
        return Transition(mode="awaiting_consent", active_task=active_task, note="consent_response")

    if intent.intent == Intent.FOLLOWUP:
        return Transition(mode=current_mode or "conversation", active_task=active_task, note="followup")

    if intent.intent in {Intent.DB_QUERY, Intent.EVENT_SEARCH, Intent.CLUB_SEARCH, Intent.CAMPUS_INFO}:
        task = active_task or new_task("db_query", text)
        task["status"] = "searching"
        return Transition(mode="agent", active_task=task, note="db_query")

    if intent.intent == Intent.PEOPLE_SEARCH:
        task = active_task or new_task("people_search", text)
        if db_answerable:
            task["status"] = "searching"
            return Transition(mode="agent", active_task=task, note="people_db")
        task["status"] = "outreach_sent"
        return Transition(mode="outreach", active_task=task, note="people_outreach")

    return Transition(mode="conversation", active_task=active_task, note="fallback")
