"""RAG indexing and retrieval for Link AI using LlamaIndex."""

import os
from typing import Optional

from llama_index.core import Document, VectorStoreIndex, Settings

from config import settings as app_settings
import supabase_client as db

# Global index instance
_index: Optional[VectorStoreIndex] = None
_is_indexed: bool = False

# In TEST_MODE (or when no API key) we skip building a real index

def _use_test_mode() -> bool:
    # Read env directly to avoid stale settings during server import
    provider = os.getenv("LLM_PROVIDER", "openai").lower()
    if os.getenv("TEST_MODE", "false").lower() == "true":
        return True
    if provider == "gemini":
        return not bool(os.getenv("GOOGLE_API_KEY", ""))
    return not bool(os.getenv("OPENAI_API_KEY", ""))


def _init_llama_settings():
    """Initialize LlamaIndex settings with selected provider."""
    if app_settings.LLM_PROVIDER == "gemini":
        # Gemini provider (custom embedder to avoid package version mismatch)
        os.environ["GOOGLE_API_KEY"] = app_settings.GOOGLE_API_KEY
        from gemini_embedder import GeminiEmbedder
        Settings.embed_model = GeminiEmbedder(model_name="text-embedding-004")
        # LLM not required for retrieval/indexing; link_logic handles LLM calls.
    else:
        # OpenAI provider (default)
        os.environ["OPENAI_API_KEY"] = app_settings.OPENAI_API_KEY
        from llama_index.llms.openai import OpenAI
        from llama_index.embeddings.openai import OpenAIEmbedding
        Settings.llm = OpenAI(model="gpt-4o-mini", temperature=0)
        Settings.embed_model = OpenAIEmbedding(model="text-embedding-3-small")


# ============ Document Creators ============

def create_profile_document(profile: dict) -> Document:
    """Convert profile to searchable document."""
    interests = profile.get("interests") or []
    if isinstance(interests, str):
        interests = [interests]
    tags = profile.get("personality_tags") or []
    if isinstance(tags, str):
        tags = [tags]

    text = f"""
Student: {profile.get('full_name', 'Unknown')} (@{profile.get('username', 'unknown')})
Major: {profile.get('major', 'Undeclared')}
Year: {profile.get('grade', 'Unknown')}
Bio: {profile.get('bio', '')}
Interests: {', '.join(interests) if interests else 'Not specified'}
Personality: {', '.join(tags) if tags else 'Not specified'}
""".strip()

    return Document(
        text=text,
        metadata={
            "type": "profile",
            "id": profile.get("id", ""),
            "university_id": profile.get("university_id", ""),
            "name": profile.get("full_name", "Unknown"),
            "interests": interests,
            "major": profile.get("major"),
        },
    )


def create_org_document(org: dict) -> Document:
    """Convert organization to searchable document."""
    text = f"""
Organization: {org.get('name', 'Unknown')}
Category: {org.get('category', 'General')}
Mission: {org.get('mission_statement', '')}
Meeting Time: {org.get('meeting_time', 'TBD')}
Meeting Place: {org.get('meeting_place', 'TBD')}
""".strip()

    return Document(
        text=text,
        metadata={
            "type": "organization",
            "id": org.get("id", ""),
            "university_id": org.get("university_id", ""),
            "name": org.get("name", "Unknown"),
            "category": org.get("category"),
        },
    )


def create_event_document(event: dict) -> Document:
    """Convert event to searchable document."""
    text = f"""
Event: {event.get('title', 'Unknown Event')}
Type: {event.get('type', 'General')}
Description: {event.get('description', '')}
Date/Time: {event.get('start_at', 'TBD')}
Location: {event.get('location_name', 'TBD')}
""".strip()

    return Document(
        text=text,
        metadata={
            "type": "event",
            "id": event.get("id", ""),
            "university_id": event.get("university_id", ""),
            "name": event.get("title", "Unknown Event"),
            "event_type": event.get("type"),
        },
    )


def create_fact_document(fact: dict) -> Document:
    """Convert Link fact to searchable document."""
    text = f"""
Verified Fact ({fact.get('consent_status', 'unknown')}):
Category: {fact.get('fact_category', 'general')}
{fact.get('fact_key', 'info')}: {fact.get('fact_value', '')}
Confidence: {fact.get('confidence_score', 0)}
""".strip()

    return Document(
        text=text,
        metadata={
            "type": "link_fact",
            "id": fact.get("id", ""),
            "entity_type": fact.get("entity_type"),
            "entity_id": fact.get("entity_id"),
            "university_id": fact.get("university_id", ""),
            "category": fact.get("fact_category"),
            "consent": fact.get("consent_status"),
            "confidence": fact.get("confidence_score", 0),
        },
    )


