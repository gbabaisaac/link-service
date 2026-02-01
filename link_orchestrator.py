"""Link Orchestrator - intent routing, grounded answers, outreach flows."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from typing import Optional

from config import settings
from link_logic import llm_json, normalize_entities, build_card_metadata
import outreach_logic
import supabase_client as db

INTENT_TYPES = {
    "event_search",
    "person_search",
    "club_search",
    "campus_info",
    "casual_chat",
}

TIME_WINDOWS = {"today", "this_week", None}

DB_SCHEMA_HINT = (
    "DB schema: events(title,start_at,location_name,description,type,visibility), "
    "organizations(name,category,mission_statement,meeting_time,meeting_place,is_public), "
    "profiles(full_name,username,major,bio,interests,yearbook_visible), "
    "forums/posts(title,body,forum_id,is_public)."
)

SLANG_TERMS = {
    "fr", "frfr", "ngl", "tbh", "lowkey", "highkey", "rn", "idk", "idc", "imo",
    "lmk", "brb", "btw", "omg", "lol", "lmao", "lmfao", "wtf", "vibe", "vibes",
    "bet", "cap", "nocap", "deadass", "slay", "ate", "goated", "rizz", "sus",
}

EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001F5FF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "\U0001F700-\U0001F77F"
    "\U0001F780-\U0001F7FF"
    "\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FA6F"
    "\U0001FA70-\U0001FAFF"
    "\u2600-\u26FF"
    "\u2700-\u27BF"
    "]+",
    flags=re.UNICODE,
)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value.replace("Z", "+00:00")
        return datetime.fromisoformat(value)
    except Exception:
        return None


def _avg(prev: float, new: float, count: int) -> float:
    return (prev * count + new) / max(count + 1, 1)


def analyze_message_style(text: str) -> dict:
    """Extract lightweight style features from a message."""
    raw = text or ""
    lowered = raw.lower()
    words = re.findall(r"[a-zA-Z0-9']+", raw)
    sentences = [s for s in re.split(r"[.!?]+", raw) if s.strip()]
    alpha_chars = [c for c in raw if c.isalpha()]
    upper_chars = [c for c in alpha_chars if c.isupper()]
    lower_chars = [c for c in alpha_chars if c.islower()]

    emoji_count = len(EMOJI_RE.findall(raw))
    slang_terms = sorted({term for term in SLANG_TERMS if term in lowered})

    avg_words = len(words) / max(len(sentences), 1)
    avg_word_len = sum(len(w) for w in words) / max(len(words), 1)
    punctuation_count = len(re.findall(r"[.!?]", raw))
    exclamation_count = raw.count("!")
    question_count = raw.count("?")
    lower_ratio = len(lower_chars) / max(len(alpha_chars), 1)
    upper_ratio = len(upper_chars) / max(len(alpha_chars), 1)
    emoji_rate = emoji_count / max(len(words), 1)
    has_elongation = bool(re.search(r"(\\w)\\1{2,}", lowered))

    return {
        "avg_words_per_sentence": round(avg_words, 2),
        "avg_word_length": round(avg_word_len, 2),
        "emoji_count": emoji_count,
        "emoji_rate": round(emoji_rate, 3),
        "punctuation_count": punctuation_count,
        "exclamation_count": exclamation_count,
        "question_count": question_count,
        "lowercase_ratio": round(lower_ratio, 3),
        "uppercase_ratio": round(upper_ratio, 3),
        "slang_terms": slang_terms,
        "has_elongation": has_elongation,
        "raw_length": len(raw),
        "word_count": len(words),
    }


def update_user_style_memory(user_id: str, university_id: str, message_text: str) -> dict:
    """Update user memory with style profile + Gen Z baseline."""
    existing = db.get_user_memory(user_id) or {}
    if not university_id:
        university_id = existing.get("university_id") or (db.get_profile(user_id, enforce_public=False) or {}).get("university_id")
    if not university_id:
        return existing or {}
    detected = existing.get("detected_style") or {}
    vocab = existing.get("vocabulary_patterns") or {}
    examples = existing.get("style_examples") or []
    conversation_state = existing.get("conversation_state") or {}

    features = analyze_message_style(message_text)
    count = int(existing.get("messages_analyzed") or 0)

    merged = {
        "avg_words_per_sentence": round(_avg(float(detected.get("avg_words_per_sentence", 0)), features["avg_words_per_sentence"], count), 2),
        "avg_word_length": round(_avg(float(detected.get("avg_word_length", 0)), features["avg_word_length"], count), 2),
        "emoji_rate": round(_avg(float(detected.get("emoji_rate", 0)), features["emoji_rate"], count), 3),
        "punctuation_rate": round(_avg(float(detected.get("punctuation_rate", 0)), features["punctuation_count"], count), 2),
        "exclamation_rate": round(_avg(float(detected.get("exclamation_rate", 0)), features["exclamation_count"], count), 2),
        "question_rate": round(_avg(float(detected.get("question_rate", 0)), features["question_count"], count), 2),
        "lowercase_ratio": round(_avg(float(detected.get("lowercase_ratio", 0)), features["lowercase_ratio"], count), 3),
        "uppercase_ratio": round(_avg(float(detected.get("uppercase_ratio", 0)), features["uppercase_ratio"], count), 3),
        "has_elongation": detected.get("has_elongation", False) or features["has_elongation"],
    }

    slang = set(vocab.get("common_slang") or [])
    slang.update(features["slang_terms"])

    examples = (examples + [message_text])[-5:]

    style_confidence = min(1.0, (count + 1) / 10.0)

    conversation_state = update_conversation_state(conversation_state, message_text)

    payload = {
        "university_id": university_id,
        "last_interaction_at": "now()",
        "messages_analyzed": count + 1,
        "communication_archetype": "genz_casual",
        "style_confidence": style_confidence,
        "detected_style": merged,
        "vocabulary_patterns": {"common_slang": sorted(slang)},
        "style_examples": examples,
        "conversation_state": conversation_state,
    }
    known_preferences = existing.get("known_preferences") or {}
    lower_text = (message_text or "").lower()
    like_seed = None
    if any(x in lower_text for x in ["i like ", "i love ", "i'm into "]):
        like_seed = lower_text.split("i like ", 1)[-1]
        like_seed = like_seed.split("i love ", 1)[-1]
        like_seed = like_seed.split("i'm into ", 1)[-1]
    elif "remember i said" in lower_text:
        like_seed = lower_text.split("remember i said", 1)[-1]
    if like_seed:
        like_seed = like_seed.strip().strip(".")
        likes = known_preferences.get("likes") or []
        for part in re.split(r",| and |/|&", like_seed):
            value = part.strip()
            if value and value not in likes:
                likes.append(value)
        if likes:
            known_preferences["likes"] = likes[-5:]
    preferred_name = conversation_state.get("preferred_name")
    if preferred_name:
        known_preferences["preferred_name"] = preferred_name
    if known_preferences is not None:
        payload["known_preferences"] = known_preferences

    return db.upsert_user_memory(user_id, payload)


def build_style_instructions(user_memory: Optional[dict]) -> str:
    """Build style guidance for responses (Gen Z baseline + user mirroring)."""
    baseline = (
        "Write like a Gen Z college student. Be casual, concise, friendly. "
        "Use contractions and avoid formal phrasing."
    )
    if not user_memory:
        return baseline + " Keep it short with light punctuation and 0-2 emojis."

    detected = user_memory.get("detected_style") or {}
    vocab = user_memory.get("vocabulary_patterns") or {}
    slang = vocab.get("common_slang") or []
    avg_words = detected.get("avg_words_per_sentence")
    emoji_rate = detected.get("emoji_rate")
    lower_ratio = detected.get("lowercase_ratio", 0)
    casing = "mostly lowercase" if lower_ratio >= 0.7 else "mixed case"
    slang_hint = f"Use some of these terms if natural: {', '.join(slang[:6])}." if slang else ""
    length_hint = f"Aim for about {int(avg_words)} words per sentence." if avg_words else "Keep sentences short."
    emoji_hint = (
        f"Emoji rate ~{emoji_rate} per word; use 0-2 emojis max."
        if emoji_rate is not None
        else "Use 0-2 emojis max."
    )
    return " ".join([baseline, f"Mirror the user's style: {casing}.", length_hint, emoji_hint, slang_hint]).strip()


def update_conversation_state(state: dict, message_text: str) -> dict:
    """Track lightweight conversation context (classes, exams, mood, goals)."""
    text = (message_text or "").lower()
    state = state or {}
    topics = set(state.get("topics", []) or [])
    goals = set(state.get("goals", []) or [])
    classes = set(state.get("classes", []) or [])
    memories = state.get("memories", []) or []

    for course in _extract_course_tags(message_text):
        classes.add(course)
        topics.add("classes")

    if any(x in text for x in ["exam", "midterm", "final", "quiz"]):
        topics.add("exams")
    if any(x in text for x in ["class", "lecture", "prof", "homework", "hw"]):
        topics.add("classes")
    if any(x in text for x in ["friends", "friend group", "group chat", "hang", "party"]):
        topics.add("friends")
    if any(x in text for x in ["stressed", "tired", "burnt", "burned", "anxious"]):
        state["mood"] = "stressed"
    if any(x in text for x in ["excited", "hyped", "pumped"]):
        state["mood"] = "excited"

    if any(x in text for x in ["looking for", "need", "help with", "trying to"]):
        goals.add(text[:80])

    # Extract lightweight facts from recent user messages.
    fact_patterns = [
        (r"i went to ([^\\.\\!\\?]+)", "went_to"),
        (r"i attended ([^\\.\\!\\?]+)", "attended"),
        (r"i was at ([^\\.\\!\\?]+)", "was_at"),
        (r"i created ([^\\.\\!\\?]+)", "created"),
        (r"i built ([^\\.\\!\\?]+)", "built"),
        (r"i made ([^\\.\\!\\?]+)", "made"),
        (r"i love ([^\\.\\!\\?]+)", "love"),
        (r"i like ([^\\.\\!\\?]+)", "like"),
        (r"i hate ([^\\.\\!\\?]+)", "hate"),
    ]
    for pattern, label in fact_patterns:
        match = re.search(pattern, text)
        if match:
            value = match.group(1).strip()
            if value:
                memories.append(f"{label}:{value}")

    if "my name is " in text:
        name = text.split("my name is ", 1)[-1].split(".")[0].strip()
        if name:
            memories.append(f"name:{name}")
            state["preferred_name"] = name
    preferred_match = re.search(r"(call me|i go by|you can call me|call me)\s+([a-zA-Z0-9_'-]{1,16})", text)
    if preferred_match:
        preferred = preferred_match.group(2).strip()
        if preferred:
            state["preferred_name"] = preferred
            memories.append(f"preferred_name:{preferred}")
    if "i like " in text or "i love " in text or "i'm into " in text:
        memories.append(f"likes:{text[:80]}")
    if "i went to" in text or "i went" in text:
        memories.append(f"event:{text[:80]}")
    if "remember i said" in text or "remember that i" in text:
        memories.append(f"remember:{text[:80]}")

    state["topics"] = sorted(topics)
    state["goals"] = list(goals)[-5:]
    state["classes"] = sorted(classes)
    state["memories"] = memories[-10:]
    state["last_message_at"] = _now_utc().isoformat()
    return state


def recall_recent_activity(question: str, recent_user_messages: list[str], memories: list[str]) -> Optional[str]:
    """Return a grounded recall of what the user said they did recently."""
    q = (question or "").lower()
    time_hint = "today"
    if "yesterday" in q:
        time_hint = "yesterday"
    elif any(x in q for x in ["this morning", "earlier", "tonight"]):
        time_hint = "earlier"
    patterns = [
        r"\bi (went to|went|attended|was at|created|built|made|had|did|joined)\b[^\\.\\!\\?]*",
        r"\bi (just|recently|earlier)\b[^\\.\\!\\?]*",
    ]
    for msg in reversed(recent_user_messages or []):
        text = (msg or "").strip()
        if not text:
            continue
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                snippet = text.strip()
                snippet = re.sub(r"\\blink\\b", "", snippet, flags=re.IGNORECASE).strip()
                if "hackathon" in snippet and any(x in snippet for x in ["built", "created", "made"]):
                    return f"{time_hint} you said you built me at a hackathon."
                return f"{time_hint} you said: \"{snippet}\""
    # Fall back to memory snippets extracted during style updates.
    for mem in reversed(memories or []):
        if any(mem.startswith(prefix) for prefix in ("went_to:", "attended:", "was_at:", "created:", "built:", "made:", "event:")):
            value = mem.split(":", 1)[-1].strip()
            if value:
                if "hackathon" in value and any(x in mem for x in ["created", "built", "made"]):
                    return f"{time_hint} you said you built me at a hackathon."
                return f"{time_hint} you mentioned: {value}"
    return None


def determine_mode(message_text: str, intent: dict) -> str:
    """Pick conversation vs agent mode based on intent and message content."""
    text = (message_text or "").lower()
    if intent.get("intent") in {"event_search", "person_search", "club_search", "campus_info"}:
        return "agent"
    if any(x in text for x in ["find", "anyone", "who", "where", "when", "help me", "recommend"]):
        return "agent"
    return "conversation"


def generate_friend_checkin(user_memory: Optional[dict]) -> str:
    """Return a short friend-like check-in based on memory."""
    state = (user_memory or {}).get("conversation_state") or {}
    topics = state.get("topics", []) or []
    classes = state.get("classes", []) or []
    mood = state.get("mood")

    if mood == "stressed":
        return "how you holding up? you good?"
    if "exams" in topics:
        return "how'd that exam go?"
    if classes:
        return f"how's {classes[-1]} going?"
    if "friends" in topics:
        return "how's your friend group lately?"
    return "how's your day been?"


def _parse_iso(ts: str) -> Optional[datetime]:
    if not ts:
        return None
    try:
        if ts.endswith("Z"):
            ts = ts.replace("Z", "+00:00")
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def should_ask_class_checkin(user_memory: Optional[dict]) -> Optional[str]:
    """Return a class name to check in about if it's time."""
    memory = user_memory or {}
    state = memory.get("conversation_state") or {}
    classes = state.get("classes") or []
    if not classes:
        return None
    last_check = _parse_iso(memory.get("last_class_checkin") or "")
    now = _now_utc()
    if last_check and (now - last_check).total_seconds() < 60 * 60 * 18:
        return None
    return classes[-1]


