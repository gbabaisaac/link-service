import random
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional
import supabase_client as db


JITTER_MINUTES = 45

# Pattern scan times (in local hours, will be converted to UTC)
PATTERN_SCAN_HOURS = {
    "pattern_scan_3am": 3,
    "pattern_scan_9am": 9,
    "pattern_scan_3pm": 15,
    "pattern_scan_9pm": 21,
}


def _apply_jitter(run_at: datetime, jitter_minutes: int = JITTER_MINUTES) -> datetime:
    jitter = random.randint(-jitter_minutes, jitter_minutes)
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


def schedule_pattern_scan(user_id: str, scan_type: str, run_at: Optional[datetime] = None) -> dict:
    """
    Schedule a pattern detection scan for a user.

    Args:
        user_id: The user to scan
        scan_type: One of 'pattern_scan_3am', 'pattern_scan_9am', 'pattern_scan_3pm', 'pattern_scan_9pm'
        run_at: Optional specific time, defaults to next occurrence of the scan hour
    """
    if scan_type not in PATTERN_SCAN_HOURS:
        raise ValueError(f"Invalid scan_type: {scan_type}. Must be one of {list(PATTERN_SCAN_HOURS.keys())}")

    if run_at is None:
        # Calculate next occurrence of the scan hour
        now = datetime.now(timezone.utc)
        target_hour = PATTERN_SCAN_HOURS[scan_type]
        run_at = now.replace(hour=target_hour, minute=0, second=0, microsecond=0)
        if run_at <= now:
            run_at += timedelta(days=1)

    # Apply smaller jitter for pattern scans (15 min)
    safe_run_at = _apply_jitter(run_at, jitter_minutes=15)

    job_payload = {
        "user_id": user_id,
        "run_at": safe_run_at.astimezone(timezone.utc).isoformat(),
        "job_type": scan_type,
        "payload": {"scan_type": scan_type},
    }
    return db.create_scheduled_job(job_payload)


def schedule_wellness_check(user_id: str, run_at: Optional[datetime] = None) -> dict:
    """Schedule a wellness monitoring check."""
    if run_at is None:
        # Default to next 9am
        now = datetime.now(timezone.utc)
        run_at = now.replace(hour=9, minute=0, second=0, microsecond=0)
        if run_at <= now:
            run_at += timedelta(days=1)

    safe_run_at = _apply_jitter(run_at, jitter_minutes=30)

    job_payload = {
        "user_id": user_id,
        "run_at": safe_run_at.astimezone(timezone.utc).isoformat(),
        "job_type": "wellness_check",
        "payload": {},
    }
    return db.create_scheduled_job(job_payload)


def schedule_daily_pattern_scans(user_ids: List[str]) -> List[dict]:
    """
    Schedule all daily pattern scans for a list of users.
    Typically called by a daily cron job.
    """
    jobs_created = []

    for user_id in user_ids:
        for scan_type in PATTERN_SCAN_HOURS.keys():
            try:
                job = schedule_pattern_scan(user_id, scan_type)
                jobs_created.append(job)
            except Exception as e:
                print(f"Failed to schedule {scan_type} for {user_id}: {e}")

    return jobs_created


def schedule_class_reminder(user_id: str, class_name: str, class_time: datetime) -> dict:
    """Schedule a reminder before a class."""
    # Remind 30 minutes before class
    reminder_time = class_time - timedelta(minutes=30)
    safe_run_at = _apply_jitter(reminder_time, jitter_minutes=5)

    job_payload = {
        "user_id": user_id,
        "run_at": safe_run_at.astimezone(timezone.utc).isoformat(),
        "job_type": "class_reminder",
        "payload": {
            "class_name": class_name,
            "class_time": class_time.isoformat(),
        },
    }
    return db.create_scheduled_job(job_payload)


def schedule_study_reminder(user_id: str, subject: str, run_at: datetime) -> dict:
    """Schedule a study reminder."""
    safe_run_at = _apply_jitter(run_at, jitter_minutes=15)

    job_payload = {
        "user_id": user_id,
        "run_at": safe_run_at.astimezone(timezone.utc).isoformat(),
        "job_type": "study_reminder",
        "payload": {"subject": subject},
    }
    return db.create_scheduled_job(job_payload)


# ============ Memory Consolidation Jobs ============

def schedule_memory_consolidation_daily(user_ids: List[str]) -> List[dict]:
    """
    Schedule daily memory consolidation (short-term -> medium-term).
    Runs at 2:00 AM for each user.
    """
    jobs = []
    now = datetime.now(timezone.utc)

    # Calculate next 2:00 AM
    next_2am = now.replace(hour=2, minute=0, second=0, microsecond=0)
    if next_2am <= now:
        next_2am += timedelta(days=1)

    for user_id in user_ids:
        # Add small per-user jitter to spread load
        user_run_at = _apply_jitter(next_2am, jitter_minutes=30)

        job_payload = {
            "user_id": user_id,
            "run_at": user_run_at.astimezone(timezone.utc).isoformat(),
            "job_type": "memory_consolidation_daily",
            "payload": {},
        }

        try:
            job = db.create_scheduled_job(job_payload)
            jobs.append(job)
        except Exception:
            pass

    return jobs


def schedule_memory_consolidation_weekly(user_ids: List[str]) -> List[dict]:
    """
    Schedule weekly memory consolidation (medium-term -> long-term).
    Runs on Sundays at 1:00 AM.
    """
    jobs = []
    now = datetime.now(timezone.utc)

    # Calculate next Sunday 1:00 AM
    days_until_sunday = (6 - now.weekday()) % 7
    if days_until_sunday == 0 and now.hour >= 1:
        days_until_sunday = 7

    next_sunday_1am = (now + timedelta(days=days_until_sunday)).replace(
        hour=1, minute=0, second=0, microsecond=0
    )

    for user_id in user_ids:
        user_run_at = _apply_jitter(next_sunday_1am, jitter_minutes=30)

        job_payload = {
            "user_id": user_id,
            "run_at": user_run_at.astimezone(timezone.utc).isoformat(),
            "job_type": "memory_consolidation_weekly",
            "payload": {},
        }

        try:
            job = db.create_scheduled_job(job_payload)
            jobs.append(job)
        except Exception:
            pass

    return jobs


def schedule_all_consolidation_jobs() -> Dict[str, int]:
    """
    Schedule all memory consolidation jobs for active users.
    Called by daily cron.
    """
    active_users = db.get_active_user_ids(since_days=30)

    daily_jobs = schedule_memory_consolidation_daily(active_users)
    weekly_jobs = schedule_memory_consolidation_weekly(active_users)

    return {
        "daily_jobs_scheduled": len(daily_jobs),
        "weekly_jobs_scheduled": len(weekly_jobs),
        "total_users": len(active_users),
    }
