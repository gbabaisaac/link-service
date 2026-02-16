import time
import signal
import sys
from datetime import datetime, timezone
import supabase_client as db
from link_instance import LinkInstance

# --- Configuration ---
POLL_INTERVAL_SECONDS = 60
MAX_JOBS_PER_BATCH = 50

# Job types that are handled by pattern detection
PATTERN_JOB_TYPES = {
    "pattern_scan_3am",
    "pattern_scan_9am",
    "pattern_scan_3pm",
    "pattern_scan_9pm",
}

# Job types for memory consolidation
MEMORY_JOB_TYPES = {
    "memory_consolidation_daily",
    "memory_consolidation_weekly",
}


def handle_pattern_scan(user_id: str, job_type: str) -> None:
    """Handle pattern detection jobs."""
    from pattern_detector import pattern_detector

    if job_type == "pattern_scan_3am":
        # Sleep pattern analysis
        pattern = pattern_detector.analyze_sleep_patterns(user_id)
        if pattern["confidence"] > 0.3:
            pattern_detector.save_pattern(user_id, pattern)

    elif job_type == "pattern_scan_9am":
        # Morning routine / activity patterns
        pattern = pattern_detector.analyze_activity_patterns(user_id)
        if pattern["confidence"] > 0.3:
            pattern_detector.save_pattern(user_id, pattern)

        # Also check for routine changes
        changes = pattern_detector.detect_routine_changes(user_id)
        for change in changes:
            if change.get("severity") in ("high", "moderate"):
                # Could trigger a wellness signal here
                pass

    elif job_type == "pattern_scan_3pm":
        # Academic patterns
        pattern = pattern_detector.analyze_academic_patterns(user_id)
        if pattern["confidence"] > 0.3:
            pattern_detector.save_pattern(user_id, pattern)

    elif job_type == "pattern_scan_9pm":
        # Social/evening patterns
        pattern = pattern_detector.analyze_social_patterns(user_id)
        if pattern["confidence"] > 0.3:
            pattern_detector.save_pattern(user_id, pattern)


def handle_memory_consolidation(user_id: str, job_type: str) -> None:
    """Handle memory consolidation jobs."""
    from tiered_memory import get_tiered_memory_manager

    manager = get_tiered_memory_manager(user_id)

    if job_type == "memory_consolidation_daily":
        # Short-term -> Medium-term consolidation (runs at 2am)
        result = manager.consolidate_short_to_medium()
        print(f"[{datetime.now()}] Daily consolidation for {user_id}: "
              f"{result['promoted']} promoted, {result['discarded']} discarded")

    elif job_type == "memory_consolidation_weekly":
        # Medium-term -> Long-term consolidation (runs Sundays at 1am)
        result = manager.consolidate_medium_to_long()
        print(f"[{datetime.now()}] Weekly consolidation for {user_id}: "
              f"{result['promoted']} promoted, {result['condensed']} condensed")


def handle_wellness_check(user_id: str) -> None:
    """Handle wellness monitoring jobs."""
    from wellness_monitor import wellness_monitor

    # Check for wellness signals
    signals = wellness_monitor.run_wellness_check(user_id)

    for signal in signals:
        if signal.get("should_trigger_checkin"):
            # Schedule a check-in based on the wellness signal
            from link_scheduler import schedule_checkin
            from datetime import timedelta

            run_at = datetime.now(timezone.utc) + timedelta(hours=2)
            schedule_checkin(user_id, run_at, {
                "event_type": "wellness_checkin",
                "context": signal.get("reason", "checking in"),
            })


def handle_jobs():
    """Fetch and process pending jobs."""
    try:
        jobs = db.list_pending_jobs(limit=MAX_JOBS_PER_BATCH)
        if not jobs:
            return

        print(f"[{datetime.now()}] Found {len(jobs)} pending jobs.")

        for job in jobs:
            try:
                # 1. Mark as processing
                db.update_job_status(job["id"], "processing")

                user_id = job["user_id"]
                job_type = job.get("job_type")

                # 2. Route to appropriate handler
                if job_type in PATTERN_JOB_TYPES:
                    handle_pattern_scan(user_id, job_type)
                elif job_type in MEMORY_JOB_TYPES:
                    handle_memory_consolidation(user_id, job_type)
                elif job_type == "wellness_check":
                    handle_wellness_check(user_id)
                else:
                    # Default: Use LinkInstance for check_in and other jobs
                    instance = LinkInstance(user_id)
                    instance.run_scheduled_job(job)

                # 3. Mark Complete
                db.update_job_status(job["id"], "completed")
                print(f"[{datetime.now()}] Completed job {job['id']} ({job_type}) for user {user_id}")

            except Exception as e:
                print(f"[{datetime.now()}] FAILED job {job['id']}: {e}")
                db.update_job_status(job["id"], "failed")

    except Exception as e:
        print(f"[{datetime.now()}] Worker Error: {e}")

def run_worker():
    """Main loop."""
    print(f"[{datetime.now()}] Link Scheduler Worker Started.")
    print(f"Polling every {POLL_INTERVAL_SECONDS} seconds...")
    
    while True:
        handle_jobs()
        time.sleep(POLL_INTERVAL_SECONDS)

# Graceful Shutdown
def signal_handler(sig, frame):
    print('Stopping worker...')
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    run_worker()