def build_vibe_instructions(recent_user_messages: list[str]) -> str:
    """Create short vibe-matching instructions from recent user messages."""
    if not recent_user_messages:
        return ""
    joined = " ".join(recent_user_messages).lower()
    vibe = []
    if any(x in joined for x in ["girly", "girl", "omg", "bestie"]):
        vibe.append("Use softer, feminine-coded language. You can say girly or girl.")
    if any(x in joined for x in ["lol", "lmao", "lmfao", "haha"]):
        vibe.append("Keep it playful and light.")
    if any(x in joined for x in ["hbu", "wyd", "wya", "wassup", "sup"]):
        vibe.append("Be super casual and short.")
    if any(c in joined for c in [":)", "😂", "🥹", "😭", "💀", "✨", "💅"]):
        vibe.append("Match emoji usage lightly (0-2).")
    return " ".join(vibe)


def generate_small_talk_response(
    message_text: str,
    user_memory: Optional[dict],
    recent_user_messages: Optional[list[str]] = None,
    conversation_history: str = "",
) -> str:
    """Generate a casual, friend-like response without making factual claims."""
    text = (message_text or "").strip().lower()
    prefs = (user_memory or {}).get("known_preferences") or {}
    likes = prefs.get("likes") or []
    like_hint = f"btw you still into {likes[0]}?" if likes else ""

    if settings.TEST_MODE:
        if any(x in text for x in ["who am i", "do you know me"]):
            return "you tell me 😅 give me the tea"
        if any(x in text for x in ["yo", "hey", "hi", "sup", "what's up", "whats up"]):
            return "yo! what's good? " + like_hint
        if "?" in text:
            return "gotchu. tell me a lil more and i'll help"
        return "say less, what's the vibe?"

    style_instructions = build_style_instructions(user_memory)
    vibe_instructions = build_vibe_instructions(recent_user_messages or [])
    prompt = f"""Write a friendly, creative small-talk reply. Do NOT claim facts or info you don't have. Keep it short and warm.

User message: "{message_text}"
Style: {style_instructions}
Vibe: {vibe_instructions}
Conversation so far (last messages):
{conversation_history}
Optional follow-up: {like_hint}

Return JSON:
{{"message": "..."}}"""
    result = llm_json(prompt, temperature=0.7)
    msg = (result.get("message") or "").strip()
    if not msg:
        return "yo! what's the vibe?"
    return msg


def classify_smalltalk(message_text: str) -> str:
    """Classify smalltalk intent into general/capabilities/checkin."""
    if settings.TEST_MODE:
        text = (message_text or "").lower()
        if any(x in text for x in ["what can you do", "what are you able to do", "what do you do", "what are you"]):
            return "capabilities"
        return "general"
    prompt = f"""Classify the user's message as one of:
- capabilities (asking what Link can do)
- checkin (asking about Link or user's day)
- general (small talk)

Message: "{message_text}"

Return JSON:
{{"type":"capabilities|checkin|general"}}
"""
    result = llm_json(prompt, temperature=0)
    return (result.get("type") or "general").strip()


