"""Tests for the Wellness Monitor module."""

import sys
import os
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta

# Setup path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock dependencies
sys.modules['config'] = MagicMock()
sys.modules['config'].settings = MagicMock()
sys.modules['config'].settings.TEST_MODE = True

mock_db = MagicMock()
sys.modules['supabase_client'] = mock_db

from wellness_monitor import WellnessMonitor


class TestWellnessMonitor(unittest.TestCase):
    """Test cases for WellnessMonitor class."""

    def setUp(self):
        mock_db.reset_mock()
        self.monitor = WellnessMonitor()
        self.user_id = "test_user_123"

    def test_check_mood_drop_significant(self):
        """Test detection of significant mood drops."""
        mock_db.get_user_vibe.return_value = {
            "mood_score": 3.0,  # Current low mood
            "formality_level": 0.3,
        }

        # Mock trend with earlier higher scores
        with patch.object(self.monitor, 'get_mood_trend') as mock_trend:
            mock_trend.return_value = [3.0, 3.2, 3.1, 5.5, 5.6, 5.4, 5.3]

            result = self.monitor.check_mood_drop(self.user_id)

            self.assertIsNotNone(result)
            self.assertEqual(result["signal_type"], "mood_drop")
            self.assertGreaterEqual(result["severity"], 2)

    def test_check_mood_drop_no_change(self):
        """Test no mood drop when scores are stable."""
        mock_db.get_user_vibe.return_value = {
            "mood_score": 4.5,
            "formality_level": 0.5,
        }

        with patch.object(self.monitor, 'get_mood_trend') as mock_trend:
            mock_trend.return_value = [4.5, 4.6, 4.4, 4.5, 4.6, 4.5, 4.4]

            result = self.monitor.check_mood_drop(self.user_id)

            self.assertIsNone(result)

    def test_check_isolation_signals_detected(self):
        """Test detection of isolation when social user goes quiet."""
        mock_db.get_latest_user_pattern.return_value = {
            "pattern_data": {"level": "highly_social"}
        }
        mock_db.get_or_create_link_conversation.return_value = {"id": "conv_123"}
        mock_db.list_link_messages_for_conversation.return_value = []  # No recent messages
        mock_db.list_recent_outreach_target_ids.return_value = []  # No outreach

        result = self.monitor.check_isolation_signals(self.user_id)

        self.assertIsNotNone(result)
        self.assertEqual(result["signal_type"], "isolation")
        self.assertTrue(result["should_trigger_checkin"])

    def test_check_isolation_signals_not_detected(self):
        """Test no isolation when user is active."""
        mock_db.get_latest_user_pattern.return_value = {
            "pattern_data": {"level": "moderately_social"}
        }
        mock_db.get_or_create_link_conversation.return_value = {"id": "conv_123"}
        mock_db.list_link_messages_for_conversation.return_value = [
            {"content": "hey", "created_at": datetime.now(timezone.utc).isoformat()}
        ]
        mock_db.list_recent_outreach_target_ids.return_value = []

        result = self.monitor.check_isolation_signals(self.user_id)

        self.assertIsNone(result)

    def test_check_stress_indicators_detected(self):
        """Test detection of stress keywords."""
        mock_db.get_or_create_link_conversation.return_value = {"id": "conv_123"}

        now = datetime.now(timezone.utc).isoformat()
        mock_db.list_link_messages_for_conversation.return_value = [
            {"content": "i'm so stressed about this exam", "created_at": now},
            {"content": "feeling really anxious lately", "created_at": now},
            {"content": "can't sleep because i'm worried", "created_at": now},
            {"content": "i'm overwhelmed with everything", "created_at": now},
            {"content": "just a normal message here", "created_at": now},
        ]

        result = self.monitor.check_stress_indicators(self.user_id)

        self.assertIsNotNone(result)
        self.assertEqual(result["signal_type"], "stress")
        self.assertGreaterEqual(result["severity"], 3)
        self.assertTrue(len(result["metrics"]["keywords_found"]) > 0)

    def test_check_stress_indicators_none(self):
        """Test no stress when messages are normal."""
        mock_db.get_or_create_link_conversation.return_value = {"id": "conv_123"}

        now = datetime.now(timezone.utc).isoformat()
        mock_db.list_link_messages_for_conversation.return_value = [
            {"content": "had a great day today", "created_at": now},
            {"content": "lunch was good", "created_at": now},
            {"content": "class was interesting", "created_at": now},
        ]

        result = self.monitor.check_stress_indicators(self.user_id)

        self.assertIsNone(result)

    def test_check_activity_change_drop(self):
        """Test detection of activity drops."""
        mock_db.get_latest_user_pattern.return_value = {
            "pattern_data": {
                "level": "highly_active",
                "messages_per_day": 10,
            }
        }
        mock_db.get_or_create_link_conversation.return_value = {"id": "conv_123"}
        # Only 3 messages in 3 days = 1/day (10% of baseline)
        mock_db.list_link_messages_for_conversation.return_value = [
            {"content": "msg"} for _ in range(3)
        ]

        result = self.monitor.check_activity_change(self.user_id)

        self.assertIsNotNone(result)
        self.assertEqual(result["signal_type"], "activity_change")

    def test_get_wellness_score_healthy(self):
        """Test wellness score calculation with no signals."""
        mock_db.get_wellness_signals.return_value = []
        mock_db.get_latest_user_pattern.return_value = {
            "pattern_data": {"level": "moderately_active"}
        }

        result = self.monitor.get_wellness_score(self.user_id)

        self.assertEqual(result, 1.0)

    def test_get_wellness_score_with_signals(self):
        """Test wellness score reduction with signals."""
        mock_db.get_wellness_signals.return_value = [
            {"severity": 3},
            {"severity": 2},
        ]
        mock_db.get_latest_user_pattern.return_value = None

        result = self.monitor.get_wellness_score(self.user_id)

        # Should be reduced: 1.0 - (3*0.1) - (2*0.1) = 0.5
        self.assertAlmostEqual(result, 0.5, places=2)

    def test_should_trigger_checkin_high_severity(self):
        """Test check-in trigger with high severity signal."""
        mock_db.get_wellness_signals.return_value = [
            {"severity": 4, "description": "High stress detected"}
        ]

        should_trigger, reason = self.monitor.should_trigger_checkin(self.user_id)

        self.assertTrue(should_trigger)
        self.assertIsNotNone(reason)

    def test_should_trigger_checkin_low_severity(self):
        """Test no check-in trigger with low severity signals."""
        mock_db.get_wellness_signals.return_value = [
            {"severity": 2, "description": "Minor activity change"}
        ]

        should_trigger, reason = self.monitor.should_trigger_checkin(self.user_id)

        self.assertFalse(should_trigger)
        self.assertIsNone(reason)

    def test_run_wellness_check_comprehensive(self):
        """Test full wellness check flow."""
        # Setup mocks for comprehensive check
        mock_db.get_user_vibe.return_value = {"mood_score": 4.0}
        mock_db.get_latest_user_pattern.return_value = {
            "pattern_data": {"level": "moderately_social"}
        }
        mock_db.get_or_create_link_conversation.return_value = {"id": "conv_123"}
        mock_db.list_link_messages_for_conversation.return_value = [
            {"content": "normal message", "created_at": datetime.now(timezone.utc).isoformat()}
        ]
        mock_db.list_recent_outreach_target_ids.return_value = ["user_1"]
        mock_db.create_wellness_signal.return_value = {"id": "signal_1"}

        with patch.object(self.monitor, 'get_mood_trend') as mock_trend:
            mock_trend.return_value = [4.0, 4.1, 4.0, 4.0, 4.1, 4.0, 4.0]

            result = self.monitor.run_wellness_check(self.user_id)

            self.assertIsInstance(result, list)


if __name__ == '__main__':
    unittest.main()
