"""Supabase client and data access functions for Link AI."""

from typing import Optional
from datetime import datetime, timezone
from supabase import create_client, Client
from config import settings

_client: Optional[Client] = None
_rls_clients: dict[str, Client] = {}


def get_supabase_client() -> Client:
    """Get or create Supabase client singleton."""
    global _client
    if _client is None:
        if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_KEY:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
        _client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
    return _client


def get_supabase_client_for_user(access_token: str) -> Client:
    """Create a Supabase client that enforces RLS for a user."""
    if not access_token:
        return get_supabase_client()
    cached = _rls_clients.get(access_token)
    if cached:
        return cached
    if not settings.SUPABASE_URL or not settings.SUPABASE_ANON_KEY:
        raise RuntimeError("SUPABASE_URL and SUPABASE_ANON_KEY must be set for RLS client")
    client = create_client(
        settings.SUPABASE_URL,
        settings.SUPABASE_ANON_KEY,
        options={"global": {"headers": {"Authorization": f"Bearer {access_token}"}}},
    )
    _rls_clients[access_token] = client
    return client


# ============ Profile Functions ============

def get_profiles(university_id: Optional[str] = None, limit: int = 500) -> list[dict]:
    """Fetch profiles, optionally filtered by university."""
    client = get_supabase_client()
    query = client.table("profiles").select("*")
    if university_id:
        query = query.eq("university_id", university_id)
    # Only include visible, non-Link profiles
    query = (
        query
        .neq("is_link", True)
        .in_("friends_visibility", ["school", "public"])
        .eq("yearbook_visible", True)
    )
    return query.limit(limit).execute().data


def get_profiles_rls(access_token: str, university_id: Optional[str] = None, limit: int = 500) -> list[dict]:
    """Fetch profiles using RLS for a user."""
    client = get_supabase_client_for_user(access_token)
    query = client.table("profiles").select("*")
    if university_id:
        query = query.eq("university_id", university_id)
    return query.limit(limit).execute().data


def get_profile(user_id: str, enforce_public: bool = True) -> Optional[dict]:
    """Fetch a single profile by user ID."""
    client = get_supabase_client()
    query = client.table("profiles").select("*").eq("id", user_id)
    if enforce_public:
        query = (
            query
            .neq("is_link", True)
            .in_("friends_visibility", ["school", "public"])
            .eq("yearbook_visible", True)
        )
    result = query.execute()
    return result.data[0] if result.data else None


def get_profile_rls(access_token: str, user_id: str) -> Optional[dict]:
    """Fetch a single profile by user ID using RLS."""
    client = get_supabase_client_for_user(access_token)
    result = client.table("profiles").select("*").eq("id", user_id).maybe_single().execute()
    return result.data if result.data else None


def get_link_system_profile(university_id: str) -> Optional[dict]:
    """Fetch Link system profile for a university."""
    client = get_supabase_client()
    result = (
        client.table("link_system_profile")
        .select("*")
        .eq("university_id", university_id)
        .maybe_single()
        .execute()
    )
    if result.data:
        return result.data
    return None


# ============ Organization Functions ============

def get_organizations(university_id: Optional[str] = None, limit: int = 200) -> list[dict]:
    """Fetch organizations, optionally filtered by university."""
    client = get_supabase_client()
    query = client.table("organizations").select("*").eq("is_public", True)
    if university_id:
        query = query.eq("university_id", university_id)
    return query.limit(limit).execute().data


def get_organizations_rls(access_token: str, university_id: Optional[str] = None, limit: int = 200) -> list[dict]:
    """Fetch organizations using RLS for a user."""
    client = get_supabase_client_for_user(access_token)
    query = client.table("organizations").select("*")
    if university_id:
        query = query.eq("university_id", university_id)
    return query.limit(limit).execute().data


def get_organizations_count(university_id: Optional[str] = None) -> int:
    """Get total count of organizations."""
    try:
        client = get_supabase_client()
        query = client.table("organizations").select("id", count="exact")
        if university_id:
            query = query.eq("university_id", university_id)
        result = query.execute()
        return result.count or 0
    except Exception:
        return 0


def get_organization(org_id: str) -> Optional[dict]:
    """Fetch a single public organization."""
    client = get_supabase_client()
    result = (
        client.table("organizations")
        .select("*")
        .eq("id", org_id)
        .eq("is_public", True)
        .execute()
    )
    return result.data[0] if result.data else None