def generate_capabilities_response(message_text: str, user_memory: Optional[dict], conversation_history: str = "") -> str:
    """Generate a friendly capabilities response without hardcoding."""
    if settings.TEST_MODE:
        return "i'm your campus friend - i can find people, clubs, and events, answer campus qs, and ask around if i'm not sure."
    style_instructions = build_style_instructions(user_memory)
    prompt = f"""You're Link, a campus friend. Reply to the user explaining what you can do.
Keep it short, casual, and confident. Mention: find people/clubs/events, answer campus questions from real data, ask around, and connect people with consent.

User message: "{message_text}"
Style: {style_instructions}
Conversation so far (last messages):
{conversation_history}

Return JSON:
{{"message":"..."}}
"""
    result = llm_json(prompt, temperature=0.4)
    msg = (result.get("message") or "").strip()
    return msg or "i can help you find people, clubs, and events, answer campus questions, and connect folks if you want."


def dedupe_response(conversation_id: str, text: str, intent_type: str = "general") -> str:
    """Avoid repeating identical Link messages back-to-back."""
    try:
        recent = db.list_recent_link_messages(conversation_id, sender_type="link", limit=3)
        recent_texts = [r.get("content") or "" for r in recent]
    except Exception:
        recent_texts = []
    def _jaccard(a: str, b: str) -> float:
        wa = set(re.findall(r"[a-zA-Z0-9']+", (a or "").lower()))
        wb = set(re.findall(r"[a-zA-Z0-9']+", (b or "").lower()))
        if not wa or not wb:
            return 0.0
        return len(wa & wb) / max(len(wa | wb), 1)

    # Block repeated capability pitch in same conversation.
    if text and "i can help you find people, clubs, and events" in text.lower():
        if any("i can help you find people, clubs, and events" in (t or "").lower() for t in recent_texts):
            return "gotchu. what's up?"
    is_dup = text and text in recent_texts
    if not is_dup and text:
        for recent_text in recent_texts:
            if _jaccard(text, recent_text) >= 0.85:
                is_dup = True
                break
    if is_dup:
        alternatives = {
            "outreach_started": [
                "asking around, give me a sec",
                "on it. i'll let you know",
                "reaching out now",
            ],
            "general": [
                "gotchu. what's up?",
                "say less. what's the move?",
                "cool. tell me more",
            ],
        }
        choices = alternatives.get(intent_type) or alternatives["general"]
        for alt in choices:
            if alt not in recent_texts:
                return alt
    return text


def _matches_tags(text: str, tags: list[str]) -> bool:
    if not tags:
        return True
    haystack = (text or "").lower()
    return any(tag in haystack for tag in tags)


def route_intent(message_text: str, user_context: Optional[dict] = None) -> dict:
    """Prompt A - Intent Router."""
    heuristic = _heuristic_intent(message_text)
    if heuristic:
        return heuristic
    context = ""
    if user_context:
        context = f"User context: {user_context}"

    prompt = f"""Analyze this user message and return structured intent.

User message: "{message_text}"
{context}
{DB_SCHEMA_HINT}

Output JSON with:
- intent: event_search | person_search | club_search | campus_info | casual_chat
- tags: string[]
- time_window: today | this_week | null
- needs_outreach: boolean
"""

    result = llm_json(prompt, temperature=0)

    intent = (result.get("intent") or "").strip()
    if intent not in INTENT_TYPES:
        intent = _fallback_intent(message_text)

    tags = result.get("tags") or []
    tags = [t.strip().lower() for t in tags if isinstance(t, str) and t.strip()]
    tags = normalize_entities(tags)

    time_window = result.get("time_window")
    if time_window not in {"today", "this_week"}:
        time_window = None

    needs_outreach = bool(result.get("needs_outreach", False))

    return {
        "intent": intent,
        "tags": tags,
        "time_window": time_window,
        "needs_outreach": needs_outreach,
    }


def route_capability(question: str, intent: dict) -> dict:
    """Decide whether the DB likely contains the answer or outreach is needed."""
    if settings.TEST_MODE:
        q = (question or "").lower()
        if any(x in q for x in ["how many", "what time", "where", "when", "events", "club", "organization"]):
            return {
                "can_answer_from_db": True,
                "sources": ["events", "orgs", "profiles"],
                "needs_outreach": False,
                "clarify_question": "",
            }
        return {
            "can_answer_from_db": False,
            "sources": [],
            "needs_outreach": True,
            "clarify_question": "",
        }

    prompt = f"""You are Link. Decide if this question can be answered from campus DB records.

Question: "{question}"
Intent: {intent}
User context: {intent.get("user_context")}
{DB_SCHEMA_HINT}

DB sources available: events, organizations (clubs), profiles (public yearbook), forums/posts.
If answerable from DB, list which sources to query.
If not answerable, set needs_outreach=true.
If unclear, provide a short clarifying question.

Return JSON:
{{
  "can_answer_from_db": true|false,
  "sources": ["events","orgs","profiles","forums"],
  "needs_outreach": true|false,
  "clarify_question": "..."
}}
"""
    result = llm_json(prompt, temperature=0)
    can_answer = bool(result.get("can_answer_from_db", False))
    sources = result.get("sources") or []
    sources = [s for s in sources if s in {"events", "orgs", "profiles", "forums"}]
    needs_outreach = bool(result.get("needs_outreach", False))
    clarify = (result.get("clarify_question") or "").strip()
    return {
        "can_answer_from_db": can_answer,
        "sources": sources,
        "needs_outreach": needs_outreach,
        "clarify_question": clarify,
    }


def _fallback_intent(message_text: str) -> str:
    text = (message_text or "").lower()
    if any(x in text for x in ["club", "organization", "org"]):
        return "club_search"
    if any(x in text for x in ["event", "happening", "tonight", "this week", "today"]):
        return "event_search"
    if any(x in text for x in ["who", "anyone", "person", "people", "connect me"]):
        return "person_search"
    if any(x in text for x in ["where", "when", "what time", "info"]):
        return "campus_info"
    return "casual_chat"


def _extract_course_tags(text: str) -> list[str]:
    matches = re.findall(r"[A-Za-z]{2,4}\\s?\\d{2,4}", text or "")
    return [m.replace(" ", "").lower() for m in matches]


def _heuristic_intent(message_text: str) -> Optional[dict]:
    text = (message_text or "").lower()
    course_tags = _extract_course_tags(message_text)
    if course_tags:
        return {
            "intent": "person_search",
            "tags": course_tags,
            "time_window": None,
            "needs_outreach": True,
        }
    if any(x in text for x in ["anyone", "who", "tutor", "help me", "can help", "study with", "group"]):
        tags = []
        if "csc" in text or "cs" in text:
            tags.append("cs")
        tags.extend(course_tags)
        return {
            "intent": "person_search",
            "tags": [t for t in tags if t],
            "time_window": None,
            "needs_outreach": True,
        }
    return None


def _filter_events(events: list[dict], tags: list[str], time_window: Optional[str]) -> list[dict]:
    now = _now_utc()
    if time_window == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
    elif time_window == "this_week":
        start = now
        end = now + timedelta(days=7)
    else:
        start = None
        end = None

    filtered: list[dict] = []
    for event in events:
        start_at = _parse_dt(event.get("start_at"))
        if start and end and start_at:
            if not (start <= start_at <= end):
                continue
        text = " ".join([
            event.get("title") or "",
            event.get("description") or "",
            event.get("type") or "",
            event.get("location_name") or "",
        ])
        if _matches_tags(text, tags):
            filtered.append(event)
    return filtered


def _filter_profiles(profiles: list[dict], tags: list[str]) -> list[dict]:
    filtered: list[dict] = []
    for profile in profiles:
        interests = profile.get("interests") or []
        if isinstance(interests, str):
            interests = [interests]
        text = " ".join([
            profile.get("full_name") or "",
            profile.get("username") or "",
            profile.get("major") or "",
            profile.get("bio") or "",
            " ".join([str(i) for i in interests]),
        ])
        if _matches_tags(text, tags):
            filtered.append(profile)
    return filtered


def _filter_orgs(orgs: list[dict], tags: list[str]) -> list[dict]:
    filtered: list[dict] = []
    for org in orgs:
        text = " ".join([
            org.get("name") or "",
            org.get("category") or "",
            org.get("mission_statement") or "",
            org.get("meeting_place") or "",
        ])
        if _matches_tags(text, tags):
            filtered.append(org)
    return filtered


