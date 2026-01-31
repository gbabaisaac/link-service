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
    if settings.LLM_PROVIDER == "gemini":
        import google.generativeai as genai
        genai.configure(api_key=settings.GOOGLE_API_KEY)
        # Request JSON output
        model = genai.GenerativeModel(
            "gemini-1.5-flash",
            generation_config={"response_mime_type": "application/json", "temperature": temperature},
        )
        resp = model.generate_content(prompt)
        text = getattr(resp, "text", None) or (resp.candidates[0].content.parts[0].text if resp.candidates else "{}")
        try:
            return json.loads(text or "{}")
        except Exception:
            return {}
    else:
        from openai import OpenAI
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=temperature,
        )
        try:
            return json.loads(resp.choices[0].message.content or "{}")
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


def parse_intent(question: str, conversation_history: list[dict] = None) -> Intent:
    """Parse user question into structured intent using LLM or simple patterns in TEST_MODE."""
    if settings.TEST_MODE:
        q = question.lower()
        if any(p in q for p in ("looking for", "who plays", "partners", "anyone who")):
            return Intent(type="find_people", entities=[], filters={})
        if any(p in q for p in ("where", "what time", "how do i")):
            return Intent(type="find_info", entities=[], filters={})
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
        return Intent(
            type=result.get("type", "general_question"),
            entities=result.get("entities", []),
            filters=result.get("filters", {}),
        )
    except (json.JSONDecodeError, KeyError):
        # Fallback to pattern matching
        question_lower = question.lower()
        for intent_type, patterns in INTENT_PATTERNS.items():
            if any(p in question_lower for p in patterns):
                return Intent(type=intent_type, entities=[], filters={})
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


# ============ Main Query Processing ============

def process_query(
    user_id: str,
    university_id: str,
    question: str,
    conversation_history: list[dict] = None,
) -> dict:
    """Main query processing pipeline."""
    # 1. Parse intent
    intent = parse_intent(question, conversation_history)

    # 2. Retrieve relevant documents
    search_query = question
    if intent.entities:
        search_query = f"{question} {' '.join(intent.entities)}"

    results = rag_index.retrieve(search_query, top_k=5, university_id=university_id)

    # 3. Separate facts from other results
    facts = [r for r in results if r["type"] == "link_fact"]

    # 4. Calculate confidence
    validation = calculate_confidence(results, facts, intent)

    # 5. Determine if outreach is needed
    need_outreach = (
        validation.system_confidence < settings.CONFIDENCE_THRESHOLD
        and intent.type in ["find_people", "find_info"]
    )

    # 6. Get user memory for style
    user_memory = None
    try:
        user_memory = db.get_user_memory(user_id)
    except Exception:
        pass

    # 7. Generate response
    response = generate_response(question, intent, results, user_memory, need_outreach)

    # 8. Format results for API response
    formatted_results = [
        ResultItem(
            type=r["type"],
            id=r["id"],
            name=r["name"],
            match_reason=r.get("text", "")[:100],
            confidence=round(r.get("score", 0), 2),
        )
        for r in results
    ]

    # 9. Build sources
    sources = [
        SourceItem(type=r["type"], id=r["id"], detail=r["name"])
        for r in results[:5]
    ]

    return {
        "intent": intent,
        "response": response,
        "results": formatted_results,
        "need_outreach": need_outreach,
        "outreach_request_id": None,
        "validation": validation,
        "sources": sources,
        "memory_updated": False,
        "journal_entry_created": False,
    }
