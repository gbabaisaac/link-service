"""
Wellness Monitoring for Link AI.

Detects wellness indicators and triggers appropriate interventions:
- Mood drops (significant decrease in vibe scores)
- Isolation signals (decreased social activity)
- Stress indicators (keywords, late-night activity)
- Activity changes (sudden drops in engagement)
"""

from __future__ import annotations
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
import supabase_client as db


class WellnessMonitor:
    """
    Monitors user wellness signals and triggers appropriate responses.
    Works with vibe tracking, pattern detection, and conversation analysis.
    """

    # Thresholds for wellness signals
    MOOD_DROP_THRESHOLD = 2.0  # Point drop in 48 hours
    ISOLATION_DAYS_THRESHOLD = 5  # Days without social activity
    STRESS_KEYWORD_THRESHOLD = 0.15  # Ratio of stress keywords
    ACTIVITY_DROP_THRESHOLD = 0.3  # 70% drop in activity

    # Stress-related keywords
    STRESS_KEYWORDS = {
        "stressed", "stress", "anxious", "anxiety", "overwhelmed",
        "tired", "exhausted", "burnt out", "burnout", "depressed",
        "sad", "lonely", "alone", "struggling", "failing", "failed",
        "behind", "deadline", "panic", "worried", "nervous", "scared",
        "can't sleep", "insomnia", "too much", "give up"
    }

    def run_wellness_check(self, user_id: str) -> List[Dict[str, Any]]:
        """
        Run a comprehensive wellness check for a user.

        Returns:
            List of detected wellness signals
        """
        signals = []

        # 1. Check for mood drops
        mood_signal = self.check_mood_drop(user_id)
        if mood_signal:
            signals.append(mood_signal)

        # 2. Check for isolation
        isolation_signal = self.check_isolation_signals(user_id)
        if isolation_signal:
            signals.append(isolation_signal)

        # 3. Check for stress keywords in recent messages
        stress_signal = self.check_stress_indicators(user_id)
        if stress_signal:
            signals.append(stress_signal)

        # 4. Check for activity drops
        activity_signal = self.check_activity_change(user_id)
        if activity_signal:
            signals.append(activity_signal)

        # Save detected signals to database
        for signal in signals:
            self._save_signal(user_id, signal)

        return signals

    def check_mood_drop(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Check for significant mood drops using vibe history.

        Returns:
            Wellness signal dict if mood drop detected, None otherwise
        """
        current_vibe = db.get_user_vibe(user_id)
        if not current_vibe:
            return None

        current_mood = current_vibe.get("mood_score")
        if current_mood is None:
            # Try formality as a proxy (low formality can indicate casual/relaxed)
            current_mood = current_vibe.get("formality_level", 0.5) * 5

        # Get mood trend
        trend = self.get_mood_trend(user_id, days=7)
        if len(trend) < 2:
            return None

        # Check for significant drop
        recent_avg = sum(trend[:3]) / len(trend[:3]) if len(trend) >= 3 else trend[0]
        earlier_avg = sum(trend[3:]) / len(trend[3:]) if len(trend) > 3 else trend[-1]

        drop = earlier_avg - recent_avg

        if drop >= self.MOOD_DROP_THRESHOLD:
            severity = 3 if drop >= 3 else 2
            return {
                "signal_type": "mood_drop",
                "severity": severity,
                "description": f"Mood dropped by {drop:.1f} points over the past week",
                "metrics": {
                    "recent_avg": round(recent_avg, 2),
                    "earlier_avg": round(earlier_avg, 2),
                    "drop": round(drop, 2),
                },
                "should_trigger_checkin": severity >= 3,
                "reason": "mood drop detected",
            }

        return None

    def check_isolation_signals(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Check for isolation patterns (decreased social activity).

        Returns:
            Wellness signal dict if isolation detected, None otherwise
        """
        # Check recent social patterns
        patterns = db.get_latest_user_pattern(user_id, "social")

        # Get recent outreach/connection activity
        since = datetime.now(timezone.utc) - timedelta(days=self.ISOLATION_DAYS_THRESHOLD)

        # Check for conversations
        conversation = db.get_or_create_link_conversation(user_id)
        recent_messages = []
        if conversation:
            recent_messages = db.list_link_messages_for_conversation(
                conversation["id"],
                after=since.isoformat(),
                limit=10
            )

        # Check outreach activity
        outreach_targets = db.list_recent_outreach_target_ids(user_id, days=self.ISOLATION_DAYS_THRESHOLD)

        # Determine isolation level
        has_recent_conversation = len(recent_messages) > 0
        has_recent_outreach = len(outreach_targets) > 0

        if not has_recent_conversation and not has_recent_outreach:
            # Check if this is unusual (compare to baseline)
            baseline_pattern = patterns.get("pattern_data", {}) if patterns else {}

            if baseline_pattern.get("level") in ("highly_social", "moderately_social"):
                return {
                    "signal_type": "isolation",
                    "severity": 3,
                    "description": f"No social activity in {self.ISOLATION_DAYS_THRESHOLD} days (usually active)",
                    "metrics": {
                        "days_inactive": self.ISOLATION_DAYS_THRESHOLD,
                        "baseline_level": baseline_pattern.get("level", "unknown"),
                    },
                    "should_trigger_checkin": True,
                    "reason": "social isolation detected",
                }

        return None

    def check_stress_indicators(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Check for stress indicators in recent messages.

        Returns:
            Wellness signal dict if stress detected, None otherwise
        """
        conversation = db.get_or_create_link_conversation(user_id)
        if not conversation:
            return None

        since = datetime.now(timezone.utc) - timedelta(days=3)
        messages = db.list_link_messages_for_conversation(
            conversation["id"],
            after=since.isoformat(),
            sender_type="user",
            limit=50
        )

        if not messages:
            return None

        # Count stress keywords
        total_words = 0
        stress_hits = 0
        stress_phrases_found = []

        for msg in messages:
            content = (msg.get("content") or "").lower()
            words = content.split()
            total_words += len(words)

            for keyword in self.STRESS_KEYWORDS:
                if keyword in content:
                    stress_hits += 1
                    if keyword not in stress_phrases_found:
                        stress_phrases_found.append(keyword)

        if total_words == 0:
            return None

        stress_ratio = stress_hits / len(messages)

        if stress_ratio >= self.STRESS_KEYWORD_THRESHOLD:
            severity = 4 if stress_ratio > 0.3 else 3
            return {
                "signal_type": "stress",
                "severity": severity,
                "description": f"Stress indicators detected in {int(stress_ratio * 100)}% of recent messages",
                "metrics": {
                    "stress_ratio": round(stress_ratio, 3),
                    "keywords_found": stress_phrases_found[:5],
                    "message_count": len(messages),
                },
                "should_trigger_checkin": severity >= 3,
                "reason": "stress indicators in conversation",
            }

        return None

    def check_activity_change(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Check for sudden drops in user activity.

        Returns:
            Wellness signal dict if activity drop detected, None otherwise
        """
        # Get activity pattern
        patterns = db.get_latest_user_pattern(user_id, "activity")
        if not patterns:
            return None

        pattern_data = patterns.get("pattern_data", {})

        # Check recent vs baseline activity
        messages_per_day = pattern_data.get("messages_per_day", 0)
        baseline_level = pattern_data.get("level", "unknown")

        # Get recent 3-day activity
        conversation = db.get_or_create_link_conversation(user_id)
        if not conversation:
            return None

        since = datetime.now(timezone.utc) - timedelta(days=3)
        recent_messages = db.list_link_messages_for_conversation(
            conversation["id"],
            after=since.isoformat(),
            sender_type="user",
            limit=100
        )

        recent_daily = len(recent_messages) / 3

        # Compare to baseline
        if messages_per_day > 0:
            ratio = recent_daily / messages_per_day
            if ratio < self.ACTIVITY_DROP_THRESHOLD:
                return {
                    "signal_type": "activity_change",
                    "severity": 2,
                    "description": f"Activity dropped to {int(ratio * 100)}% of baseline",
                    "metrics": {
                        "recent_daily": round(recent_daily, 1),
                        "baseline_daily": round(messages_per_day, 1),
                        "change_ratio": round(ratio, 2),
                    },
                    "should_trigger_checkin": False,  # Lower priority
                    "reason": "activity drop detected",
                }

        return None

    def get_mood_trend(self, user_id: str, days: int = 7) -> List[float]:
        """
        Get mood scores over the past N days.

        Returns:
            List of mood scores (most recent first)
        """
        # For now, use vibe tracking data
        # In a full implementation, this would query a mood_history table
        vibe = db.get_user_vibe(user_id)
        if not vibe:
            return []

        # Simulate trend based on current vibe
        # In production, this would be replaced with actual historical data
        current = vibe.get("mood_score") or vibe.get("formality_level", 0.5) * 5
        trend = [current]

        # Add slight variation for demo purposes
        import random
        for _ in range(days - 1):
            trend.append(current + random.uniform(-0.5, 0.5))

        return trend

    def should_trigger_checkin(self, user_id: str) -> Tuple[bool, Optional[str]]:
        """
        Determine if a wellness check-in should be triggered.

        Returns:
            (should_trigger, reason) tuple
        """
        # Check unacknowledged signals
        signals = db.get_wellness_signals(user_id, acknowledged=False, limit=5)

        # Trigger if there are high-severity unacknowledged signals
        for signal in signals:
            if signal.get("severity", 0) >= 3:
                return True, signal.get("description", "wellness concern")

        return False, None

    def get_wellness_score(self, user_id: str) -> float:
        """
        Calculate an overall wellness score (0-1).

        Returns:
            float between 0 (concerning) and 1 (healthy)
        """
        score = 1.0

        # Reduce score based on unacknowledged signals
        signals = db.get_wellness_signals(user_id, acknowledged=False, limit=10)

        for signal in signals:
            severity = signal.get("severity", 1)
            score -= severity * 0.1

        # Factor in recent patterns
        patterns = db.get_latest_user_pattern(user_id, "activity")
        if patterns:
            activity_level = patterns.get("pattern_data", {}).get("level", "")
            if activity_level == "low_activity":
                score -= 0.1

        return max(0.0, min(1.0, score))

    # ============ Private Helpers ============

    def _save_signal(self, user_id: str, signal: Dict[str, Any]) -> Dict:
        """Save a wellness signal to the database."""
        payload = {
            "user_id": user_id,
            "signal_type": signal.get("signal_type"),
            "severity": signal.get("severity", 1),
            "description": signal.get("description"),
            "metrics": signal.get("metrics", {}),
        }
        return db.create_wellness_signal(payload)


# Tuple type hint
from typing import Tuple

# Singleton export
wellness_monitor = WellnessMonitor()