def retrieve_candidates(
    intent: str,
    tags: list[str],
    time_window: Optional[str],
    university_id: str,
    access_token: Optional[str] = None,
) -> dict:
    """Pull relevant records from the Bonded DB."""
    events: list[dict] = []
    profiles: list[dict] = []
    orgs: list[dict] = []
    facts: list[dict] = []

    facts = lookup_verified_facts(university_id, tags)

    if intent in {"event_search", "campus_info"}:
        if access_token:
            events = db.get_upcoming_events_rls(access_token, university_id, limit=100)
        else:
            events = db.get_upcoming_events(university_id, limit=100)
        events = _filter_events(events, tags, time_window)[:10]

    if intent in {"person_search"}:
        if access_token:
            profiles = db.get_profiles_rls(access_token, university_id, limit=200)
        else:
            profiles = db.get_profiles(university_id, limit=200)
        profiles = _filter_profiles(profiles, tags)[:10]

    if intent in {"club_search", "campus_info"}:
        if access_token:
            orgs = db.get_organizations_rls(access_token, university_id, limit=200)
        else:
            orgs = db.get_organizations(university_id, limit=200)
        orgs = _filter_orgs(orgs, tags)[:10]

    return {
        "events": events,
        "profiles": profiles,
        "orgs": orgs,
        "facts": facts,
    }


def _record_summaries(records: dict) -> list[dict]:
    summaries: list[dict] = []
    for fact in records.get("facts", []):
        summaries.append(
            {
                "type": "verified_fact",
                "id": fact.get("id"),
                "fact_category": fact.get("fact_category"),
                "fact_key": fact.get("fact_key"),
                "fact_value": fact.get("fact_value"),
                "confidence": fact.get("confidence"),
                "entity_id": fact.get("entity_id"),
                "entity_type": fact.get("entity_type"),
                "verified_at": fact.get("verified_at"),
            }
        )
    for event in records.get("events", []):
        summaries.append(
            {
                "type": "event",
                "id": event.get("id"),
                "title": event.get("title"),
                "start_at": event.get("start_at"),
                "location": event.get("location_name"),
                "description": event.get("description"),
            }
        )
    for profile in records.get("profiles", []):
        summaries.append(
            {
                "type": "user",
                "id": profile.get("id"),
                "name": profile.get("full_name"),
                "major": profile.get("major"),
                "bio": profile.get("bio"),
                "interests": profile.get("interests"),
            }
        )
    for org in records.get("orgs", []):
        summaries.append(
            {
                "type": "club",
                "id": org.get("id"),
                "name": org.get("name"),
                "category": org.get("category"),
                "meeting_time": org.get("meeting_time"),
                "meeting_place": org.get("meeting_place"),
            }
        )
    return summaries


def lookup_verified_facts(university_id: str, tags: list[str], limit: int = 10) -> list[dict]:
    """Fetch unexpired verified facts for reuse."""
    now = _now_utc()
    try:
        db.delete_expired_verified_facts(now.isoformat())
    except Exception:
        pass
    facts = db.get_verified_facts(university_id, tags, limit=limit)
    filtered: list[dict] = []
    for fact in facts:
        expires_at = _parse_dt(fact.get("expires_at"))
        if expires_at and expires_at < now:
            continue
        filtered.append(fact)
    return filtered


def compose_cached_answer(question: str, facts: list[dict], style_instructions: str = "") -> dict:
    """Compose answer from verified facts cache only."""
    prompt = f"""You are Link. You MUST ONLY use the provided verified facts. If insufficient, say needs_outreach.

User question: "{question}"
Style: {style_instructions}

Verified facts:
{facts}

Return JSON:
{{
  "answer_mode": "direct" | "needs_outreach" | "ask_clarifying",
  "confidence": number,
  "answer_text": string,
  "citations": [{{"type":"verified_fact", "id":"..."}}]
}}
"""
    result = llm_json(prompt, temperature=0)
    answer_mode = result.get("answer_mode") or "needs_outreach"
    if answer_mode not in {"direct", "needs_outreach", "ask_clarifying"}:
        answer_mode = "needs_outreach"
    confidence = float(result.get("confidence") or 0.0)
    answer_text = result.get("answer_text") or ""
    citations = result.get("citations") or []
    return {
        "answer_mode": answer_mode,
        "confidence": max(0.0, min(1.0, confidence)),
        "answer_text": answer_text,
        "citations": citations,
    }


def validate_cached_citations(citations: list[dict], facts: list[dict]) -> bool:
    fact_ids = {f.get("id") for f in facts if f.get("id")}
    for c in citations or []:
        if c.get("type") != "verified_fact":
            return False
        if c.get("id") not in fact_ids:
            return False
    return True


def validate_record_citations(citations: list[dict], records: dict) -> bool:
    valid_event_ids = {e.get("id") for e in records.get("events", []) if e.get("id")}
    valid_user_ids = {p.get("id") for p in records.get("profiles", []) if p.get("id")}
    valid_club_ids = {o.get("id") for o in records.get("orgs", []) if o.get("id")}
    for c in citations or []:
        c_type = c.get("type")
        c_id = c.get("id")
        if c_type == "event" and c_id in valid_event_ids:
            continue
        if c_type == "user" and c_id in valid_user_ids:
            continue
        if c_type == "club" and c_id in valid_club_ids:
            continue
        return False
    return True


def _expires_in_days(days: int) -> str:
    return (_now_utc() + timedelta(days=days)).isoformat()


def select_forum_for_post(access_token: str, university_id: str) -> Optional[dict]:
    """Pick a campus/public forum the user can post to."""
    forums = db.list_forums_rls(access_token, university_id=university_id, limit=50)
    for forum in forums:
        if forum.get("is_public") and forum.get("type") in {"campus", "public"}:
            return forum
    return forums[0] if forums else None


def create_forum_post(
    access_token: str,
    university_id: str,
    user_id: str,
    question: str,
    tags: list[str],
) -> Optional[dict]:
    """Create an anonymous forum post for outreach fallback."""
    forum = select_forum_for_post(access_token, university_id)
    if not forum:
        return None
    title = "Looking for people to connect"
    if tags:
        title = f"Anyone into {tags[0]}?"
    body = (
        f"Hey! I'm looking for people who are into {', '.join(tags) if tags else 'this'}. "
        "If that's you, drop a comment!"
    )
    payload = {
        "forum_id": forum.get("id"),
        "user_id": user_id,
        "title": title,
        "body": body,
        "tags": tags or [],
        "is_anonymous": True,
    }
    post = db.create_post_rls(access_token, payload)
    return {"forum": forum, "post": post}


def write_verified_facts_from_records(
    university_id: str,
    records: dict,
    citations: list[dict],
    answer_text: str,
    confidence: float,
) -> None:
    """Cache verified facts based on DB-backed answers."""
    if confidence < settings.CONFIDENCE_THRESHOLD:
        return
    events_by_id = {e.get("id"): e for e in records.get("events", []) if e.get("id")}
    profiles_by_id = {p.get("id"): p for p in records.get("profiles", []) if p.get("id")}
    orgs_by_id = {o.get("id"): o for o in records.get("orgs", []) if o.get("id")}

    for citation in citations:
        c_type = citation.get("type")
        c_id = citation.get("id")
        if c_type == "event" and c_id in events_by_id:
            event = events_by_id[c_id]
            fact_value = f"{event.get('title')} at {event.get('location_name')} on {event.get('start_at')}"
            expires_at = None
            start_at = _parse_dt(event.get("start_at"))
            if start_at:
                expires_at = (start_at + timedelta(days=7)).isoformat()
            db.create_verified_fact(
                {
                    "university_id": university_id,
                    "entity_type": "event",
                    "entity_id": c_id,
                    "fact_category": "event",
                    "fact_key": "event_details",
                    "fact_value": fact_value,
                    "confidence": confidence,
                    "source_type": "db_record",
                    "source_id": c_id,
                    "consent_status": "opt_in",
                    "verified_at": _now_utc().isoformat(),
                    "expires_at": expires_at or _expires_in_days(30),
                }
            )
        if c_type == "user" and c_id in profiles_by_id:
            profile = profiles_by_id[c_id]
            interests = profile.get("interests") or []
            if isinstance(interests, str):
                interests = [interests]
            fact_value = f"{profile.get('full_name')} - {profile.get('major')} - interests: {', '.join(interests)}"
            db.create_verified_fact(
                {
                    "university_id": university_id,
                    "entity_type": "profile",
                    "entity_id": c_id,
                    "fact_category": "profile",
                    "fact_key": "profile_summary",
                    "fact_value": fact_value,
                    "confidence": confidence,
                    "source_type": "db_record",
                    "source_id": c_id,
                    "consent_status": "opt_in",
                    "verified_at": _now_utc().isoformat(),
                    "expires_at": _expires_in_days(180),
                }
            )
        if c_type == "club" and c_id in orgs_by_id:
            org = orgs_by_id[c_id]
            fact_value = f"{org.get('name')} - {org.get('meeting_time')} at {org.get('meeting_place')}"
            db.create_verified_fact(
                {
                    "university_id": university_id,
                    "entity_type": "organization",
                    "entity_id": c_id,
                    "fact_category": "club",
                    "fact_key": "club_details",
                    "fact_value": fact_value,
                    "confidence": confidence,
                    "source_type": "db_record",
                    "source_id": c_id,
                    "consent_status": "opt_in",
                    "verified_at": _now_utc().isoformat(),
                    "expires_at": _expires_in_days(180),
                }
            )