# ============ Event Functions ============

def get_upcoming_events(university_id: Optional[str] = None, limit: int = 100) -> list[dict]:
    """Fetch upcoming events."""
    client = get_supabase_client()
    query = (
        client.table("events")
        .select("*")
        .gte("start_at", "now()")
        .in_("visibility", ["public", "school"])
    )
    if university_id:
        query = query.eq("university_id", university_id)
    return query.order("start_at").limit(limit).execute().data


def get_upcoming_events_rls(access_token: str, university_id: Optional[str] = None, limit: int = 100) -> list[dict]:
    """Fetch upcoming events using RLS for a user."""
    client = get_supabase_client_for_user(access_token)
    query = client.table("events").select("*").gte("start_at", "now()")
    if university_id:
        query = query.eq("university_id", university_id)
    return query.order("start_at").limit(limit).execute().data


def list_forums_rls(access_token: str, university_id: Optional[str] = None, limit: int = 50) -> list[dict]:
    """List forums using RLS for a user."""
    client = get_supabase_client_for_user(access_token)
    query = client.table("forums").select("*")
    if university_id:
        query = query.eq("university_id", university_id)
    return query.order("created_at", desc=False).limit(limit).execute().data


def create_post_rls(access_token: str, payload: dict) -> dict:
    """Create a forum post using RLS for a user."""
    client = get_supabase_client_for_user(access_token)
    return client.table("posts").insert(payload).execute().data[0]


