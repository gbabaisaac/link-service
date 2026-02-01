from __future__ import annotations

from dataclasses import dataclass
import re
from enum import Enum
from typing import Optional


class Intent(str, Enum):
    GREETING = "greeting"
    SMALL_TALK = "small_talk"
    FOLLOWUP = "followup"
    DB_QUERY = "db_query"
    PEOPLE_SEARCH = "people_search"
    EVENT_SEARCH = "event_search"
    CLUB_SEARCH = "club_search"
    CAMPUS_INFO = "campus_info"
    PROFILE_QUESTION = "profile_question"
    PROFILE_CLASSES = "profile_classes"
    ACTIVITY_RECALL = "activity_recall"
    COUNT_QUERY = "count_query"
    FOOD = "food"
    HOUSING = "housing"
    TECH = "tech"
    SAFETY = "safety"
    TRANSPORT = "transport"
    HEALTH = "health"
    CAREER = "career"
    SPORTS = "sports"
    STUDY = "study"
    SOCIAL = "social"
    MARKETPLACE = "marketplace"
    CONSENT_RESPONSE = "consent_response"
    CANCEL_TASK = "cancel_task"
    UNKNOWN = "unknown"


@dataclass
class IntentResult:
    intent: Intent
    entities: list[str]
    raw: str


_GREETING = {"yo", "hey", "hi", "sup", "what's up", "whats up", "wyd"}
_CANCEL = {"cancel", "stop", "end", "drop", "never mind", "nevermind"}
_YES = {"yes", "yep", "yeah", "yup", "sure", "ok", "okay"}
_NO = {"no", "nope", "nah"}


def _normalize(text: str) -> str:
    return (text or "").strip().lower()


def _extract_entities(text: str) -> list[str]:
    words = re.findall(r"[a-zA-Z0-9']+", text or "")
    return [w for w in words if len(w) > 2][:8]


def classify_intent(message_text: str, active_task: Optional[dict] = None) -> IntentResult:
    raw = message_text or ""
    text = _normalize(raw)
    entities = _extract_entities(raw)

    if not text:
        return IntentResult(Intent.UNKNOWN, entities, raw)

    if any(text.startswith(x) for x in _CANCEL) or "end that task" in text or "stop asking" in text:
        return IntentResult(Intent.CANCEL_TASK, entities, raw)

    if text in _YES or text in _NO:
        if active_task:
            status = (active_task.get("status") or "").lower()
            if status in {
                "awaiting_consent",
                "awaiting_requester_consent",
                "awaiting_target_consent",
            }:
                return IntentResult(Intent.CONSENT_RESPONSE, entities, raw)
        return IntentResult(Intent.FOLLOWUP, entities, raw)

    if text in _GREETING or len(text) <= 3:
        return IntentResult(Intent.GREETING, entities, raw)

    if any(x in text for x in ["how are you", "how's your day", "what's good", "wyd", "hru"]):
        return IntentResult(Intent.SMALL_TALK, entities, raw)

    if any(x in text for x in ["who am i", "what do you know about me", "do you know me", "tell me about myself"]):
        return IntentResult(Intent.PROFILE_QUESTION, entities, raw)
    if any(
        x in text
        for x in [
            "what did i do today",
            "what did i do yesterday",
            "what did i do earlier",
            "what did i do this morning",
            "what did i do tonight",
            "remind me what i did",
            "what did i do",
        ]
    ):
        return IntentResult(Intent.ACTIVITY_RECALL, entities, raw)
    if any(x in text for x in ["what classes am i taking", "my classes", "my schedule", "this semester", "current classes"]):
        return IntentResult(Intent.PROFILE_CLASSES, entities, raw)

    if any(x in text for x in ["how many", "count", "number of"]):
        return IntentResult(Intent.COUNT_QUERY, entities, raw)

    if any(x in text for x in ["club", "clubs", "org", "organization", "organizations", "compsci", "computer science", "cs "]):
        return IntentResult(Intent.CLUB_SEARCH, entities, raw)

    if any(x in text for x in ["event", "events", "party", "show", "concert", "talk"]):
        return IntentResult(Intent.EVENT_SEARCH, entities, raw)

    if any(x in text for x in ["find", "anyone", "someone", "people", "person", "connect me", "looking for"]):
        return IntentResult(Intent.PEOPLE_SEARCH, entities, raw)

    if any(x in text for x in ["campus", "library", "gym", "dining", "hours", "where is", "where's"]):
        return IntentResult(Intent.CAMPUS_INFO, entities, raw)
    if any(x in text for x in ["food", "dining", "lunch", "dinner", "menu"]):
        return IntentResult(Intent.FOOD, entities, raw)
    if any(x in text for x in ["dorm", "housing", "room", "ra", "maintenance"]):
        return IntentResult(Intent.HOUSING, entities, raw)
    if any(x in text for x in ["wifi", "password", "print", "printer", "login", "it"]):
        return IntentResult(Intent.TECH, entities, raw)
    if any(x in text for x in ["safe", "police", "escort", "emergency"]):
        return IntentResult(Intent.SAFETY, entities, raw)
    if any(x in text for x in ["shuttle", "bus", "ride", "carpool", "parking"]):
        return IntentResult(Intent.TRANSPORT, entities, raw)
    if any(x in text for x in ["health", "counseling", "clinic", "therapy"]):
        return IntentResult(Intent.HEALTH, entities, raw)
    if any(x in text for x in ["job", "internship", "career", "resume", "career fair"]):
        return IntentResult(Intent.CAREER, entities, raw)
    if any(x in text for x in ["sports", "game", "pickup", "intramural", "gym"]):
        return IntentResult(Intent.SPORTS, entities, raw)
    if any(x in text for x in ["study", "tutor", "notes", "exam", "midterm"]):
        return IntentResult(Intent.STUDY, entities, raw)
    if any(x in text for x in ["party", "concert", "hang", "weekend", "fun"]):
        return IntentResult(Intent.SOCIAL, entities, raw)
    if any(x in text for x in ["buy", "sell", "market", "textbook", "bike", "sublet"]):
        return IntentResult(Intent.MARKETPLACE, entities, raw)

    # If user is responding while an active task exists, treat as followup.
    if active_task:
        return IntentResult(Intent.FOLLOWUP, entities, raw)

    return IntentResult(Intent.UNKNOWN, entities, raw)