def write_verified_fact_from_outreach(
    university_id: str,
    run_id: str,
    answer_text: str,
    confidence: float,
    result_summary: Optional[str] = None,
) -> None:
    """Cache outreach-verified result summary."""
    if confidence < settings.OUTREACH_CONFIDENCE_THRESHOLD:
        return
    fact_value = result_summary or answer_text
    db.create_verified_fact(
        {
            "university_id": university_id,
            "entity_type": "outreach",
            "entity_id": None,
            "fact_category": "outreach",
            "fact_key": "outreach_summary",
            "fact_value": fact_value,
            "confidence": confidence,
            "source_type": "outreach_reply",
            "source_id": run_id,
            "consent_status": "opt_in",
            "verified_at": _now_utc().isoformat(),
            "expires_at": _expires_in_days(14),
        }
    )


def compute_db_confidence(records: dict, tags: list[str], time_window: Optional[str]) -> float:
    """Simple deterministic confidence score for DB-based answers."""
    summaries = _record_summaries(records)
    if not summaries:
        return 0.1

    max_overlap = 0.0
    completeness = 0.0
    for item in summaries:
        text = " ".join([str(v or "") for v in item.values()]).lower()
        if tags:
            overlap = sum(1 for t in tags if t in text) / max(len(tags), 1)
        else:
            overlap = 0.4
        max_overlap = max(max_overlap, overlap)

        if item.get("type") == "event":
            has_time = bool(item.get("start_at"))
            has_location = bool(item.get("location"))
            completeness = max(completeness, 0.2 + 0.4 * int(has_time) + 0.4 * int(has_location))
        else:
            completeness = max(completeness, 0.6)

    corroboration = min(0.2, 0.05 * max(len(summaries) - 1, 0))
    score = 0.4 + 0.4 * max_overlap + 0.2 * completeness + corroboration
    return max(0.1, min(0.95, score))


def compose_grounded_answer(question: str, records: dict, style_instructions: str = "") -> dict:
    """Prompt B - Grounded Answer Composer."""
    summaries = _record_summaries(records)
    prompt = f"""You are Link. You MUST ONLY use the provided records. If they are insufficient, choose needs_outreach or ask_clarifying.

User question: "{question}"
Style: {style_instructions}
{DB_SCHEMA_HINT}

Records (IDs and key fields):
{summaries}

Return JSON:
{{
  "answer_mode": "direct" | "needs_outreach" | "ask_clarifying",
  "confidence": number,
  "answer_text": string,
  "cards": {{"event_ids"?:[], "user_ids"?:[], "club_ids"?:[]}},
  "citations": [{{"type":"event"|"user"|"club", "id":"..."}}],
  "why": string
}}
"""

    result = llm_json(prompt, temperature=0)

    answer_mode = result.get("answer_mode") or "needs_outreach"
    if answer_mode not in {"direct", "needs_outreach", "ask_clarifying"}:
        answer_mode = "needs_outreach"

    confidence = float(result.get("confidence") or 0.0)
    answer_text = result.get("answer_text") or ""
    cards = result.get("cards") or {}
    citations = result.get("citations") or []

    return {
        "answer_mode": answer_mode,
        "confidence": max(0.0, min(1.0, confidence)),
        "answer_text": answer_text,
        "cards": cards,
        "citations": citations,
        "why": result.get("why") or "",
    }


def _matches_record(record: dict, tags: list[str]) -> bool:
    if not tags:
        return True
    hay = " ".join([str(record.get(k, "")) for k in ["name", "title", "category", "mission_statement", "description"]]).lower()
    return any(t.lower() in hay for t in tags if t)


def try_db_query(question: str, intent: str, records: dict, tags: Optional[list[str]] = None) -> Optional[dict]:
    """Deterministic DB-first answers for obvious queries (no LLM)."""
    text = (question or "").lower()
    if "how many" in text:
        if any(x in text for x in ["club", "clubs", "org", "organization", "organizations"]):
            return {"type": "count_orgs"}
        if any(x in text for x in ["event", "events"]):
            return {"type": "count_events"}
        if "major" in text:
            if "computer science" in text or "comp sci" in text or "compsci" in text or "cs " in text:
                major_query = "computer science"
            else:
                major_query = (tags or [None])[0]
            return {"type": "count_major", "major_query": major_query}
    if "how many" in text and any(x in text for x in ["user", "users", "students", "people"]):
        return {"type": "count_users"}
    if intent in {"club_search", "campus_info"}:
        orgs = records.get("orgs") or []
        if orgs:
            filtered = [o for o in orgs if _matches_record(o, tags or [])]
            picked = (filtered or orgs)[:2]
            return {
                "type": "list_orgs",
                "answer_text": "here are a couple clubs that match:",
                "items": picked,
                "citations": [{"type": "club", "id": o.get("id")} for o in picked],
                "confidence": 0.8,
            }
    if intent == "event_search":
        events = records.get("events") or []
        if events:
            filtered = [e for e in events if _matches_record(e, tags or [])]
            picked = (filtered or events)[:2]
            return {
                "type": "list_events",
                "answer_text": "here are a couple events coming up:",
                "items": picked,
                "citations": [{"type": "event", "id": e.get("id")} for e in picked],
                "confidence": 0.8,
            }
    if intent == "person_search":
        profiles = records.get("profiles") or []
        if profiles:
            filtered = [p for p in profiles if _matches_record(p, tags or [])]
            picked = (filtered or profiles)[:2]
            return {
                "type": "list_people",
                "answer_text": "i found a couple people:",
                "items": picked,
                "citations": [{"type": "user", "id": p.get("id")} for p in picked],
                "confidence": 0.75,
            }
    return None


def insert_cards_from_items(
    conversation_id: str,
    university_id: str,
    items: list[dict],
    item_type: str,
    session_id: Optional[str] = None,
) -> None:
    """Insert card messages directly from item payloads."""
    link_profile = db.get_link_system_profile(university_id)
    sender_id = link_profile.get("link_user_id") if link_profile else None
    for item in items:
        metadata = build_card_metadata(item, item_type)
        if metadata:
            title = (
                item.get("title")
                or item.get("name")
                or item.get("full_name")
                or "Card"
            )
            db.insert_link_message(
                conversation_id,
                sender_id,
                title,
                metadata,
                session_id=session_id,
            )


def start_link_relay(
    requester_user_id: str,
    requester_conversation_id: str,
    target_user_id: str,
    question: str,
    university_id: str,
    session_id: Optional[str] = None,
) -> dict:
    """Ask another user's Link instance a question (no connection)."""
    run = db.create_link_relay_run(
        {
            "requester_user_id": requester_user_id,
            "requester_conversation_id": requester_conversation_id,
            "target_user_id": target_user_id,
            "question": question,
            "status": "pending",
        }
    )
    target_convo = db.get_or_create_link_conversation(target_user_id)
    link_profile = db.get_link_system_profile(university_id)
    sender_id = link_profile.get("link_user_id") if link_profile else None
    prompt = f"{question} (reply here)"
    msg = db.insert_link_message(
        target_convo["id"],
        sender_id,
        prompt,
        {"shareType": "text", "relay_run_id": run["id"]},
        sender_type="link",
    )
    db.create_link_relay_target(
        {
            "run_id": run["id"],
            "dm_conversation_id": target_convo["id"],
            "outreach_message_id": msg.get("id"),
            "status": "sent",
        }
    )
    db.update_link_relay_run(run["id"], {"status": "awaiting_target"})
    # Notify requester
    insert_link_response(
        requester_conversation_id,
        university_id,
        "gotchu. i'll ask and get back to you.",
        citations=[],
        cards={},
        confidence=0.5,
        session_id=session_id,
        task_state="relay",
    )
    return {"run_id": run["id"]}


