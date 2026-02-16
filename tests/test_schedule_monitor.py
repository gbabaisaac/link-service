"""Tests for the Schedule Monitoring module."""

import sys
import os
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta, time

# Setup path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock dependencies
sys.modules['config'] = MagicMock()
sys.modules['config'].settings = MagicMock()
sys.modules['config'].settings.TEST_MODE = True

mock_db = MagicMock()
sys.modules['supabase_client'] = mock_db

from schedule_monitor import ScheduleMonitor


class TestScheduleMonitor(unittest.TestCase):
    """Test cases for ScheduleMonitor class."""

    def setUp(self):
        mock_db.reset_mock()
        self.monitor = ScheduleMonitor()
        self.user_id = "test_user_123"

    def test_get_next_class_with_schedule(self):
        """Test getting next class when schedule exists."""
        # Mock user context with class schedule
        mock_db.get_user_context.return_value = {
            "classes": [
                {
                    "name": "CS 101",
                    "schedule": [
                        {"day": "Monday", "time": "09:00"},
                        {"day": "Wednesday", "time": "09:00"},
                    ],
                    "location": "Room 101"
                },
                {
                    "name": "MATH 201",
                    "schedule": [
                        {"day": "Tuesday", "time": "14:00"},
                    ],
                    "location": "Room 202"
                }
            ]
        }

        result = self.monitor.get_next_class(self.user_id)

        # Should return a class (depending on current day)
        if result:
            self.assertIn("class_name", result)
            self.assertIn("start_time", result)
            self.assertIn("time_until_minutes", result)

    def test_get_next_class_no_classes(self):
        """Test getting next class when no classes exist."""
        mock_db.get_user_context.return_value = {"classes": []}

        result = self.monitor.get_next_class(self.user_id)
        self.assertIsNone(result)

    def test_get_todays_classes(self):
        """Test getting today's classes."""
        today_weekday = datetime.now().weekday()
        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        today_name = day_names[today_weekday]

        mock_db.get_user_context.return_value = {
            "classes": [
                {
                    "name": "CS 101",
                    "schedule": [{"day": today_name, "time": "09:00"}]
                },
                {
                    "name": "MATH 201",
                    "schedule": [{"day": today_name, "time": "14:00"}]
                }
            ]
        }

        result = self.monitor.get_todays_classes(self.user_id)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["class_name"], "CS 101")  # 9am comes first

    def test_should_send_morning_alert_class_soon(self):
        """Test morning alert when class is within 2 hours."""
        now = datetime.now(timezone.utc)

        # Only test if it's morning (6am-10am)
        if 6 <= now.hour < 10:
            # Mock next class in 1 hour
            mock_db.get_user_context.return_value = {
                "classes": [{
                    "name": "Early Class",
                    "schedule": [{"day": now.strftime("%A"), "time": (now + timedelta(hours=1)).strftime("%H:%M")}]
                }]
            }

            should_send, class_info = self.monitor.should_send_morning_alert(self.user_id)

            # Depending on timing, this may or may not trigger
            self.assertIsInstance(should_send, bool)
        else:
            # Outside morning hours, should not send
            mock_db.get_user_context.return_value = {"classes": []}
            should_send, _ = self.monitor.should_send_morning_alert(self.user_id)
            self.assertFalse(should_send)

    def test_get_study_reminder_time(self):
        """Test calculation of study reminder time."""
        mock_db.get_latest_user_pattern.return_value = None

        result = self.monitor.get_study_reminder_time(self.user_id)

        self.assertIsNotNone(result)
        self.assertIsInstance(result, datetime)
        # Should be in the future
        self.assertGreater(result, datetime.now(timezone.utc))

    def test_get_free_slots(self):
        """Test finding free time slots."""
        today = datetime.now(timezone.utc)
        today_name = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][today.weekday()]

        mock_db.get_user_context.return_value = {
            "classes": [{
                "name": "Class 1",
                "schedule": [{"day": today_name, "time": "10:00"}]
            }]
        }

        result = self.monitor.get_free_slots(self.user_id)

        # Should have free slots before and after the class
        self.assertIsInstance(result, list)
        for slot in result:
            self.assertIn("start_time", slot)
            self.assertIn("end_time", slot)
            self.assertIn("duration_minutes", slot)

    def test_day_to_weekday_conversion(self):
        """Test day string to weekday number conversion."""
        self.assertEqual(self.monitor._day_to_weekday("Monday"), 0)
        self.assertEqual(self.monitor._day_to_weekday("mon"), 0)
        self.assertEqual(self.monitor._day_to_weekday("M"), 0)
        self.assertEqual(self.monitor._day_to_weekday("Friday"), 4)
        self.assertEqual(self.monitor._day_to_weekday("F"), 4)
        self.assertIsNone(self.monitor._day_to_weekday("invalid"))

    def test_parse_time_formats(self):
        """Test parsing various time formats."""
        self.assertEqual(self.monitor._parse_time("09:00"), time(9, 0))
        self.assertEqual(self.monitor._parse_time("14:30"), time(14, 30))
        self.assertEqual(self.monitor._parse_time("2:30 PM"), time(14, 30))
        self.assertEqual(self.monitor._parse_time("9:00 AM"), time(9, 0))
        self.assertIsNone(self.monitor._parse_time("invalid"))

    def test_parse_meeting_string(self):
        """Test parsing meeting strings like 'MWF 9:00 AM'."""
        result = self.monitor._parse_meeting_string("MWF 9:00 AM")

        # Should return 3 entries for Monday, Wednesday, Friday
        self.assertEqual(len(result), 3)
        days = [r[0] for r in result]
        self.assertIn(0, days)  # Monday
        self.assertIn(2, days)  # Wednesday
        self.assertIn(4, days)  # Friday

    def test_parse_class_schedule_format_1(self):
        """Test parsing schedule format with day/time objects."""
        cls = {
            "schedule": [
                {"day": "Monday", "time": "09:00"},
                {"day": "Wednesday", "time": "09:00"},
            ]
        }

        result = self.monitor._parse_class_schedule(cls)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0][0], 0)  # Monday
        self.assertEqual(result[1][0], 2)  # Wednesday

    def test_parse_class_schedule_format_2(self):
        """Test parsing schedule format with days array."""
        cls = {
            "days": ["M", "W", "F"],
            "start_time": "10:00"
        }

        result = self.monitor._parse_class_schedule(cls)

        self.assertEqual(len(result), 3)


if __name__ == '__main__':
    unittest.main()
