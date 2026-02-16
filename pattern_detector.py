"""
Pattern Detection Engine for Link AI.

Analyzes user behavior patterns including:
- Sleep patterns (3am scan)
- Morning routines (9am scan)
- Afternoon activity (3pm scan)
- Evening/social patterns (9pm scan)
"""

from __future__ import annotations
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
import supabase_client as db


class PatternDetector:
    """
    Detects behavioral patterns from user activity data.
    Runs at scheduled intervals (3am/9am/3pm/9pm) to build pattern profiles.
    """

    # Pattern confidence thresholds
    MIN_CONFIDENCE = 0.3
    HIGH_CONFIDENCE = 0.7

    # Time windows for analysis
    ANALYSIS_WINDOW_DAYS = 14

    def analyze_sleep_patterns(self, user_id: str) -> Dict[str, Any]:
        """
        Analyze sleep patterns based on last message times.
        Runs at 3am to detect late-night activity.

        Returns:
            dict with pattern_type, pattern_data, confidence
        """
        # Get messages from the past 2 weeks
        since = datetime.now(timezone.utc) - timedelta(days=self.ANALYSIS_WINDOW_DAYS)
        messages = self._get_user_messages_since(user_id, since)

        if not messages:
            return self._empty_pattern("sleep")

        # Analyze message timestamps for late-night activity (11pm - 5am)
        late_night_count = 0
        total_days_active = set()
        late_night_times = []

        for msg in messages:
            created = self._parse_timestamp(msg.get("created_at"))
            if not created:
                continue

            total_days_active.add(created.date())
            hour = created.hour

            # Late night is 11pm (23) to 5am
            if hour >= 23 or hour < 5:
                late_night_count += 1
                late_night_times.append(hour)

        active_days = len(total_days_active)
        if active_days < 3:
            return self._empty_pattern("sleep")

        # Calculate pattern metrics
        late_night_ratio = late_night_count / len(messages) if messages else 0
        avg_late_hour = sum(late_night_times) / len(late_night_times) if late_night_times else 0

        # Determine pattern type
        if late_night_ratio > 0.3:
            pattern_label = "night_owl"
            confidence = min(0.9, late_night_ratio + 0.2)
        elif late_night_ratio < 0.05:
            pattern_label = "early_sleeper"
            confidence = 0.6
        else:
            pattern_label = "normal"
            confidence = 0.5

        return {
            "pattern_type": "sleep",
            "pattern_data": {
                "label": pattern_label,
                "late_night_ratio": round(late_night_ratio, 3),
                "avg_late_hour": round(avg_late_hour, 1) if late_night_times else None,
                "sample_size": len(messages),
                "active_days": active_days,
            },
            "confidence": round(confidence, 2),
        }

    def analyze_activity_patterns(self, user_id: str) -> Dict[str, Any]:
        """
        Analyze general activity patterns (message frequency, timing).
        Runs at 9am and 3pm.

        Returns:
            dict with pattern_type, pattern_data, confidence
        """
        since = datetime.now(timezone.utc) - timedelta(days=self.ANALYSIS_WINDOW_DAYS)
        messages = self._get_user_messages_since(user_id, since)

        if not messages:
            return self._empty_pattern("activity")

        # Analyze message distribution by hour
        hour_counts = {h: 0 for h in range(24)}
        day_counts = {d: 0 for d in range(7)}  # 0=Monday

        for msg in messages:
            created = self._parse_timestamp(msg.get("created_at"))
            if not created:
                continue
            hour_counts[created.hour] += 1
            day_counts[created.weekday()] += 1

        total = len(messages)

        # Find peak hours (top 3)
        sorted_hours = sorted(hour_counts.items(), key=lambda x: x[1], reverse=True)
        peak_hours = [h for h, c in sorted_hours[:3] if c > 0]

        # Find peak days
        sorted_days = sorted(day_counts.items(), key=lambda x: x[1], reverse=True)
        peak_days = [d for d, c in sorted_days[:3] if c > 0]

        # Determine activity level
        messages_per_day = total / self.ANALYSIS_WINDOW_DAYS
        if messages_per_day > 10:
            activity_level = "highly_active"
            confidence = 0.8
        elif messages_per_day > 3:
            activity_level = "moderately_active"
            confidence = 0.7
        elif messages_per_day > 0.5:
            activity_level = "occasionally_active"
            confidence = 0.6
        else:
            activity_level = "low_activity"
            confidence = 0.5

        return {
            "pattern_type": "activity",
            "pattern_data": {
                "level": activity_level,
                "messages_per_day": round(messages_per_day, 1),
                "peak_hours": peak_hours,
                "peak_days": peak_days,
                "hour_distribution": hour_counts,
                "day_distribution": day_counts,
            },
            "confidence": round(confidence, 2),
        }

    def analyze_social_patterns(self, user_id: str) -> Dict[str, Any]:
        """
        Analyze social interaction patterns.
        Runs at 9pm to detect evening social activity.

        Returns:
            dict with pattern_type, pattern_data, confidence
        """
        since = datetime.now(timezone.utc) - timedelta(days=self.ANALYSIS_WINDOW_DAYS)

        # Check outreach activity
        outreach_runs = self._get_outreach_runs(user_id, since)

        # Check friend interactions (if available)
        friends = db.get_friends(user_id) if hasattr(db, "get_friends") else []

        outreach_count = len(outreach_runs)
        friend_count = len(friends)

        # Determine social pattern
        if outreach_count > 5 or friend_count > 20:
            social_level = "highly_social"
            confidence = 0.8
        elif outreach_count > 2 or friend_count > 10:
            social_level = "moderately_social"
            confidence = 0.7
        elif outreach_count > 0 or friend_count > 3:
            social_level = "selectively_social"
            confidence = 0.6
        else:
            social_level = "private"
            confidence = 0.5

        return {
            "pattern_type": "social",
            "pattern_data": {
                "level": social_level,
                "outreach_count": outreach_count,
                "friend_count": friend_count,
            },
            "confidence": round(confidence, 2),
        }

    def analyze_academic_patterns(self, user_id: str) -> Dict[str, Any]:
        """
        Analyze academic-related patterns (study mentions, class activity).

        Returns:
            dict with pattern_type, pattern_data, confidence
        """
        since = datetime.now(timezone.utc) - timedelta(days=self.ANALYSIS_WINDOW_DAYS)
        messages = self._get_user_messages_since(user_id, since)

        if not messages:
            return self._empty_pattern("academic")

        # Keywords indicating academic activity
        study_keywords = {"study", "exam", "test", "midterm", "final", "homework", "assignment", "paper", "essay", "project", "class", "lecture", "professor", "library"}

        study_mentions = 0
        for msg in messages:
            content = (msg.get("content") or "").lower()
            if any(kw in content for kw in study_keywords):
                study_mentions += 1

        study_ratio = study_mentions / len(messages) if messages else 0

        # Check class schedule
        user_context = db.get_user_context(user_id)
        classes = user_context.get("classes", []) if user_context else []
        class_count = len(classes)

        # Determine academic engagement
        if study_ratio > 0.2 and class_count > 3:
            academic_level = "highly_engaged"
            confidence = 0.8
        elif study_ratio > 0.1 or class_count > 2:
            academic_level = "moderately_engaged"
            confidence = 0.7
        elif class_count > 0:
            academic_level = "enrolled"
            confidence = 0.6
        else:
            academic_level = "unknown"
            confidence = 0.3

        return {
            "pattern_type": "academic",
            "pattern_data": {
                "level": academic_level,
                "study_mention_ratio": round(study_ratio, 3),
                "class_count": class_count,
            },
            "confidence": round(confidence, 2),
        }

    def detect_routine_changes(self, user_id: str) -> List[Dict[str, Any]]:
        """
        Detect significant changes in user routines.
        Compares recent patterns to historical baseline.

        Returns:
            List of detected changes with descriptions
        """
        changes = []

        # Get recent patterns (last 7 days)
        recent_since = datetime.now(timezone.utc) - timedelta(days=7)
        recent_messages = self._get_user_messages_since(user_id, recent_since)

        # Get baseline patterns (8-21 days ago)
        baseline_start = datetime.now(timezone.utc) - timedelta(days=21)
        baseline_end = datetime.now(timezone.utc) - timedelta(days=8)
        baseline_messages = self._get_user_messages_between(user_id, baseline_start, baseline_end)

        if not recent_messages or not baseline_messages:
            return changes

        # Compare activity levels
        recent_daily = len(recent_messages) / 7
        baseline_daily = len(baseline_messages) / 13

        if baseline_daily > 0:
            change_ratio = recent_daily / baseline_daily

            if change_ratio < 0.3:
                changes.append({
                    "change_type": "activity_drop",
                    "severity": "high",
                    "description": "Significant decrease in messaging activity",
                    "metrics": {
                        "recent_daily": round(recent_daily, 1),
                        "baseline_daily": round(baseline_daily, 1),
                        "change_ratio": round(change_ratio, 2),
                    }
                })
            elif change_ratio < 0.6:
                changes.append({
                    "change_type": "activity_drop",
                    "severity": "moderate",
                    "description": "Moderate decrease in messaging activity",
                    "metrics": {
                        "recent_daily": round(recent_daily, 1),
                        "baseline_daily": round(baseline_daily, 1),
                        "change_ratio": round(change_ratio, 2),
                    }
                })
            elif change_ratio > 2.5:
                changes.append({
                    "change_type": "activity_spike",
                    "severity": "notable",
                    "description": "Significant increase in messaging activity",
                    "metrics": {
                        "recent_daily": round(recent_daily, 1),
                        "baseline_daily": round(baseline_daily, 1),
                        "change_ratio": round(change_ratio, 2),
                    }
                })

        # Compare timing patterns
        recent_late = sum(1 for m in recent_messages if self._is_late_night(m))
        baseline_late = sum(1 for m in baseline_messages if self._is_late_night(m))

        recent_late_ratio = recent_late / len(recent_messages) if recent_messages else 0
        baseline_late_ratio = baseline_late / len(baseline_messages) if baseline_messages else 0

        if recent_late_ratio > baseline_late_ratio + 0.2:
            changes.append({
                "change_type": "sleep_pattern_shift",
                "severity": "moderate",
                "description": "Increase in late-night activity",
                "metrics": {
                    "recent_late_ratio": round(recent_late_ratio, 2),
                    "baseline_late_ratio": round(baseline_late_ratio, 2),
                }
            })

        return changes

    def save_pattern(self, user_id: str, pattern: Dict[str, Any]) -> Dict[str, Any]:
        """Save detected pattern to database."""
        payload = {
            "user_id": user_id,
            "pattern_type": pattern["pattern_type"],
            "pattern_data": pattern["pattern_data"],
            "confidence": pattern["confidence"],
            "detected_at": datetime.now(timezone.utc).isoformat(),
        }
        return db.create_user_pattern(payload)

    # ============ Private Helpers ============

    def _get_user_messages_since(self, user_id: str, since: datetime) -> List[Dict]:
        """Fetch user messages since a given datetime."""
        # Get the user's conversation
        conversation = db.get_or_create_link_conversation(user_id)
        if not conversation:
            return []

        conversation_id = conversation.get("id")
        if not conversation_id:
            return []

        return db.list_link_messages_for_conversation(
            conversation_id,
            after=since.isoformat(),
            sender_type="user",
            limit=500
        )

    def _get_user_messages_between(self, user_id: str, start: datetime, end: datetime) -> List[Dict]:
        """Fetch user messages between two datetimes."""
        messages = self._get_user_messages_since(user_id, start)
        return [m for m in messages if self._parse_timestamp(m.get("created_at")) and self._parse_timestamp(m.get("created_at")) < end]

    def _get_outreach_runs(self, user_id: str, since: datetime) -> List[Dict]:
        """Get outreach runs for a user."""
        try:
            # Check for recent outreach run function
            if hasattr(db, "list_recent_outreach_target_ids"):
                # This returns target IDs, but we can count from runs table
                client = db.get_supabase_client()
                result = client.table("link_outreach_runs").select("*").eq("requester_user_id", user_id).gte("created_at", since.isoformat()).execute()
                return result.data or []
        except Exception:
            pass
        return []

    def _parse_timestamp(self, ts: Optional[str]) -> Optional[datetime]:
        """Parse ISO timestamp string."""
        if not ts:
            return None
        try:
            # Handle various ISO formats
            if ts.endswith("Z"):
                ts = ts[:-1] + "+00:00"
            return datetime.fromisoformat(ts)
        except (ValueError, TypeError):
            return None

    def _is_late_night(self, msg: Dict) -> bool:
        """Check if message was sent during late night hours."""
        created = self._parse_timestamp(msg.get("created_at"))
        if not created:
            return False
        hour = created.hour
        return hour >= 23 or hour < 5

    def _empty_pattern(self, pattern_type: str) -> Dict[str, Any]:
        """Return empty pattern structure."""
        return {
            "pattern_type": pattern_type,
            "pattern_data": {"label": "insufficient_data"},
            "confidence": 0.0,
        }


# Singleton export
pattern_detector = PatternDetector()