def collect_link_relay(run_id: str, university_id: str, session_id: Optional[str] = None) -> dict:
    """Collect reply from target's Link conversation and relay it."""
    run = db.get_link_relay_run(run_id)
    if not run:
        return {"status": "failed", "message": "Run not found"}
    targets = db.list_link_relay_targets(run_id)
    if not targets:
        return {"status": "failed", "message": "No target"}
    target = targets[0]
    replies = db.list_link_messages_for_conversation(
        target["dm_conversation_id"],
        after=target.get("sent_at"),
        sender_type="user",
        limit=5,
    )
    if not replies:
        return {"status": "awaiting_target"}
    reply = replies[0]
    db.update_link_relay_target(
        target["id"],
        {
            "reply_message_id": reply.get("id"),
            "status": "replied",
            "updated_at": _now_utc().isoformat(),
        },
    )
    db.update_link_relay_run(
        run_id,
        {"status": "answered", "updated_at": _now_utc().isoformat()},
    )
    citation = [{"type": "user", "id": run.get("target_user_id"), "message_id": reply.get("id")}]
    insert_link_response(
        run.get("requester_conversation_id"),
        university_id,
        f"they said: {reply.get('content')}",
        citations=citation,
        cards={},
        confidence=0.6,
        session_id=session_id,
        task_state="answered",
    )
    return {"status": "answered"}

def build_outreach_message(
    question: str,
    intent: str,
    tags: list[str],
    style_instructions: str = "",
    requester_profile: Optional[dict] = None,
) -> str:
    """Prompt C - Outreach Message Generator."""
    topic = tags[0] if tags else "this"
    name = requester_profile.get("full_name") if requester_profile else "a student"
    reason = question or topic
    # Keep outreach concise and consent-focused.
    return (
        f"yo! quick q from Link - {name} is looking for {reason}. "
        "if you're down for an intro, reply YES. if not, reply NO."
    )


def extract_and_rank_replies(replies: list[dict], original_query: str, style_instructions: str = "") -> dict:
    """Prompt D - Reply Extractor + Ranker."""
    if settings.TEST_MODE:
        first = replies[0] if replies else {}
        return {
            "extracted_claims": [
                {
                    "claim": first.get("text", ""),
                    "event_name": None,
                    "time": None,
                    "location": None,
                    "source": None,
                    "mentioned_people": [],
                    "confidence": 0.6,
                }
            ],
            "ranked_results": [
                {
                    "result_summary": first.get("text", ""),
                    "supporting_reply_ids": [first.get("message_id")] if first else [],
                    "score": 0.6,
                    "reasons": ["test_mode"],
                }
            ],
            "final_answer_text": "I heard back from someone who said they're down. Want me to connect you?",
            "confidence": 0.6,
            "suggested_connection_user_id": first.get("user_id"),
        }
    prompt = f"""You are Link. Extract claims and rank outreach replies. If a reply explicitly says they want to be connected, set suggested_connection_user_id to that user's id.

Original query: "{original_query}"
Style: {style_instructions}

Replies (user_id, message_id, text):
{replies}

Return JSON:
{{
  "extracted_claims": [{{"claim":"...","event_name":null,"time":null,"location":null,"source":null,"mentioned_people":[],"confidence":0.0}}],
  "ranked_results": [{{"result_summary":"...","supporting_reply_ids":[],"score":0.0,"reasons":[]}}],
  "final_answer_text": "...",
  "confidence": 0.0,
  "suggested_connection_user_id": null
}}
"""

    result = llm_json(prompt, temperature=0)
    return {
        "extracted_claims": result.get("extracted_claims") or [],
        "ranked_results": result.get("ranked_results") or [],
        "final_answer_text": result.get("final_answer_text") or "",
        "confidence": float(result.get("confidence") or 0.0),
        "suggested_connection_user_id": result.get("suggested_connection_user_id"),
    }


def compute_outreach_confidence(replies: list[dict]) -> float:
    """Deterministic confidence for outreach-based answers."""
    if not replies:
        return 0.1

    base = 0.4
    boost = 0.0
    for reply in replies:
        text = (reply.get("text") or "").lower()
        if any(x in text for x in ["event", "meet", "session", "talk"]):
            boost += 0.2
            break
    for reply in replies:
        text = (reply.get("text") or "").lower()
        if any(x in text for x in ["pm", "am", "tonight", "today", "at ", "location", "room"]):
            boost += 0.2
            break
    for reply in replies:
        text = (reply.get("text") or "").lower()
        if any(x in text for x in ["discord", "email", "ig", "instagram", "group chat", "flyer"]):
            boost += 0.2
            break
    if len(replies) >= 2:
        boost += 0.2

    return min(0.95, base + boost)


def insert_link_response(
    conversation_id: str,
    university_id: str,
    text: str,
    citations: list[dict],
    cards: dict,
    confidence: float,
    session_id: Optional[str] = None,
    task_state: Optional[str] = None,
) -> None:
    link_profile = db.get_link_system_profile(university_id)
    sender_id = link_profile.get("link_user_id") if link_profile else None
    text = dedupe_response(conversation_id, text, intent_type="general")
    metadata = {
        "shareType": "text",
        "citations": citations,
        "cards": cards,
        "confidence": confidence,
    }
    if task_state:
        metadata["task_state"] = task_state
    db.insert_link_message(conversation_id, sender_id, text, metadata, session_id=session_id)

    if not cards:
        return

    for event_id in cards.get("event_ids") or []:
        event = db.get_event(event_id)
        if not event:
            continue
        metadata = build_card_metadata(event, "event")
        if metadata:
            db.insert_link_message(conversation_id, sender_id, event.get("title") or "Event", metadata, session_id=session_id)

    for user_id in cards.get("user_ids") or []:
        profile = db.get_profile(user_id, enforce_public=True)
        if not profile:
            continue
        metadata = build_card_metadata(profile, "profile")
        if metadata:
            db.insert_link_message(conversation_id, sender_id, profile.get("full_name") or "Student", metadata, session_id=session_id)

    for org_id in cards.get("club_ids") or []:
        org = db.get_organization(org_id)
        if not org:
            continue
        metadata = build_card_metadata(org, "organization")
        if metadata:
            db.insert_link_message(conversation_id, sender_id, org.get("name") or "Club", metadata, session_id=session_id)


def start_outreach(
    user_id: str,
    university_id: str,
    link_conversation_id: str,
    question: str,
    intent: dict,
    session_id: Optional[str] = None,
    access_token: Optional[str] = None,
) -> dict:
    """Create an outreach run and DM targets."""
    run = db.create_link_outreach_run(
        {
            "link_conversation_id": link_conversation_id,
            "requester_user_id": user_id,
            "query": question,
            "intent": intent.get("intent"),
            "status": "collecting",
            "intent_payload": intent,
        }
    )

    tags = intent.get("tags") or []
    style_instructions = build_style_instructions(None)
    requester_profile = None
    if access_token:
        requester_profile = db.get_profile_rls(access_token, user_id)
    if not requester_profile:
        requester_profile = db.get_profile(user_id, enforce_public=True)
    if requester_profile and not requester_profile.get("yearbook_visible", True):
        requester_profile = None
    requester_memory = db.get_user_memory(user_id) or {}
    preferred_name = (requester_memory.get("known_preferences") or {}).get("preferred_name")
    dm_text = build_outreach_message(
        question,
        intent.get("intent"),
        tags,
        style_instructions=style_instructions,
        requester_profile=requester_profile,
    )
    if preferred_name and requester_profile:
        dm_text = dm_text.replace(requester_profile.get("full_name") or "", preferred_name)

    batch_size = min(settings.OUTREACH_BATCH_SIZE, 10)
    recent_targets = db.list_recent_outreach_target_ids(user_id, days=7)
    targets = outreach_logic.select_outreach_targets(
        requester_id=user_id,
        university_id=university_id,
        entities=tags,
        batch_size=batch_size,
        excluded_ids=[user_id] + recent_targets,
    )

    link_profile = db.get_link_system_profile(university_id)
    sender_id = link_profile.get("link_user_id") if link_profile else None

    target_rows: list[dict] = []
    for target in targets:
        target_user_id = target.get("user_id")
        if not target_user_id or not sender_id:
            continue
        convo = db.get_or_create_dm_conversation(sender_id, target_user_id)
        if not convo:
            continue
        message = db.insert_message(
            convo["id"],
            sender_id,
            dm_text,
            {
                "shareType": "text",
                "requester_user_id": user_id,
                "requester_profile": {
                    "full_name": requester_profile.get("full_name") if requester_profile else None,
                    "username": requester_profile.get("username") if requester_profile else None,
                    "major": requester_profile.get("major") if requester_profile else None,
                    "bio": requester_profile.get("bio") if requester_profile else None,
                    "interests": requester_profile.get("interests") if requester_profile else None,
                },
            },
        )
        if requester_profile:
            profile_metadata = build_card_metadata(requester_profile, "profile")
            if profile_metadata:
                db.insert_message(
                    convo["id"],
                    sender_id,
                    requester_profile.get("full_name") or "Profile",
                    profile_metadata,
                )
        db.insert_message(
            convo["id"],
            sender_id,
            "Want an intro? Reply YES or NO.",
            {"shareType": "text"},
        )
        target_rows.append(
            {
                "run_id": run["id"],
                "target_user_id": target_user_id,
                "dm_conversation_id": convo["id"],
                "outreach_message_id": message.get("id"),
                "status": "sent",
            }
        )

    if target_rows:
        db.create_link_outreach_targets(target_rows)

    link_profile = db.get_link_system_profile(university_id)
    sender_id = link_profile.get("link_user_id") if link_profile else None
    db.insert_link_message(
        link_conversation_id,
        sender_id,
        dedupe_response(link_conversation_id, "not sure yet - i'll ask a few people and report back.", intent_type="outreach_started"),
        {
            "shareType": "text",
            "run_id": run["id"],
            "run_status": "collecting",
            "asked_count": len(target_rows),
            "task_state": "collecting",
        },
        session_id=session_id,
    )

    return {"run_id": run["id"], "targets": target_rows, "dm_text": dm_text}


