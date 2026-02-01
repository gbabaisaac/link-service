"""Core Link AI brain logic - intent parsing, confidence scoring, response generation."""

import json
import re
from typing import Optional

from config import settings
from schemas import Intent, ValidationInfo, ResultItem, SourceItem, ResponseContent
import rag_index
import supabase_client as db


# LLM adapter (OpenAI or Gemini)

def llm_json(prompt: str, temperature: float = 0.0) -> dict:
    """Call the configured LLM and return a JSON object (dict)."""
    def _openai_call() -> dict:
        from openai import OpenAI
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=temperature,
        )
        return json.loads(resp.choices[0].message.content or "{}")

    if settings.LLM_PROVIDER == "gemini":
        try:
            import google.generativeai as genai
            genai.configure(api_key=settings.GOOGLE_API_KEY)
            model = genai.GenerativeModel(
                "gemini-2.0-flash",
                generation_config={"response_mime_type": "application/json", "temperature": temperature},
            )
            resp = model.generate_content(prompt)
            text = getattr(resp, "text", None) or (resp.candidates[0].content.parts[0].text if resp.candidates else "{}")
            return json.loads(text or "{}")
        except Exception:
            if settings.OPENAI_API_KEY:
                try:
                    return _openai_call()
                except Exception:
                    return {}
            return {}
    else:
        try:
            return _openai_call()
        except Exception:
            return {}


# ============ Intent Classification ============

INTENT_PATTERNS = {
    "find_people": ["looking for", "anyone who", "people that", "find someone", "know anyone", "who plays", "partners"],
    "find_info": ["where is", "what time", "how do i", "tell me about", "what's the", "when does"],
    "find_event": ["events", "happening", "things to do", "activities", "what's going on"],
    "find_org": ["clubs", "organizations", "groups", "join a", "orgs"],
    "checkin_response": ["good", "fine", "stressed", "busy", "excited", "tired", "great"],
}

SMALL_TALK_PATTERNS = [
    "hi", "hello", "hey", "yo", "sup", "what's up", "whats up", "wyd", "how are you", "how's it going",
]

ENTITY_SYNONYMS = {
    "cs": ["computer science", "comp sci", "comp-sci", "compsci", "computer-science", "computerscience"],
}


def normalize_entities(entities: list[str]) -> list[str]:
    """Expand entities with lightweight synonyms."""
    normalized: list[str] = []
    for e in entities or []:
        e = (e or "").strip().lower()
        if not e:
            continue
        if e not in normalized:
            normalized.append(e)
        for syn in ENTITY_SYNONYMS.get(e, []):
            if syn not in normalized:
                normalized.append(syn)
    return normalized


def _is_small_talk(question: str) -> bool:
    q = (question or "").strip().lower()
    if not q:
        return True
    if len(q.split()) <= 3 and any(p in q for p in SMALL_TALK_PATTERNS):
        return True
    return False


def extract_preferences(question: str) -> list[str]:
    """Extract simple preference phrases from user messages."""
    text = (question or "").lower()
    patterns = [
        r"i like ([^\\.,!?]+)",
        r"i love ([^\\.,!?]+)",
        r"i enjoy ([^\\.,!?]+)",
        r"i'm into ([^\\.,!?]+)",
    ]
    prefs: list[str] = []
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            pref = match.group(1).strip()
            if pref and pref not in prefs:
                prefs.append(pref)
    return prefs


