import random
from datetime import datetime, timedelta, timezone
from typing import Dict, Any
import supabase_client as db


JITTER_MINUTES = 45


def _apply_jitter(run_at: datetime) -> datetime:
    jitter = random.randint(-JITTER_MINUTES, JITTER_MINUTES)
    return run_at + timedelta(minutes=jitter)


def schedule_checkin(user_id: str, run_at: datetime, payload: Dict[str, Any]) -> dict:
    safe_run_at = _apply_jitter(run_at)
    job_payload = {
        "user_id": user_id,
        "run_at": safe_run_at.astimezone(timezone.utc).isoformat(),
        "job_type": "check_in",
        "payload": payload,
    }
    return db.create_scheduled_job(job_payload)
