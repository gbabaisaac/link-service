import re
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
import supabase_client as db

class LifeEventDetector:
    """
    Detects significant life events (Exams, Interviews, Dates) from user messages
    and schedules proactive follow-ups (The 'Socialite' Scheduler).
    """

    # Lightweight regex patterns for detection
    PATTERNS = [
        (r"i have an interview (on|at) (.*)", "interview"),
        (r"my interview is (on|at) (.*)", "interview"),
        (r"i have a (midterm|final|exam|test) (on|at) (.*)", "exam"),
        (r"my (midterm|final|exam|test) is (on|at) (.*)", "exam"),
        (r"i have a date (on|at) (.*)", "date"),
        (r"going on a date (on|at) (.*)", "date"),
        (r"presentation (on|at) (.*)", "speech"),
    ]

    def process_message(self, user_id: str, message: str) -> List[Dict[str, Any]]:
        """
        Scan message for events. If found, save to DB and schedule check-in.
        Returns list of detected events.
        """
        detected_events = []
        text = message.lower()

        for pattern, event_type in self.PATTERNS:
            match = re.search(pattern, text)
            if match:
                time_str = match.group(2).strip() # "friday", "tomorrow", "5pm"
                
                # In a real system, we'd use a robust NLP Date Parser (e.g. dateparser lib).
                # For this MVP, we will heuristic "tomorrow" or "today".
                target_date = self._parse_relative_time(time_str)
                
                if target_date:
                    event = self._register_event(user_id, event_type, target_date, message)
                    detected_events.append(event)
        
        return detected_events

    def _register_event(self, user_id: str, event_type: str, target_date: datetime, original_text: str) -> Dict[str, Any]:
        """Save event to DB and schedule the follow-up job."""
        
        # 1. Save valid event to Vault
        event_payload = {
            "user_id": user_id,
            "event_type": event_type,
            "target_date": target_date.isoformat(),
            "sentiment": "neutral", # improved by VibeMatcher later
            "status": "active",
            "check_in_scheduled": True
        }
        saved_event = db.create_life_event(event_payload)
        
        # 2. Schedule the 'Check In' Job
        # Rule: Check in 2 hours after the event (or next morning if late)
        # MVP Rule: Check in 4 hours after the target time
        run_at = target_date + timedelta(hours=4)
        
        job_payload = {
            "user_id": user_id,
            "run_at": run_at.isoformat(),
            "job_type": "check_in",
            "payload": {
                "event_id": saved_event["id"],
                "event_type": event_type,
                "context": original_text
            }
        }
        db.create_scheduled_job(job_payload)
        
        return saved_event

    def _parse_relative_time(self, time_str: str) -> Optional[datetime]:
        """Simple heuristic date parser for MVP."""
        now = datetime.now(timezone.utc)
        if "tomorrow" in time_str:
            return now + timedelta(days=1)
        if "tonight" in time_str or "today" in time_str:
            return now + timedelta(hours=4) # Assume event is soon
        if "friday" in time_str:
             # Calculate next friday
             days_ahead = 4 - now.weekday()
             if days_ahead <= 0: days_ahead += 7
             return now + timedelta(days=days_ahead)
        
        # Fallback: If we can't parse, don't schedule (avoid spam).
        return None

life_event_detector = LifeEventDetector()
