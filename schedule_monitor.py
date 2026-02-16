"""
Schedule Monitoring for Link AI.

Monitors user class schedules and triggers context-aware reminders:
- Morning class alerts
- Study session prompts
- Assignment due date reminders
"""

from __future__ import annotations
from datetime import datetime, timezone, timedelta, time
from typing import Dict, Any, List, Optional, Tuple
import supabase_client as db


class ScheduleMonitor:
    """
    Monitors user schedules and determines optimal times for reminders.
    Integrates with class schedules, study patterns, and user preferences.
    """

    # Default reminder lead times (in minutes)
    CLASS_REMINDER_LEAD = 30
    STUDY_REMINDER_LEAD = 60

    # Time windows for study reminders
    MORNING_STUDY_WINDOW = (time(8, 0), time(12, 0))
    AFTERNOON_STUDY_WINDOW = (time(14, 0), time(18, 0))
    EVENING_STUDY_WINDOW = (time(19, 0), time(22, 0))

    def get_next_class(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the user's next upcoming class.

        Returns:
            dict with class_name, start_time, location, or None
        """
        user_context = db.get_user_context(user_id)
        classes = user_context.get("classes", []) if user_context else []

        if not classes:
            return None

        now = datetime.now(timezone.utc)
        today_weekday = now.weekday()  # 0=Monday
        current_time = now.time()

        next_class = None
        min_delta = timedelta(days=8)  # Max lookahead

        for cls in classes:
            class_schedule = self._parse_class_schedule(cls)
            if not class_schedule:
                continue

            for day, start_time in class_schedule:
                # Calculate days until this class
                days_until = (day - today_weekday) % 7

                # If it's today, check if the class hasn't started yet
                if days_until == 0:
                    if start_time <= current_time:
                        days_until = 7  # Next week

                class_dt = now.replace(
                    hour=start_time.hour,
                    minute=start_time.minute,
                    second=0,
                    microsecond=0
                ) + timedelta(days=days_until)

                delta = class_dt - now
                if timedelta(0) < delta < min_delta:
                    min_delta = delta
                    next_class = {
                        "class_name": cls.get("name") or cls.get("course_code", "Class"),
                        "start_time": class_dt.isoformat(),
                        "location": cls.get("location") or cls.get("room", ""),
                        "professor": cls.get("professor") or cls.get("instructor", ""),
                        "time_until_minutes": int(delta.total_seconds() / 60),
                    }

        return next_class

    def get_todays_classes(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all classes scheduled for today."""
        user_context = db.get_user_context(user_id)
        classes = user_context.get("classes", []) if user_context else []

        if not classes:
            return []

        now = datetime.now(timezone.utc)
        today_weekday = now.weekday()
        todays_classes = []

        for cls in classes:
            class_schedule = self._parse_class_schedule(cls)
            if not class_schedule:
                continue

            for day, start_time in class_schedule:
                if day == today_weekday:
                    class_dt = now.replace(
                        hour=start_time.hour,
                        minute=start_time.minute,
                        second=0,
                        microsecond=0
                    )
                    todays_classes.append({
                        "class_name": cls.get("name") or cls.get("course_code", "Class"),
                        "start_time": class_dt.isoformat(),
                        "location": cls.get("location") or cls.get("room", ""),
                        "is_past": class_dt < now,
                    })

        # Sort by start time
        todays_classes.sort(key=lambda x: x["start_time"])
        return todays_classes

    def should_send_morning_alert(self, user_id: str) -> Tuple[bool, Optional[Dict]]:
        """
        Determine if a morning class alert should be sent.

        Returns:
            (should_send, class_info) tuple
        """
        now = datetime.now(timezone.utc)

        # Only consider morning alerts between 6am and 10am
        if not (6 <= now.hour < 10):
            return False, None

        next_class = self.get_next_class(user_id)
        if not next_class:
            return False, None

        # Alert if class is within 2 hours
        time_until = next_class.get("time_until_minutes", 999)
        if 0 < time_until <= 120:
            return True, next_class

        return False, None

    def get_study_reminder_time(self, user_id: str) -> Optional[datetime]:
        """
        Calculate the optimal time for a study reminder based on user patterns.

        Returns:
            datetime for the next study reminder, or None
        """
        now = datetime.now(timezone.utc)

        # Check user's activity patterns if available
        patterns = db.get_latest_user_pattern(user_id, "activity")

        # Default to evening study time
        preferred_window = self.EVENING_STUDY_WINDOW

        if patterns and patterns.get("pattern_data"):
            peak_hours = patterns["pattern_data"].get("peak_hours", [])
            if peak_hours:
                # Find the peak hour that falls in a study window
                for hour in peak_hours:
                    if 8 <= hour < 12:
                        preferred_window = self.MORNING_STUDY_WINDOW
                        break
                    elif 14 <= hour < 18:
                        preferred_window = self.AFTERNOON_STUDY_WINDOW
                        break

        # Calculate next occurrence of the preferred window start
        target_time = now.replace(
            hour=preferred_window[0].hour,
            minute=preferred_window[0].minute,
            second=0,
            microsecond=0
        )

        if target_time <= now:
            # If we've passed the window start today, try tomorrow
            target_time += timedelta(days=1)

        return target_time

    def get_free_slots(self, user_id: str, date: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """
        Find free time slots in the user's schedule.

        Args:
            user_id: User ID
            date: Date to check (defaults to today)

        Returns:
            List of free slot dicts with start_time, end_time, duration_minutes
        """
        if date is None:
            date = datetime.now(timezone.utc)

        classes = self.get_todays_classes(user_id)

        # Build list of busy periods
        busy_periods = []
        for cls in classes:
            start = datetime.fromisoformat(cls["start_time"])
            # Assume 1 hour class duration if not specified
            end = start + timedelta(hours=1)
            busy_periods.append((start, end))

        # Sort by start time
        busy_periods.sort(key=lambda x: x[0])

        # Find gaps
        free_slots = []
        day_start = date.replace(hour=8, minute=0, second=0, microsecond=0)
        day_end = date.replace(hour=22, minute=0, second=0, microsecond=0)

        current = day_start
        for busy_start, busy_end in busy_periods:
            if busy_start > current:
                # There's a free slot
                duration = int((busy_start - current).total_seconds() / 60)
                if duration >= 30:  # Only count slots of 30+ minutes
                    free_slots.append({
                        "start_time": current.isoformat(),
                        "end_time": busy_start.isoformat(),
                        "duration_minutes": duration,
                    })
            current = max(current, busy_end)

        # Check for time after last class
        if current < day_end:
            duration = int((day_end - current).total_seconds() / 60)
            if duration >= 30:
                free_slots.append({
                    "start_time": current.isoformat(),
                    "end_time": day_end.isoformat(),
                    "duration_minutes": duration,
                })

        return free_slots

    def schedule_class_reminders(self, user_id: str) -> List[Dict]:
        """
        Schedule reminders for all upcoming classes.

        Returns:
            List of created jobs
        """
        from link_scheduler import schedule_class_reminder

        jobs = []
        todays_classes = self.get_todays_classes(user_id)

        for cls in todays_classes:
            if cls.get("is_past"):
                continue

            start_time = datetime.fromisoformat(cls["start_time"])
            try:
                job = schedule_class_reminder(
                    user_id,
                    cls["class_name"],
                    start_time
                )
                jobs.append(job)
            except Exception:
                pass

        return jobs

    # ============ Private Helpers ============

    def _parse_class_schedule(self, cls: Dict) -> List[Tuple[int, time]]:
        """
        Parse class schedule from various formats.

        Returns:
            List of (weekday, start_time) tuples
        """
        schedule = []

        # Try different schedule formats
        if "schedule" in cls:
            # Format: {"schedule": [{"day": "Monday", "time": "09:00"}]}
            for entry in cls.get("schedule", []):
                day = self._day_to_weekday(entry.get("day"))
                time_str = entry.get("time") or entry.get("start_time")
                if day is not None and time_str:
                    parsed_time = self._parse_time(time_str)
                    if parsed_time:
                        schedule.append((day, parsed_time))

        elif "days" in cls:
            # Format: {"days": ["M", "W", "F"], "start_time": "10:00"}
            days = cls.get("days", [])
            time_str = cls.get("start_time") or cls.get("time")
            parsed_time = self._parse_time(time_str)
            if parsed_time:
                for day_str in days:
                    day = self._day_to_weekday(day_str)
                    if day is not None:
                        schedule.append((day, parsed_time))

        elif "meeting_times" in cls:
            # Format: {"meeting_times": "MWF 9:00 AM"}
            meeting = cls.get("meeting_times", "")
            schedule = self._parse_meeting_string(meeting)

        return schedule

    def _day_to_weekday(self, day_str: Optional[str]) -> Optional[int]:
        """Convert day string to weekday number (0=Monday)."""
        if not day_str:
            return None

        day_map = {
            "monday": 0, "mon": 0, "m": 0,
            "tuesday": 1, "tue": 1, "t": 1, "tu": 1,
            "wednesday": 2, "wed": 2, "w": 2,
            "thursday": 3, "thu": 3, "th": 3, "r": 3,
            "friday": 4, "fri": 4, "f": 4,
            "saturday": 5, "sat": 5, "s": 5,
            "sunday": 6, "sun": 6, "u": 6,
        }
        return day_map.get(day_str.lower().strip())

    def _parse_time(self, time_str: Optional[str]) -> Optional[time]:
        """Parse time string to time object."""
        if not time_str:
            return None

        formats = ["%H:%M", "%I:%M %p", "%I:%M%p", "%H:%M:%S"]
        for fmt in formats:
            try:
                parsed = datetime.strptime(time_str.strip(), fmt)
                return parsed.time()
            except ValueError:
                continue
        return None

    def _parse_meeting_string(self, meeting: str) -> List[Tuple[int, time]]:
        """Parse meeting string like 'MWF 9:00 AM'."""
        import re

        schedule = []
        if not meeting:
            return schedule

        # Extract days and time
        match = re.match(r"([MTWRFSU]+)\s+(\d{1,2}:\d{2}\s*(?:AM|PM)?)", meeting, re.IGNORECASE)
        if match:
            days_str = match.group(1).upper()
            time_str = match.group(2)

            parsed_time = self._parse_time(time_str)
            if parsed_time:
                for char in days_str:
                    day = self._day_to_weekday(char)
                    if day is not None:
                        schedule.append((day, parsed_time))

        return schedule


# Singleton export
schedule_monitor = ScheduleMonitor()