def collect_outreach(
    run_id: str,
    university_id: str,
    session_id: Optional[str] = None,
    access_token: Optional[str] = None,
) -> dict:
    """Collect replies and respond in Link chat."""
    run = db.get_link_outreach_run(run_id)
    if not run:
        return {"status": "failed", "message": "Run not found"}

    targets = db.list_link_outreach_targets(run_id)
    replies: list[dict] = []

    for target in targets:
        if target.get("status") == "replied":
            continue
        messages = db.list_messages_for_conversation(
            target["dm_conversation_id"],
            after=target.get("sent_at"),
            sender_id=target.get("target_user_id"),
            limit=5,
        )
        if not messages:
            continue
        reply = messages[0]
        db.update_link_outreach_target(
            target["id"],
            {
                "reply_message_id": reply.get("id"),
                "status": "replied",
                "updated_at": _now_utc().isoformat(),
            },
        )
        replies.append(
            {
                "user_id": target.get("target_user_id"),
                "message_id": reply.get("id"),
                "text": reply.get("content"),
            }
        )

    if not replies:
        replies = []

    if (
        not replies
        and not run.get("forum_post_id")
        and access_token
        and int(run.get("expansions") or 0) >= 2
        and len(targets) >= 10
    ):
        created = create_forum_post(
            access_token,
            university_id,
            run.get("requester_user_id"),
            run.get("query"),
            (run.get("intent_payload") or {}).get("tags") or [],
        )
        if created:
            forum = created.get("forum") or {}
            post = created.get("post") or {}
            db.update_link_outreach_run(
                run_id,
                {
                    "status": "forum_posted",
                    "forum_id": forum.get("id"),
                    "forum_post_id": post.get("id"),
                    "forum_posted_at": _now_utc().isoformat(),
                    "updated_at": _now_utc().isoformat(),
                },
            )
            link_profile = db.get_link_system_profile(university_id)
            sender_id = link_profile.get("link_user_id") if link_profile else None
            if sender_id:
                db.insert_link_message(
                    run.get("link_conversation_id"),
                    sender_id,
                    "I couldn't find anyone yet, so I made an anonymous forum post. I'll let you know if anyone replies.",
                    {"shareType": "text", "run_id": run_id, "forum_post_id": post.get("id")},
                    session_id=session_id,
                )
        return {"status": run.get("status"), "message": "Posted to forum."}

    if run.get("forum_post_id") and access_token:
        posted_at = run.get("forum_posted_at") or run.get("updated_at")
        comments = db.list_forum_comments_rls(access_token, run.get("forum_post_id"), after=posted_at)
        if comments:
            requester_profile = db.get_profile_rls(access_token, run.get("requester_user_id"))
            if requester_profile and not requester_profile.get("yearbook_visible", True):
                requester_profile = None
            dm_text = build_outreach_message(
                run.get("query"),
                run.get("intent"),
                (run.get("intent_payload") or {}).get("tags") or [],
                style_instructions=build_style_instructions(None),
                requester_profile=requester_profile,
            )
            existing_targets = {t.get("target_user_id") for t in targets}
            new_rows: list[dict] = []
            link_profile = db.get_link_system_profile(university_id)
            sender_id = link_profile.get("link_user_id") if link_profile else None
            for comment in comments:
                commenter_id = comment.get("user_id")
                if not commenter_id or commenter_id in existing_targets or not sender_id:
                    continue
                convo = db.get_or_create_dm_conversation(sender_id, commenter_id)
                if not convo:
                    continue
                message = db.insert_message(
                    convo["id"],
                    sender_id,
                    dm_text,
                    {"shareType": "text", "requester_user_id": run.get("requester_user_id")},
                )
                if requester_profile:
                    profile_metadata = build_card_metadata(requester_profile, "profile")
                    if profile_metadata:
                        db.insert_message(
                            convo["id"],
                            sender_id,
                            requester_profile.get("full_name") or "Profile",
                            profile_metadata,
                        )
                db.insert_message(
                    convo["id"],
                    sender_id,
                    "Want an intro? Reply YES or NO.",
                    {"shareType": "text"},
                )
                new_rows.append(
                    {
                        "run_id": run_id,
                        "target_user_id": commenter_id,
                        "dm_conversation_id": convo["id"],
                        "outreach_message_id": message.get("id"),
                        "status": "sent",
                        "source_comment_id": comment.get("id"),
                    }
                )
            if new_rows:
                db.create_link_outreach_targets(new_rows)
        return {"status": run.get("status"), "message": "Collecting forum replies."}

    min_replies = 2 if len(replies) >= 2 else 1
    if len(replies) < min_replies:
        expansions = int(run.get("expansions") or 0)
        max_targets = 10
        if expansions < 2 and len(targets) < max_targets:
            additional = min(5, max_targets - len(targets))
            excluded_ids = [run.get("requester_user_id")] + [t.get("target_user_id") for t in targets]
            requester_profile = db.get_profile(run.get("requester_user_id"), enforce_public=True)
            if requester_profile and not requester_profile.get("yearbook_visible", True):
                requester_profile = None
            more_targets = outreach_logic.select_outreach_targets(
                requester_id=run.get("requester_user_id"),
                university_id=university_id,
                entities=(run.get("intent_payload") or {}).get("tags") or [],
                batch_size=additional,
                excluded_ids=excluded_ids,
            )
            link_profile = db.get_link_system_profile(university_id)
            sender_id = link_profile.get("link_user_id") if link_profile else None
            dm_text = build_outreach_message(
                run.get("query"),
                run.get("intent"),
                (run.get("intent_payload") or {}).get("tags") or [],
                style_instructions=build_style_instructions(None),
                requester_profile=requester_profile,
            )
            new_rows: list[dict] = []
            for target in more_targets:
                target_user_id = target.get("user_id")
                if not target_user_id or not sender_id:
                    continue
                convo = db.get_or_create_dm_conversation(sender_id, target_user_id)
                if not convo:
                    continue
                message = db.insert_message(convo["id"], sender_id, dm_text, {"shareType": "text"})
                if requester_profile:
                    profile_metadata = build_card_metadata(requester_profile, "profile")
                    if profile_metadata:
                        db.insert_message(
                            convo["id"],
                            sender_id,
                            requester_profile.get("full_name") or "Profile",
                            profile_metadata,
                        )
                db.insert_message(
                    convo["id"],
                    sender_id,
                    "Want an intro? Reply YES or NO.",
                    {"shareType": "text"},
                )
                new_rows.append(
                    {
                        "run_id": run_id,
                        "target_user_id": target_user_id,
                        "dm_conversation_id": convo["id"],
                        "outreach_message_id": message.get("id"),
                        "status": "sent",
                    }
                )
            if new_rows:
                db.create_link_outreach_targets(new_rows)
                db.update_link_outreach_run(
                    run_id,
                    {
                        "expansions": expansions + 1,
                        "updated_at": _now_utc().isoformat(),
                    },
                )
                db.insert_link_message(
                    run.get("link_conversation_id"),
                    sender_id,
                    "still waiting on replies - i asked a few more people.",
                    {
                        "shareType": "text",
                        "run_id": run_id,
                        "run_status": "collecting",
                        "asked_count": len(targets) + len(new_rows),
                        "task_state": "collecting",
                    },
                    session_id=session_id,
                )
        return {"status": run.get("status"), "message": "Still collecting replies."}

    requester_memory = db.get_user_memory(run.get("requester_user_id")) if run.get("requester_user_id") else None
    style_instructions = build_style_instructions(requester_memory)
    extracted = extract_and_rank_replies(replies, run.get("query"), style_instructions=style_instructions)
    confidence = compute_outreach_confidence(replies)

    citations = [
        {"type": "outreach_reply", "id": r.get("message_id"), "user_id": r.get("user_id")}
        for r in replies
    ]

    answer_text = extracted.get("final_answer_text") or "Here's what I heard back."
    ranked = extracted.get("ranked_results") or []
    top_summary = ranked[0].get("result_summary") if ranked else None

    convo_id = run.get("link_conversation_id")
    insert_link_response(
        convo_id,
        university_id,
        answer_text,
        citations,
        cards={},
        confidence=confidence,
        session_id=session_id,
    )
    try:
        write_verified_fact_from_outreach(
            university_id,
            run_id,
            answer_text,
            confidence,
            result_summary=top_summary,
        )
    except Exception:
        pass

    suggested = extracted.get("suggested_connection_user_id")
    if run.get("intent") == "person_search" and not suggested:
        for reply in replies:
            reply_type, consent, _ = outreach_logic.interpret_reply(reply.get("text") or "")
            if consent == "yes":
                suggested = reply.get("user_id")
                break
    if suggested:
        link_profile = db.get_link_system_profile(university_id)
        sender_id = link_profile.get("link_user_id") if link_profile else None
        db.update_link_outreach_run(
            run_id,
            {
                "status": "awaiting_consent",
                "suggested_connection_user_id": suggested,
                "confidence": confidence,
                "updated_at": _now_utc().isoformat(),
            },
        )
        try:
            convo_state = db.get_link_conversation_state(run.get("requester_user_id"), convo_id)
            if convo_state:
                pending = convo_state.get("pending_consents") or []
                pending.append(
                    {
                        "id": run_id,
                        "type": "requester",
                        "user_id": run.get("requester_user_id"),
                        "message_sent_at": _now_utc().isoformat(),
                        "response": "pending",
                    }
                )
                db.update_link_conversation_state(
                    convo_state["id"],
                    {
                        "mode": "awaiting_consent",
                        "pending_consents": pending,
                        "updated_at": _now_utc().isoformat(),
                    },
                )
        except Exception:
            pass
        if sender_id:
            db.insert_link_message(
                convo_id,
                sender_id,
                "Want me to connect you?",
                {"shareType": "text", "run_id": run_id, "suggested_user_id": suggested, "task_state": "awaiting_consent"},
                session_id=session_id,
            )
        return {"status": "awaiting_consent", "confidence": confidence}

    db.update_link_outreach_run(
        run_id,
        {
            "status": "done",
            "confidence": confidence,
            "updated_at": _now_utc().isoformat(),
        },
    )
    try:
        convo_state = db.get_link_conversation_state(run.get("requester_user_id"), convo_id)
        if convo_state:
            db.update_link_conversation_state(
                convo_state["id"],
                {
                    "mode": "conversation",
                    "active_task": None,
                    "updated_at": _now_utc().isoformat(),
                },
            )
    except Exception:
        pass

    return {"status": "done", "confidence": confidence}


