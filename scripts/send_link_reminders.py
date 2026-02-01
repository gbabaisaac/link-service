#!/usr/bin/env python3
"""
Run as a scheduled job (Railway cron or similar) to deliver pending Link reminders.
"""

from datetime import datetime, timedelta, timezone
from config import settings
import supabase_client as db
from link_logic import llm_json


def send_due_reminders(window_minutes: int = 2):
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(minutes=1)
    window_end = now + timedelta(minutes=window_minutes)
    reminders = db.list_due_link_reminders(window_start.isoformat(), window_end.isoformat())
    if not reminders:
        return
    link_profile_cache = {}
    for reminder in reminders:
        user_id = reminder.get("user_id")
        univ = reminder.get("university_id")
        convo = db.get_or_create_link_conversation(user_id)
        link_profile = link_profile_cache.get(univ)
        if link_profile is None:
            link_profile = db.get_link_system_profile(univ) if univ else {}
            link_profile_cache[univ] = link_profile
        sender_id = link_profile.get("link_user_id")
        message = reminder.get("message_text") or "hey, how’d that presentation go?"
        if sender_id and convo:
            db.insert_link_message(
                convo["id"],
                sender_id,
                message,
                {"shareType": "text", "reminder_id": reminder.get("id")},
            )
        db.mark_link_reminder_sent(reminder.get("id"), now.isoformat())


if __name__ == "__main__":
    send_due_reminders()
