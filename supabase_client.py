"""Supabase client and data access functions for Link AI."""

from typing import Optional
from supabase import create_client, Client
from config import settings

_client: Optional[Client] = None


def get_supabase_client() -> Client:
    """Get or create Supabase client singleton."""
    global _client
    if _client is None:
        if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_KEY:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
        _client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
    return _client


# ============ Profile Functions ============

def get_profiles(university_id: Optional[str] = None, limit: int = 500) -> list[dict]:
    """Fetch profiles, optionally filtered by university."""
    client = get_supabase_client()
    query = client.table("profiles").select("*")
    if university_id:
        query = query.eq("university_id", university_id)
    return query.limit(limit).execute().data


def get_profile(user_id: str) -> Optional[dict]:
    """Fetch a single profile by user ID."""
    client = get_supabase_client()
    result = client.table("profiles").select("*").eq("id", user_id).execute()
    return result.data[0] if result.data else None


# ============ Organization Functions ============

def get_organizations(university_id: Optional[str] = None, limit: int = 200) -> list[dict]:
    """Fetch organizations, optionally filtered by university."""
    client = get_supabase_client()
    query = client.table("organizations").select("*")
    if university_id:
        query = query.eq("university_id", university_id)
    return query.limit(limit).execute().data


# ============ Event Functions ============

def get_upcoming_events(university_id: Optional[str] = None, limit: int = 100) -> list[dict]:
    """Fetch upcoming events."""
    client = get_supabase_client()
    query = client.table("events").select("*").gte("start_at", "now()")
    if university_id:
        query = query.eq("university_id", university_id)
    return query.order("start_at").limit(limit).execute().data


# ============ Link Facts Functions ============

def get_link_facts(university_id: Optional[str] = None, consent_only: bool = True) -> list[dict]:
    """Fetch Link facts, optionally filtered."""
    client = get_supabase_client()
    query = client.table("link_facts").select("*")
    if consent_only:
        query = query.eq("consent_status", "opt_in")
    if university_id:
        query = query.eq("university_id", university_id)
    return query.execute().data


def get_facts_count() -> int:
    """Get total count of link_facts."""
    try:
        client = get_supabase_client()
        result = client.table("link_facts").select("id", count="exact").execute()
        return result.count or 0
    except Exception:
        return 0


def create_link_fact(fact: dict) -> dict:
    """Create a new link fact."""
    client = get_supabase_client()
    return client.table("link_facts").insert(fact).execute().data[0]


# ============ User Memory Functions ============

def get_user_memory(user_id: str) -> Optional[dict]:
    """Fetch user memory/style profile."""
    client = get_supabase_client()
    result = client.table("link_user_memory").select("*").eq("user_id", user_id).execute()
    return result.data[0] if result.data else None


def upsert_user_memory(user_id: str, data: dict) -> dict:
    """Create or update user memory."""
    client = get_supabase_client()
    data["user_id"] = user_id
    return client.table("link_user_memory").upsert(data).execute().data[0]


# ============ Journal Functions ============

def create_journal_entry(entry: dict) -> dict:
    """Create a journal entry."""
    client = get_supabase_client()
    return client.table("link_journal_entries").insert(entry).execute().data[0]


def get_journal_entries(user_id: str, limit: int = 10) -> list[dict]:
    """Get journal entries for a user."""
    client = get_supabase_client()
    return (
        client.table("link_journal_entries")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
        .data
    )


# ============ Outreach Functions ============

def create_outreach_request(request: dict) -> dict:
    """Create an outreach request."""
    client = get_supabase_client()
    return client.table("link_outreach_requests").insert(request).execute().data[0]


def get_outreach_request(request_id: str) -> Optional[dict]:
    """Fetch an outreach request by ID."""
    client = get_supabase_client()
    result = client.table("link_outreach_requests").select("*").eq("id", request_id).execute()
    return result.data[0] if result.data else None


def update_outreach_request(request_id: str, data: dict) -> dict:
    """Update an outreach request."""
    client = get_supabase_client()
    return client.table("link_outreach_requests").update(data).eq("id", request_id).execute().data[0]


# ============ Connection Functions ============

def create_connection(connection: dict) -> dict:
    """Create a connection record."""
    client = get_supabase_client()
    return client.table("link_connections").insert(connection).execute().data[0]


# ============ Friendships/Social Graph ============

def get_friends(user_id: str) -> list[str]:
    """Get friend IDs for a user."""
    client = get_supabase_client()
    result1 = client.table("friendships").select("user2_id").eq("user1_id", user_id).execute()
    result2 = client.table("friendships").select("user1_id").eq("user2_id", user_id).execute()
    friends = [r["user2_id"] for r in result1.data] + [r["user1_id"] for r in result2.data]
    return list(set(friends))


def get_classmates(user_id: str, semester: Optional[str] = None) -> list[str]:
    """Get classmate IDs for a user."""
    client = get_supabase_client()
    # Get user's classes
    query = client.table("user_class_enrollments").select("class_id").eq("user_id", user_id)
    if semester:
        query = query.eq("semester", semester)
    user_classes = query.execute().data
    class_ids = [c["class_id"] for c in user_classes]
    
    if not class_ids:
        return []
    
    # Get other students in those classes
    classmates = []
    for class_id in class_ids:
        result = client.table("user_class_enrollments").select("user_id").eq("class_id", class_id).execute()
        classmates.extend([r["user_id"] for r in result.data if r["user_id"] != user_id])
    
    return list(set(classmates))