def resolve_consent(
    run_id: str,
    requester_user_id: str,
    target_user_id: str,
    requester_ok: bool,
    target_ok: bool,
) -> dict:
    """Create an intro chat once both sides consent."""
    run = db.get_link_outreach_run(run_id)
    if not run:
        return {"status": "failed", "message": "Run not found"}

    convo_id = run.get("link_conversation_id")
    requester_profile = db.get_profile(requester_user_id, enforce_public=False) or {}
    university_id = requester_profile.get("university_id")
    link_profile = db.get_link_system_profile(university_id) if university_id else None
    link_sender_id = link_profile.get("link_user_id") if link_profile else None

    if requester_ok and target_ok:
        convo = db.create_conversation(
            {
                "type": "direct",
                "created_by": requester_user_id,
                "is_system_generated": True,
            }
        )
        db.add_conversation_participants(convo["id"], [requester_user_id, target_user_id])

        intro = "Intro: you both mentioned you're into this - I'll let you take it from here."
        if link_sender_id:
            db.insert_message(convo["id"], link_sender_id, intro, {"shareType": "text"})

        db.update_link_outreach_run(
            run_id,
            {
                "status": "done",
                "updated_at": _now_utc().isoformat(),
            },
        )
        if link_sender_id:
            db.insert_link_message(
                convo_id,
                link_sender_id,
                "Connected - I made a chat.",
                {"shareType": "text", "run_id": run_id, "run_status": "done", "task_state": "done"},
            )
        try:
            convo_state = db.get_link_conversation_state(requester_user_id, convo_id)
            if convo_state:
                pending = [c for c in (convo_state.get("pending_consents") or []) if c.get("id") != run_id]
                resolved = convo_state.get("resolved_tasks") or []
                resolved.append(
                    {
                        "id": run_id,
                        "type": "people_search",
                        "query": run.get("query"),
                        "status": "resolved",
                        "resolved_at": _now_utc().isoformat(),
                    }
                )
                db.update_link_conversation_state(
                    convo_state["id"],
                    {
                        "mode": "conversation",
                        "active_task": None,
                        "pending_consents": pending,
                        "resolved_tasks": resolved,
                        "updated_at": _now_utc().isoformat(),
                    },
                )
        except Exception:
            pass
        return {"status": "done", "conversation_id": convo["id"]}

    # If requester declines, let the target know politely and keep searching.
    if not requester_ok:
        if link_sender_id:
            convo = db.get_or_create_dm_conversation(link_sender_id, target_user_id)
            if convo:
                db.insert_message(
                    convo["id"],
                    link_sender_id,
                    "Hey! They already found someone, but if you're looking for friends who are into this, lmk and I can help.",
                    {"shareType": "text"},
                )
        db.update_link_outreach_run(
            run_id,
            {
                "status": "forum_posted" if run.get("forum_post_id") else "collecting",
                "suggested_connection_user_id": None,
                "updated_at": _now_utc().isoformat(),
            },
        )
        # mark target declined
        targets = db.list_link_outreach_targets(run_id)
        for t in targets:
            if t.get("target_user_id") == target_user_id:
                db.update_link_outreach_target(t.get("id"), {"status": "declined", "updated_at": _now_utc().isoformat()})
                break
        if link_sender_id:
            db.insert_link_message(
                convo_id,
                link_sender_id,
                "Got it - I'll keep looking for someone else.",
                {"shareType": "text", "run_id": run_id},
            )
        try:
            convo_state = db.get_link_conversation_state(requester_user_id, convo_id)
            if convo_state:
                pending = [c for c in (convo_state.get("pending_consents") or []) if c.get("id") != run_id]
                resolved = convo_state.get("resolved_tasks") or []
                resolved.append(
                    {
                        "id": run_id,
                        "type": "people_search",
                        "query": run.get("query"),
                        "status": "declined",
                        "resolved_at": _now_utc().isoformat(),
                    }
                )
                db.update_link_conversation_state(
                    convo_state["id"],
                    {
                        "mode": "conversation",
                        "active_task": None,
                        "pending_consents": pending,
                        "resolved_tasks": resolved,
                        "updated_at": _now_utc().isoformat(),
                    },
                )
        except Exception:
            pass
        return {"status": "collecting"}

    # If target declines, let requester know and keep searching.
    if not target_ok:
        db.update_link_outreach_run(
            run_id,
            {
                "status": "forum_posted" if run.get("forum_post_id") else "collecting",
                "suggested_connection_user_id": None,
                "updated_at": _now_utc().isoformat(),
            },
        )
        targets = db.list_link_outreach_targets(run_id)
        for t in targets:
            if t.get("target_user_id") == target_user_id:
                db.update_link_outreach_target(t.get("id"), {"status": "declined", "updated_at": _now_utc().isoformat()})
                break
        if link_sender_id:
            db.insert_link_message(
                convo_id,
                link_sender_id,
                "They weren't available, but I'll keep looking.",
                {"shareType": "text", "run_id": run_id},
            )
        try:
            convo_state = db.get_link_conversation_state(requester_user_id, convo_id)
            if convo_state:
                pending = [c for c in (convo_state.get("pending_consents") or []) if c.get("id") != run_id]
                resolved = convo_state.get("resolved_tasks") or []
                resolved.append(
                    {
                        "id": run_id,
                        "type": "people_search",
                        "query": run.get("query"),
                        "status": "declined",
                        "resolved_at": _now_utc().isoformat(),
                    }
                )
                db.update_link_conversation_state(
                    convo_state["id"],
                    {
                        "mode": "conversation",
                        "active_task": None,
                        "pending_consents": pending,
                        "resolved_tasks": resolved,
                        "updated_at": _now_utc().isoformat(),
                    },
                )
        except Exception:
            pass
        return {"status": "collecting"}

    db.update_link_outreach_run(
        run_id,
        {
            "status": "failed",
            "updated_at": _now_utc().isoformat(),
        },
    )
    if link_sender_id:
        db.insert_link_message(
            convo_id,
            link_sender_id,
            "No worries - I won't connect you.",
            {"shareType": "text", "run_id": run_id, "run_status": "done", "task_state": "done"},
        )
    return {"status": "failed"}