def parse_intent(question: str, conversation_history: list[dict] = None) -> Intent:
    """Parse user question into structured intent using LLM or simple patterns in TEST_MODE."""
    if settings.TEST_MODE:
        if _is_small_talk(question):
            return Intent(type="small_talk", entities=[], filters={})
        q = question.lower()
        if any(p in q for p in ("looking for", "who plays", "partners", "anyone who")):
            return Intent(type="find_people", entities=normalize_entities([]), filters={})
        if any(p in q for p in ("where", "what time", "how do i")):
            return Intent(type="find_info", entities=normalize_entities([]), filters={})
        return Intent(type="general_question", entities=[], filters={})

    # Build context from conversation history
    history_context = ""
    if conversation_history:
        history_context = "\n".join(
            [f"{msg['role']}: {msg['content']}" for msg in conversation_history[-5:]]
        )

    prompt = f"""Analyze this user message and extract the intent.

User message: "{question}"
{f"Recent conversation: {history_context}" if history_context else ""}

Classify the intent as one of:
- small_talk: Greetings or casual chat
- find_people: Looking for people with specific interests/skills
- find_info: Asking for information about something
- find_event: Looking for events or activities
- find_org: Looking for clubs or organizations
- general_question: General question or chat
- checkin_response: Responding to a check-in question

Extract key entities (nouns, activities, topics mentioned).
Extract any filters (time constraints, preferences, requirements).

Respond in JSON format:
{{
    "type": "intent_type",
    "entities": ["entity1", "entity2"],
    "filters": {{}}
}}"""

    result = llm_json(prompt, temperature=0)

    try:
        intent = Intent(
            type=result.get("type", "general_question"),
            entities=normalize_entities(result.get("entities", [])),
            filters=result.get("filters", {}),
        )
        if _is_small_talk(question):
            intent.type = "small_talk"
        return intent
    except (json.JSONDecodeError, KeyError):
        # Fallback to pattern matching
        question_lower = question.lower()
        if _is_small_talk(question):
            return Intent(type="small_talk", entities=[], filters={})
        for intent_type, patterns in INTENT_PATTERNS.items():
            if any(p in question_lower for p in patterns):
                return Intent(type=intent_type, entities=normalize_entities([]), filters={})
        return Intent(type="general_question", entities=[], filters={})


# ============ Confidence Scoring ============

def calculate_confidence(
    results: list[dict], facts: list[dict], intent: Intent
) -> ValidationInfo:
    """Calculate confidence score using dual retrieval agreement."""
    # Base confidence from result count
    if len(results) == 0:
        base = 0.1
    elif len(results) < 3:
        base = 0.5
    else:
        base = 0.8

    # Agreement score from dual retrieval
    _, _, agreement = rag_index.retrieve_dual(" ".join(intent.entities) if intent.entities else "query")

    # Source quality - weight opt_in facts higher
    opt_in_facts = [f for f in facts if f.get("consent") == "opt_in"]
    source_quality = 0.5 + (0.5 * len(opt_in_facts) / max(len(facts), 1))

    system_confidence = round(base * agreement * source_quality, 2)

    return ValidationInfo(
        system_confidence=system_confidence,
        agreement_score=round(agreement, 2),
        sources_count=len(results),
        verified_facts_used=len(opt_in_facts),
    )


# ============ Response Generation ============

