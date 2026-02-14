from typing import Dict, Any, Optional
import supabase_client as db
from sanitizer_logic import sanitize_text, build_public_tags

from datetime import datetime, timedelta, timezone
from sensitive_guard import is_sensitive

MAX_ORDERS_PER_HOUR = 5

def create_work_order(
    requester_user_id: str,
    conversation_id: Optional[str],
    message: str,
    intent: str,
    user_context: Dict[str, Any],
) -> dict:
    # 1. Sensitive Content Guard
    if is_sensitive(message):
        return {"error": "sensitive_content_blocked", "message": "I can't help with inquiries about sensitive private info."}

    # 2. Rate Limiting
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=1)
    # Note: count_recent_work_orders must use the service client (Vault access)
    recent_count = db.count_recent_work_orders(requester_user_id, since)
    if recent_count >= MAX_ORDERS_PER_HOUR:
        return {"error": "rate_limit_exceeded", "message": "Slow down! You've reached your outreach limit for the hour."}

    profile = user_context.get("profile") or {}
    known_pii = [
        profile.get("full_name"),
        profile.get("email"),
        profile.get("username"),
        profile.get("phone"),
    ]
    sanitized = sanitize_text(message, known_pii=known_pii)
    tags = build_public_tags(user_context)
    university_id = profile.get("university_id")
    
    payload = {
        "university_id": university_id,
        "intent": intent,
        "query": sanitized,
        "public_tags": tags,
        "status": "pending",
    }
    work_order = db.create_work_order(payload)
    db.create_work_order_map(
        {
            "work_order_id": work_order["id"],
            "requester_user_id": requester_user_id,
            "conversation_id": conversation_id,
        }
    )
    return work_order