def create_post_document(post: dict) -> Document:
    """Convert forum post to searchable document."""
    forum = post.get("forums") or {}
    text = f"""
Post: {post.get('title', 'Untitled')}
Forum: {forum.get('name', 'Forum')}
Body: {post.get('body', '')}
Tags: {', '.join(post.get('tags') or [])}
""".strip()

    return Document(
        text=text,
        metadata={
            "type": "post",
            "id": post.get("id", ""),
            "forum_id": post.get("forum_id", ""),
            "forum_name": forum.get("name"),
            "university_id": forum.get("university_id"),
            "name": post.get("title", "Post"),
        },
    )


# ============ Index Management ============

def build_index(university_id: Optional[str] = None) -> dict:
    """Build or rebuild the RAG index from Supabase data."""
    global _index, _is_indexed

    if _use_test_mode():
        _index = None
        _is_indexed = True
        return {"profiles": 0, "organizations": 0, "events": 0, "link_facts": 0}

    _init_llama_settings()

    documents = []
    counts = {"profiles": 0, "organizations": 0, "events": 0, "link_facts": 0, "posts": 0}

    # Load profiles
    try:
        profiles = db.get_profiles(university_id)
        for p in profiles:
            documents.append(create_profile_document(p))
            counts["profiles"] += 1
    except Exception as e:
        print(f"Warning: Could not load profiles: {e}")

    # Load organizations
    try:
        orgs = db.get_organizations(university_id)
        for o in orgs:
            documents.append(create_org_document(o))
            counts["organizations"] += 1
    except Exception as e:
        print(f"Warning: Could not load organizations: {e}")

    # Load upcoming events
    try:
        events = db.get_upcoming_events(university_id)
        for e in events:
            documents.append(create_event_document(e))
            counts["events"] += 1
    except Exception as e:
        print(f"Warning: Could not load events: {e}")

    # Load verified facts
    try:
        facts = db.get_link_facts(university_id, consent_only=True)
        for f in facts:
            documents.append(create_fact_document(f))
            counts["link_facts"] += 1
    except Exception as e:
        print(f"Warning: Could not load link_facts: {e}")

    # Load public forum posts
    try:
        posts = db.get_posts(university_id)
        for p in posts:
            documents.append(create_post_document(p))
            counts["posts"] += 1
    except Exception as e:
        print(f"Warning: Could not load posts: {e}")

    # Build the vector index
    if documents:
        _index = VectorStoreIndex.from_documents(documents)
        _is_indexed = True
    else:
        # Create empty index
        _index = VectorStoreIndex.from_documents([Document(text="No data available")])
        _is_indexed = True

    return counts


def get_index() -> Optional[VectorStoreIndex]:
    """Get the RAG index, building if necessary."""
    global _index, _is_indexed
    if _index is None and not _use_test_mode():
        build_index()
    return _index


def is_indexed() -> bool:
    """Check if the index has been built."""
    return _is_indexed


# ============ Retrieval ============

def retrieve(query: str, top_k: int = 5, university_id: Optional[str] = None) -> list[dict]:
    """Retrieve relevant documents for a query."""
    if _use_test_mode():
        # Return empty results in test mode
        return []

    index = get_index()
    retriever = index.as_retriever(similarity_top_k=top_k)

    nodes = retriever.retrieve(query)

    results = []
    for node in nodes:
        meta = node.metadata
        # Filter by university if specified
        if university_id and meta.get("university_id") != university_id:
            continue

        results.append(
            {
                "type": meta.get("type", "unknown"),
                "id": meta.get("id", ""),
                "name": meta.get("name", "Unknown"),
                "score": node.score,
                "text": node.text[:200],
                "metadata": meta,
            }
        )

    return results


def retrieve_dual(query: str, top_k: int = 5) -> tuple[list[dict], list[dict], float]:
    """Perform dual retrieval for confidence scoring (agreement check)."""
    if _use_test_mode():
        return [], [], 1.0

    # First retrieval with default settings
    results_1 = retrieve(query, top_k)

    # Second retrieval (in production, could use different temperature)
    # For simplicity, we do the same retrieval - real impl would vary params
    results_2 = retrieve(query, top_k)

    # Calculate Jaccard similarity
    ids_1 = {r["id"] for r in results_1}
    ids_2 = {r["id"] for r in results_2}

    if not ids_1 and not ids_2:
        agreement = 1.0
    elif not ids_1 or not ids_2:
        agreement = 0.0
    else:
        intersection = len(ids_1 & ids_2)
        union = len(ids_1 | ids_2)
        agreement = intersection / union if union > 0 else 0.0

    return results_1, results_2, agreement


# ============ CLI Entry Point ============

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "rebuild":
        print("Rebuilding RAG index...")
        counts = build_index()
        print(f"Indexed: {counts}")
    else:
        print("Usage: python -m rag_index rebuild")