def generate_response(
    question: str,
    intent: Intent,
    results: list[dict],
    user_memory: Optional[dict] = None,
    need_outreach: bool = False,
) -> ResponseContent:
    """Generate Link's friendly response."""
    if intent.type == "small_talk":
        return ResponseContent(
            message="hey! what's up? want help finding people, events, or info on campus?",
            tone="friendly",
            suggestions=["Find clubs", "Find events", "Meet people"],
        )
    if intent.type == "general_question" and not results and not need_outreach:
        return ResponseContent(
            message="got it - what do you want to find on campus?",
            tone="friendly",
            suggestions=["Clubs", "Events", "People"],
        )
    if settings.TEST_MODE:
        # Simple offline response for testing
        msg = ""
        if intent.type == "find_people":
            msg = "tennis partners! i can ask around if you want."
        elif intent.type == "find_info":
            msg = "i might not have that info cached. want me to check and get back?"
        else:
            msg = "got it! how can i help more specifically?"
        return ResponseContent(message=msg, tone="friendly", suggestions=["Try reindexing later"]) 

    # Determine communication style
    archetype = "friendly"  # default
    if user_memory:
        archetype = user_memory.get("communication_archetype", "friendly")

    # Build results context
    results_text = ""
    if results:
        results_text = "\n".join(
            [f"- {r['name']} ({r['type']}): {r.get('text', '')[:100]}" for r in results[:5]]
        )

    prompt = f"""You are Link, a friendly AI assistant for campus communities.
You're helpful, warm, and build relationships with students.

User asked: "{question}"
Intent: {intent.type}
Entities: {intent.entities}

Relevant results found:
{results_text if results_text else "No specific results found."}

Need to ask around campus: {need_outreach}

Communication style to use: {archetype}
- If gen_z_casual: use lowercase, slang like "fr", "bet", strategic emojis
- If professional: proper grammar, formal tone
- If friendly (default): warm, helpful, moderate emoji use

Generate a helpful response. If need_outreach is True, offer to ask around.
Never mention specific people, posts, events, or organizations unless they appear in the results list.
If the results list is empty, do not invent names or content - ask a clarifying question instead.
If the intent is find_org, only talk about organizations (no forums/posts).
Keep it concise and natural.

Respond in JSON:
{{
    "message": "your response",
    "tone": "friendly",
    "suggestions": ["optional follow-up suggestions"]
}}"""

    result = llm_json(prompt, temperature=0.7)

    try:
        return ResponseContent(
            message=result.get("message", "I'm not sure how to help with that."),
            tone=result.get("tone", "friendly"),
            suggestions=result.get("suggestions", []),
        )
    except (json.JSONDecodeError, KeyError):
        return ResponseContent(
            message="I'm having trouble understanding. Could you rephrase that?",
            tone="friendly",
            suggestions=[],
        )


def build_results_payload(results: list[dict]) -> Optional[dict]:
    """Fetch full records for results so clients can render cards."""
    items: list[dict] = []
    types: set[str] = set()

    for result in results:
        r_type = result.get("type")
        record = None
        if r_type == "profile":
            record = db.get_profile(result.get("id", ""), enforce_public=True)
        elif r_type == "organization":
            record = db.get_organization(result.get("id", ""))
        elif r_type == "event":
            record = db.get_event(result.get("id", ""))
        elif r_type == "post":
            record = db.get_post(result.get("id", ""))

        if record:
            record["type"] = r_type
            items.append(record)
            types.add(r_type)

    if not items:
        return None

    if len(types) == 1:
        type_map = {
            "profile": "people",
            "organization": "orgs",
            "event": "events",
            "post": "posts",
        }
        payload_type = type_map.get(next(iter(types)), "mixed")
    else:
        payload_type = "mixed"

    return {"type": payload_type, "results": items}


def build_card_metadata(item: dict, item_type: str) -> Optional[dict]:
    """Convert full item into card metadata for the client UI."""
    if item_type == "profile":
        return {
            "shareType": "profile",
            "user_id": item.get("id"),
            "profile_id": item.get("id"),
            "id": item.get("id"),
            "full_name": item.get("full_name"),
            "username": item.get("username"),
            "avatar_url": item.get("avatar_url"),
            "major": item.get("major"),
            "graduation_year": item.get("graduation_year"),
            "mutual_friends": item.get("mutual_friends"),
        }
    if item_type == "event":
        return {
            "shareType": "event",
            "event_id": item.get("id"),
            "title": item.get("title"),
            "start_at": item.get("start_at"),
            "location_name": item.get("location_name"),
            "image_url": item.get("image_url"),
            "attendee_count": item.get("attendees_count"),
        }
    if item_type == "organization":
        return {
            "shareType": "org",
            "org_id": item.get("id"),
            "name": item.get("name"),
            "category": item.get("category"),
            "logo_url": item.get("logo_url"),
            "member_count": item.get("member_count"),
        }
    if item_type == "post":
        forum = item.get("forums") or {}
        return {
            "shareType": "post",
            "post_id": item.get("id"),
            "forum_id": item.get("forum_id"),
            "title": item.get("title"),
            "body": item.get("body"),
            "image_url": (item.get("media_urls") or [None])[0],
            "forum_name": forum.get("name"),
            "comments_count": item.get("comments_count"),
            "upvotes_count": item.get("upvotes_count"),
        }
    return None