def list_forum_comments_rls(
    access_token: str,
    post_id: str,
    after: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """List forum comments for a post using RLS for a user."""
    client = get_supabase_client_for_user(access_token)
    query = client.table("forum_comments").select("*").eq("post_id", post_id).is_("deleted_at", "null")
    if after:
        query = query.gt("created_at", after)
    return query.order("created_at", desc=False).limit(limit).execute().data


def get_events_count(university_id: Optional[str] = None) -> int:
    """Get total count of events."""
    try:
        client = get_supabase_client()
        query = client.table("events").select("id", count="exact")
        if university_id:
            query = query.eq("university_id", university_id)
        result = query.execute()
        return result.count or 0
    except Exception:
        return 0


def get_event(event_id: str) -> Optional[dict]:
    """Fetch a single event if it is broadly visible."""
    client = get_supabase_client()
    result = (
        client.table("events")
        .select("*")
        .eq("id", event_id)
        .in_("visibility", ["public", "school"])
        .execute()
    )
    return result.data[0] if result.data else None


# ============ Post Functions ============

def get_posts(university_id: Optional[str] = None, limit: int = 200) -> list[dict]:
    """Fetch posts from public forums."""
    client = get_supabase_client()
    query = (
        client.table("posts")
        .select("*, forums!inner(id, name, is_public, university_id)")
        .eq("forums.is_public", True)
        .is_("deleted_at", "null")
    )
    if university_id:
        query = query.eq("forums.university_id", university_id)
    return query.order("created_at", desc=True).limit(limit).execute().data


def get_post(post_id: str) -> Optional[dict]:
    """Fetch a single post from a public forum."""
    client = get_supabase_client()
    result = (
        client.table("posts")
        .select("*, forums!inner(id, name, is_public, university_id)")
        .eq("id", post_id)
        .eq("forums.is_public", True)
        .is_("deleted_at", "null")
        .execute()
    )
    return result.data[0] if result.data else None


# ============ Link Conversation/Message Functions ============

def get_or_create_link_conversation(user_id: str) -> Optional[dict]:
    """Get or create a Link conversation for the user via RPC."""
    client = get_supabase_client()
    result = client.rpc("get_or_create_link_conversation", {"p_user_id": user_id}).execute()
    conversation_id = result.data
    if not conversation_id:
        return None
    convo = (
        client.table("link_conversations")
        .select("*")
        .eq("id", conversation_id)
        .maybe_single()
        .execute()
    )
    return convo.data if convo.data else None


def get_or_create_link_session(user_id: str, university_id: Optional[str] = None) -> Optional[dict]:
    """Get or create an active Link session for the user."""
    client = get_supabase_client()
    existing = (
        client.table("link_user_sessions")
        .select("*")
        .eq("user_id", user_id)
        .eq("status", "active")
        .order("started_at", desc=True)
        .limit(1)
        .execute()
    )
    if existing.data:
        session = existing.data[0]
    else:
        payload = {"user_id": user_id, "status": "active"}
        if university_id:
            payload["university_id"] = university_id
        created = client.table("link_user_sessions").insert(payload).execute()
        session = created.data[0] if created.data else None

    if session:
        client.table("link_user_sessions").update({
            "last_active_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", session["id"]).execute()
    return session


def get_link_session_for_user(session_id: str, user_id: str) -> Optional[dict]:
    """Fetch a Link session and ensure it belongs to the user."""
    client = get_supabase_client()
    result = (
        client.table("link_user_sessions")
        .select("*")
        .eq("id", session_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    return result.data if result.data else None


def insert_link_message(
    conversation_id: str,
    sender_id: Optional[str],
    content: str,
    metadata: Optional[dict] = None,
    session_id: Optional[str] = None,
    sender_type: str = "link",
) -> Optional[dict]:
    """Insert a Link message into link_messages."""
    client = get_supabase_client()
    payload = {
        "conversation_id": conversation_id,
        "sender_type": sender_type,
        "sender_id": sender_id,
        "content": content,
        "metadata": metadata or {},
    }
    if session_id:
        payload["session_id"] = session_id
    result = client.table("link_messages").insert(payload).execute()
    return result.data[0] if result.data else None


def set_link_conversation_session(conversation_id: str, session_id: str) -> None:
    """Attach a Link session to a conversation."""
    client = get_supabase_client()
    client.table("link_conversations").update({
        "session_id": session_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", conversation_id).execute()


# ============ Link Outreach (Runs/Targets) ============

def create_link_outreach_run(payload: dict) -> dict:
    """Create a link outreach run."""
    client = get_supabase_client()
    return client.table("link_outreach_runs").insert(payload).execute().data[0]


def get_link_outreach_run(run_id: str) -> Optional[dict]:
    """Fetch a link outreach run by ID."""
    client = get_supabase_client()
    result = client.table("link_outreach_runs").select("*").eq("id", run_id).maybe_single().execute()
    return result.data if result.data else None


def update_link_outreach_run(run_id: str, payload: dict) -> Optional[dict]:
    """Update a link outreach run."""
    client = get_supabase_client()
    result = client.table("link_outreach_runs").update(payload).eq("id", run_id).execute()
    return result.data[0] if result.data else None


def create_link_outreach_targets(rows: list[dict]) -> list[dict]:
    """Create link outreach target rows in bulk."""
    if not rows:
        return []
    client = get_supabase_client()
    return client.table("link_outreach_targets").insert(rows).execute().data


def list_link_outreach_targets(run_id: str) -> list[dict]:
    """List outreach targets for a run."""
    client = get_supabase_client()
    return (
        client.table("link_outreach_targets")
        .select("*")
        .eq("run_id", run_id)
        .order("sent_at", desc=False)
        .execute()
        .data
    )


def update_link_outreach_target(target_id: str, payload: dict) -> Optional[dict]:
    """Update a link outreach target row."""
    client = get_supabase_client()
    result = client.table("link_outreach_targets").update(payload).eq("id", target_id).execute()
    return result.data[0] if result.data else None


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


def get_link_facts_by_value(university_id: str, fact_value: str) -> list[dict]:
    """Fetch opt-in Link facts matching a fact_value."""
    client = get_supabase_client()
    return (
        client.table("link_facts")
        .select("*")
        .eq("university_id", university_id)
        .eq("consent_status", "opt_in")
        .ilike("fact_value", fact_value)
        .execute()
        .data
    )


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


# ============ Verified Facts Cache ============

def create_verified_fact(fact: dict) -> dict:
    """Create a verified fact cache entry."""
    client = get_supabase_client()
    return client.table("link_verified_facts").insert(fact).execute().data[0]


def get_verified_facts(university_id: str, tags: list[str], limit: int = 10) -> list[dict]:
    """Fetch verified facts that match any tag in fact_value."""
    client = get_supabase_client()
    query = client.table("link_verified_facts").select("*").eq("university_id", university_id)
    query = query.eq("consent_status", "opt_in")
    if tags:
        # Supabase doesn't support OR ilike easily; run sequentially and merge.
        results: list[dict] = []
        seen: set[str] = set()
        for tag in tags:
            if not tag:
                continue
            resp = query.ilike("fact_value", f"%{tag}%").limit(limit).execute().data
            for row in resp:
                row_id = row.get("id")
                if row_id and row_id not in seen:
                    results.append(row)
                    seen.add(row_id)
            if len(results) >= limit:
                break
        return results[:limit]
    return query.limit(limit).execute().data


def delete_expired_verified_facts(now_iso: str) -> int:
    """Delete expired verified facts, return count if available."""
    client = get_supabase_client()
    result = client.table("link_verified_facts").delete().lt("expires_at", now_iso).execute()
    return len(result.data or [])

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
    return client.table("link_user_memory").upsert(data, on_conflict="user_id").execute().data[0]


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


def create_outreach_message(message: dict) -> dict:
    """Create an outreach message record."""
    client = get_supabase_client()
    return client.table("link_outreach_messages").insert(message).execute().data[0]


def list_outreach_messages(request_id: str, target_user_id: Optional[str] = None) -> list[dict]:
    """List outreach messages for a request."""
    client = get_supabase_client()
    query = client.table("link_outreach_messages").select("*").eq("outreach_request_id", request_id)
    if target_user_id:
        query = query.eq("target_user_id", target_user_id)
    return query.order("created_at").execute().data


def update_outreach_message(message_id: str, data: dict) -> dict:
    """Update an outreach message record."""
    client = get_supabase_client()
    return client.table("link_outreach_messages").update(data).eq("id", message_id).execute().data[0]


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


def get_profile_by_username(username: str) -> Optional[dict]:
    """Fetch a profile by username."""
    client = get_supabase_client()
    result = client.table("profiles").select("*").eq("username", username).maybe_single().execute()
    return result.data if result.data else None


def get_profiles_by_ids(user_ids: list[str]) -> list[dict]:
    """Fetch profiles by a list of user IDs."""
    if not user_ids:
        return []
    client = get_supabase_client()
    return client.table("profiles").select("*").in_("id", user_ids).execute().data


def create_conversation(payload: dict) -> dict:
    """Create a conversation row."""
    client = get_supabase_client()
    return client.table("conversations").insert(payload).execute().data[0]


def add_conversation_participants(conversation_id: str, user_ids: list[str]) -> list[dict]:
    """Add participants to a conversation."""
    client = get_supabase_client()
    rows = [{"conversation_id": conversation_id, "user_id": uid} for uid in user_ids]
    return client.table("conversation_participants").insert(rows).execute().data


def insert_message(conversation_id: str, sender_id: str, content: str, metadata: Optional[dict] = None) -> dict:
    """Insert a message into a conversation."""
    client = get_supabase_client()
    payload = {
        "conversation_id": conversation_id,
        "sender_id": sender_id,
        "content": content,
        "metadata": metadata or {},
    }
    return client.table("messages").insert(payload).execute().data[0]


def list_messages_for_conversation(
    conversation_id: str,
    after: Optional[str] = None,
    sender_id: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """List messages in a conversation, optionally filtered by sender and time."""
    client = get_supabase_client()
    query = client.table("messages").select("*").eq("conversation_id", conversation_id)
    if sender_id:
        query = query.eq("sender_id", sender_id)
    if after:
        query = query.gt("created_at", after)
    return query.order("created_at", desc=False).limit(limit).execute().data


def get_or_create_dm_conversation(user_id: str, other_user_id: str) -> Optional[dict]:
    """Find or create a direct conversation between two users."""
    client = get_supabase_client()
    convo_ids = client.table("conversation_participants").select("conversation_id").eq("user_id", user_id).execute().data
    convo_ids = [row["conversation_id"] for row in convo_ids]

    if convo_ids:
        shared = (
            client.table("conversation_participants")
            .select("conversation_id")
            .eq("user_id", other_user_id)
            .in_("conversation_id", convo_ids)
            .execute()
            .data
        )
        shared_ids = [row["conversation_id"] for row in shared]
        if shared_ids:
            convo = (
                client.table("conversations")
                .select("*")
                .in_("id", shared_ids)
                .eq("type", "direct")
                .order("created_at", desc=True)
                .limit(1)
                .execute()
                .data
            )
            if convo:
                return convo[0]

    convo = create_conversation(
        {
            "type": "direct",
            "created_by": user_id,
            "is_system_generated": True,
        }
    )
    add_conversation_participants(convo["id"], [user_id, other_user_id])
    return convo


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
