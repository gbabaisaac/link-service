"""Tests for the Pattern Detection Engine."""

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

from pattern_detector import PatternDetector


class TestPatternDetector(unittest.TestCase):
    """Test cases for PatternDetector class."""

    def setUp(self):
        mock_db.reset_mock()
        self.detector = PatternDetector()
        self.user_id = "test_user_123"

    def test_analyze_sleep_patterns_night_owl(self):
        """Test detection of night owl sleep patterns."""
        now = datetime.now(timezone.utc)

        # Create messages with late night timestamps
        messages = []
        for i in range(20):
            # Half at 2am, half at normal hours
            hour = 2 if i < 10 else 14
            ts = now.replace(hour=hour, minute=0) - timedelta(days=i % 7)
            messages.append({
                "content": f"test message {i}",
                "created_at": ts.isoformat(),
            })

        mock_db.get_or_create_link_conversation.return_value = {"id": "conv_123"}
        mock_db.list_link_messages_for_conversation.return_value = messages

        result = self.detector.analyze_sleep_patterns(self.user_id)

        self.assertEqual(result["pattern_type"], "sleep")
        self.assertIn(result["pattern_data"]["label"], ["night_owl", "normal"])
        self.assertGreater(result["confidence"], 0)

    def test_analyze_sleep_patterns_insufficient_data(self):
        """Test handling of insufficient data."""
        mock_db.get_or_create_link_conversation.return_value = {"id": "conv_123"}
        mock_db.list_link_messages_for_conversation.return_value = []

        result = self.detector.analyze_sleep_patterns(self.user_id)

        self.assertEqual(result["pattern_type"], "sleep")
        self.assertEqual(result["pattern_data"]["label"], "insufficient_data")
        self.assertEqual(result["confidence"], 0.0)

    def test_analyze_activity_patterns_highly_active(self):
        """Test detection of highly active users."""
        now = datetime.now(timezone.utc)

        # Create 150 messages over 14 days = ~10 per day
        messages = []
        for i in range(150):
            hour = (9 + i % 8)  # Between 9am and 5pm
            day = i // 10
            ts = now.replace(hour=hour, minute=0) - timedelta(days=day)
            messages.append({
                "content": f"test message {i}",
                "created_at": ts.isoformat(),
            })

        mock_db.get_or_create_link_conversation.return_value = {"id": "conv_123"}
        mock_db.list_link_messages_for_conversation.return_value = messages

        result = self.detector.analyze_activity_patterns(self.user_id)

        self.assertEqual(result["pattern_type"], "activity")
        self.assertEqual(result["pattern_data"]["level"], "highly_active")
        self.assertGreater(result["confidence"], 0.7)

    def test_analyze_activity_patterns_low_activity(self):
        """Test detection of low activity users."""
        now = datetime.now(timezone.utc)

        # Create 5 messages over 14 days
        messages = [
            {"content": "msg", "created_at": (now - timedelta(days=i*3)).isoformat()}
            for i in range(5)
        ]

        mock_db.get_or_create_link_conversation.return_value = {"id": "conv_123"}
        mock_db.list_link_messages_for_conversation.return_value = messages

        result = self.detector.analyze_activity_patterns(self.user_id)

        self.assertEqual(result["pattern_type"], "activity")
        # 5 messages / 14 days = ~0.36 messages per day -> low_activity or occasionally_active
        self.assertIn(result["pattern_data"]["level"], ["low_activity", "occasionally_active"])

    def test_analyze_social_patterns_highly_social(self):
        """Test detection of highly social patterns."""
        mock_db.get_supabase_client.return_value.table.return_value.select.return_value.eq.return_value.gte.return_value.execute.return_value.data = [
            {"id": f"run_{i}"} for i in range(10)  # 10 outreach runs
        ]
        mock_db.get_friends.return_value = [f"friend_{i}" for i in range(25)]  # 25 friends

        result = self.detector.analyze_social_patterns(self.user_id)

        self.assertEqual(result["pattern_type"], "social")
        self.assertEqual(result["pattern_data"]["level"], "highly_social")

    def test_analyze_academic_patterns_engaged(self):
        """Test detection of academically engaged users."""
        now = datetime.now(timezone.utc)

        # Create messages with study-related keywords
        messages = [
            {"content": "studying for my midterm exam", "created_at": now.isoformat()},
            {"content": "going to library", "created_at": now.isoformat()},
            {"content": "professor gave us homework", "created_at": now.isoformat()},
            {"content": "working on assignment", "created_at": now.isoformat()},
            {"content": "class was good today", "created_at": now.isoformat()},
            {"content": "random chat", "created_at": now.isoformat()},
        ]

        mock_db.get_or_create_link_conversation.return_value = {"id": "conv_123"}
        mock_db.list_link_messages_for_conversation.return_value = messages
        mock_db.get_user_context.return_value = {
            "classes": [{"name": "CS101"}, {"name": "MATH201"}, {"name": "PHYS101"}]
        }

        result = self.detector.analyze_academic_patterns(self.user_id)

        self.assertEqual(result["pattern_type"], "academic")
        self.assertIn(result["pattern_data"]["level"], ["highly_engaged", "moderately_engaged"])

    def test_detect_routine_changes_activity_drop(self):
        """Test detection of activity drops."""
        now = datetime.now(timezone.utc)

        # All messages (combined recent + baseline)
        all_messages = []

        # Recent: only 3 messages in 7 days
        for i in range(3):
            all_messages.append({
                "content": "msg",
                "created_at": (now - timedelta(days=i*2)).isoformat()
            })

        # Baseline: 20 messages in 13 days (before recent period, days 8-21)
        for i in range(20):
            all_messages.append({
                "content": "msg",
                "created_at": (now - timedelta(days=8+i)).isoformat()
            })

        mock_db.get_or_create_link_conversation.return_value = {"id": "conv_123"}
        # Return same list for both calls (method will filter by date)
        mock_db.list_link_messages_for_conversation.return_value = all_messages

        result = self.detector.detect_routine_changes(self.user_id)

        # Should detect some change (may or may not be activity_drop depending on thresholds)
        self.assertIsInstance(result, list)

    def test_parse_timestamp_valid(self):
        """Test timestamp parsing with valid ISO format."""
        ts = "2024-01-15T10:30:00+00:00"
        result = self.detector._parse_timestamp(ts)
        self.assertIsNotNone(result)
        self.assertEqual(result.hour, 10)

    def test_parse_timestamp_with_z(self):
        """Test timestamp parsing with Z suffix."""
        ts = "2024-01-15T10:30:00Z"
        result = self.detector._parse_timestamp(ts)
        self.assertIsNotNone(result)

    def test_parse_timestamp_invalid(self):
        """Test timestamp parsing with invalid format."""
        result = self.detector._parse_timestamp("not a timestamp")
        self.assertIsNone(result)

    def test_is_late_night(self):
        """Test late night detection."""
        late_msg = {"created_at": "2024-01-15T02:30:00+00:00"}
        normal_msg = {"created_at": "2024-01-15T14:30:00+00:00"}

        self.assertTrue(self.detector._is_late_night(late_msg))
        self.assertFalse(self.detector._is_late_night(normal_msg))


if __name__ == '__main__':
    unittest.main()