# ============ Main Query Processing ============

def process_query(
    user_id: str,
    university_id: str,
    question: str,
    conversation_history: list[dict] = None,
    session_id: Optional[str] = None,
) -> dict:
    """Main query processing pipeline."""
    # 1. Parse intent
    intent = parse_intent(question, conversation_history)

    # 2. Handle simple count queries directly
    q_lower = question.lower()
    if intent.type in ["find_info", "general_question"]:
        if any(p in q_lower for p in ["how many org", "number of org", "org count", "organizations on campus"]):
            count = db.get_organizations_count(university_id)
            response = ResponseContent(
                message=f"There are {count} organizations on campus.",
                tone="friendly",
                suggestions=[],
            )
            validation = ValidationInfo(
                system_confidence=0.9,
                agreement_score=1.0,
                sources_count=0,
                verified_facts_used=0,
            )
            return {
                "intent": intent,
                "response": response,
                "results": [],
                "need_outreach": False,
                "outreach_request_id": None,
                "validation": validation,
                "sources": [],
                "memory_updated": False,
                "journal_entry_created": False,
            }
        if any(p in q_lower for p in ["how many event", "number of event", "events on campus"]):
            count = db.get_events_count(university_id)
            response = ResponseContent(
                message=f"There are {count} events on campus.",
                tone="friendly",
                suggestions=[],
            )
            validation = ValidationInfo(
                system_confidence=0.9,
                agreement_score=1.0,
                sources_count=0,
                verified_facts_used=0,
            )
            return {
                "intent": intent,
                "response": response,
                "results": [],
                "need_outreach": False,
                "outreach_request_id": None,
                "validation": validation,
                "sources": [],
                "memory_updated": False,
                "journal_entry_created": False,
            }

    # 3. Retrieve relevant documents (skip for general chat)
    results = []
    if intent.type in ["find_people", "find_info", "find_event", "find_org"]:
        search_query = question
        if intent.entities:
            search_query = f"{question} {' '.join(normalize_entities(intent.entities))}"
        results = rag_index.retrieve(search_query, top_k=5, university_id=university_id)

    # 4. Type-gate results based on intent
    if intent.type == "find_org":
        results = [r for r in results if r["type"] in ["organization", "link_fact"]]
    elif intent.type == "find_people":
        results = [r for r in results if r["type"] in ["profile", "link_fact"]]
    elif intent.type == "find_event":
        results = [r for r in results if r["type"] in ["event", "link_fact"]]

    # 5. Separate facts from other results
    facts = [r for r in results if r["type"] == "link_fact"]

    # 6. Calculate confidence
    validation = calculate_confidence(results, facts, intent)

    # 7. Determine if outreach is needed
    need_outreach = (
        validation.system_confidence < settings.CONFIDENCE_THRESHOLD
        and intent.type in ["find_people", "find_info", "find_org"]
    )

    # 8. Filter/limit results based on confidence (only for find intents)
    filtered_results = results
    min_confidence_to_show = 0.6
    if intent.type in ["find_people", "find_info", "find_event", "find_org"] and validation.system_confidence < settings.CONFIDENCE_THRESHOLD:
        verified = [r for r in results if r["type"] == "link_fact"]
        others = [r for r in results if r["type"] != "link_fact"]
        ordered = verified + others
        filtered_results = [r for r in ordered if (r.get("score") or 0) >= min_confidence_to_show]
        if not filtered_results:
            filtered_results = ordered[:1]
        else:
            filtered_results = filtered_results[:2]
    if intent.type == "find_people":
        # Drop unrelated profiles if they don't mention any entity keywords
        entities = normalize_entities(intent.entities)
        if entities:
            def _matches_entities(item: dict) -> bool:
                haystack = f"{item.get('name','')} {item.get('text','')}".lower()
                return any(e in haystack for e in entities)
            filtered_results = [r for r in filtered_results if _matches_entities(r)]
        else:
            filtered_results = []
        if not filtered_results:
            need_outreach = True

    if intent.type == "find_org":
        entities = normalize_entities(intent.entities)
        if entities:
            def _org_matches(item: dict) -> bool:
                haystack = f"{item.get('name','')} {item.get('text','')}".lower()
                return any(e in haystack for e in entities)
            filtered_results = [r for r in filtered_results if _org_matches(r)]
        if not filtered_results:
            need_outreach = True

    if intent.type in ["small_talk", "general_question", "checkin_response"]:
        filtered_results = []
        need_outreach = False

    if need_outreach:
        filtered_results = []

    # 7. Get user memory for style
    user_memory = None
    try:
        user_memory = db.get_user_memory(user_id)
    except Exception:
        pass

    # 8. Generate response
    response = generate_response(question, intent, filtered_results, user_memory, need_outreach)

    # 9. Format results for API response
    formatted_results = [
        ResultItem(
            type=r["type"],
            id=r["id"],
            name=r["name"],
            match_reason=r.get("text", "")[:100],
            confidence=round(r.get("score", 0), 2),
        )
        for r in filtered_results
    ]

    # 10. Build sources
    sources = [
        SourceItem(type=r["type"], id=r["id"], detail=r["name"])
        for r in filtered_results[:5]
    ]

    payload_data = None
    if not need_outreach and intent.type in ["find_people", "find_info", "find_event", "find_org"]:
        payload_data = build_results_payload(filtered_results)

    # Persist Link response + cards into link_messages (best-effort)
    try:
        convo = db.get_or_create_link_conversation(user_id)
        if convo and response and response.message:
            link_profile = db.get_link_system_profile(university_id)
            sender_id = link_profile.get("link_user_id") if link_profile else None
            session = None
            if session_id:
                session = db.get_link_session_for_user(session_id, user_id)
            if not session:
                session = db.get_or_create_link_session(user_id, university_id)

            if session:
                db.set_link_conversation_session(convo["id"], session["id"])

            db.insert_link_message(
                convo["id"],
                sender_id,
                response.message,
                {"shareType": "text"},
                session_id=session["id"] if session else None,
            )

            if payload_data and payload_data.get("results") and not need_outreach:
                for item in payload_data["results"]:
                    item_type = item.get("type")
                    metadata = build_card_metadata(item, item_type)
                    if metadata:
                        title = item.get("name") or item.get("title") or "Shared item"
                        db.insert_link_message(
                            convo["id"],
                            sender_id,
                            title,
                            metadata,
                            session_id=session["id"] if session else None,
                        )
    except Exception:
        pass

    # Update user memory (best-effort)
    memory_updated = False
    try:
        if user_memory is None:
            user_memory = {}
        total_interactions = int(user_memory.get("total_interactions") or 0) + 1
        questions_asked = int(user_memory.get("questions_asked") or 0)
        if intent.type in ["find_people", "find_info", "find_event", "find_org"]:
            questions_asked += 1

        known_preferences = user_memory.get("known_preferences") or {}
        likes = set(known_preferences.get("likes") or [])
        for pref in extract_preferences(question):
            likes.add(pref)
        if likes:
            known_preferences["likes"] = sorted(likes)

        memory_payload = {
            "university_id": university_id,
            "last_interaction_at": "now()",
            "total_interactions": total_interactions,
            "questions_asked": questions_asked,
            "conversation_context": {
                "last_intent": intent.type,
                "last_entities": intent.entities,
            },
            "known_preferences": known_preferences,
        }
        db.upsert_user_memory(user_id, memory_payload)
        memory_updated = True
    except Exception:
        memory_updated = False

    return {
        "intent": intent,
        "response": response,
        "results": formatted_results,
        "data": payload_data,
        "session_id": session["id"] if "session" in locals() and session else None,
        "need_outreach": need_outreach,
        "outreach_request_id": None,
        "validation": validation,
        "sources": sources,
        "memory_updated": memory_updated,
        "journal_entry_created": False,
    }
