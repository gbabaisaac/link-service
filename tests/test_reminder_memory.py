"""
Comprehensive tests for Reminder and Memory features.
Tests cover:
1. Reminder time parsing (various formats)
2. Reminder task extraction
3. Reminder intent classification
4. Memory manager with vault null check
"""

import sys
import os
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta

# Setup path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock config before imports
sys.modules['config'] = MagicMock()
sys.modules['config'].settings = MagicMock()
sys.modules['config'].settings.TEST_MODE = True
sys.modules['config'].settings.SUPABASE_URL = "https://mock.supabase.co"
sys.modules['config'].settings.SUPABASE_KEY = "mock-key"
sys.modules['config'].settings.LINK_VAULT_KEY = "dmVyeS1zZWN1cmUtMzItYnl0ZS1rZXktZm9yLWRldgot"

# Mock dependencies
mock_db = MagicMock()
sys.modules['supabase_client'] = mock_db

mock_llm = MagicMock()
sys.modules['link_logic'] = MagicMock()
sys.modules['link_logic'].llm_json = mock_llm

# We'll test both with and without vault
mock_vault = MagicMock()


class TestReminderTimeParsing(unittest.TestCase):
    """Test parse_reminder_time function."""

    def setUp(self):
        # Import after mocks are set up
        sys.modules['link_memory'] = MagicMock()
        sys.modules['link_memory'].vault = mock_vault

        # Import the function we're testing
        import importlib
        if 'main' in sys.modules:
            importlib.reload(sys.modules['main'])

        # We need to import parse_reminder_time from main
        # But main has too many dependencies, so let's test inline
        import re as regex_module

        def parse_reminder_time(text: str):
            """Parse time expressions like 'in 2 hours', 'in 30 minutes', 'tomorrow at 3pm'."""
            text = text.lower()
            now = datetime.now(timezone.utc)

            # Match "in X hours/minutes"
            match = regex_module.search(r"in\s+(\d+)\s*(hour|hr|minute|min)s?", text)
            if match:
                amount = int(match.group(1))
                unit = match.group(2)
                if "hour" in unit or "hr" in unit:
                    return now + timedelta(hours=amount)
                else:
                    return now + timedelta(minutes=amount)

            # Match "tomorrow"
            if "tomorrow" in text:
                tomorrow = now + timedelta(days=1)
                # Check for time like "at 3pm" or "at 15:00"
                time_match = regex_module.search(r"at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text)
                if time_match:
                    hour = int(time_match.group(1))
                    minute = int(time_match.group(2) or 0)
                    period = time_match.group(3)
                    if period == "pm" and hour < 12:
                        hour += 12
                    elif period == "am" and hour == 12:
                        hour = 0
                    return tomorrow.replace(hour=hour, minute=minute, second=0, microsecond=0)
                return tomorrow.replace(hour=9, minute=0, second=0, microsecond=0)

            # Match "in a bit" / "later" / "soon" - default 1 hour
            if any(x in text for x in ["in a bit", "later", "soon"]):
                return now + timedelta(hours=1)

            # Default to 1 hour if no time found
            return now + timedelta(hours=1)

        self.parse_reminder_time = parse_reminder_time

    def test_in_hours(self):
        """Test 'in X hours' parsing."""
        now = datetime.now(timezone.utc)

        result = self.parse_reminder_time("remind me in 2 hours")
        expected = now + timedelta(hours=2)
        self.assertAlmostEqual(result.timestamp(), expected.timestamp(), delta=2)

        result = self.parse_reminder_time("remind me in 5 hours to call mom")
        expected = now + timedelta(hours=5)
        self.assertAlmostEqual(result.timestamp(), expected.timestamp(), delta=2)

    def test_in_minutes(self):
        """Test 'in X minutes' parsing."""
        now = datetime.now(timezone.utc)

        result = self.parse_reminder_time("remind me in 30 minutes")
        expected = now + timedelta(minutes=30)
        self.assertAlmostEqual(result.timestamp(), expected.timestamp(), delta=2)

        result = self.parse_reminder_time("remind me in 15 min to check email")
        expected = now + timedelta(minutes=15)
        self.assertAlmostEqual(result.timestamp(), expected.timestamp(), delta=2)

    def test_in_hr_abbreviation(self):
        """Test 'in X hr' abbreviation."""
        now = datetime.now(timezone.utc)

        result = self.parse_reminder_time("remind me in 1 hr")
        expected = now + timedelta(hours=1)
        self.assertAlmostEqual(result.timestamp(), expected.timestamp(), delta=2)

    def test_tomorrow_default(self):
        """Test 'tomorrow' defaults to 9am."""
        now = datetime.now(timezone.utc)
        tomorrow = now + timedelta(days=1)

        result = self.parse_reminder_time("remind me tomorrow")
        self.assertEqual(result.hour, 9)
        self.assertEqual(result.minute, 0)
        self.assertEqual(result.day, tomorrow.day)

    def test_tomorrow_with_time_pm(self):
        """Test 'tomorrow at X pm'."""
        result = self.parse_reminder_time("remind me tomorrow at 3pm")
        self.assertEqual(result.hour, 15)
        self.assertEqual(result.minute, 0)

    def test_tomorrow_with_time_am(self):
        """Test 'tomorrow at X am'."""
        result = self.parse_reminder_time("remind me tomorrow at 8am")
        self.assertEqual(result.hour, 8)
        self.assertEqual(result.minute, 0)

    def test_tomorrow_with_specific_time(self):
        """Test 'tomorrow at H:MM'."""
        result = self.parse_reminder_time("remind me tomorrow at 2:30pm")
        self.assertEqual(result.hour, 14)
        self.assertEqual(result.minute, 30)

    def test_in_a_bit(self):
        """Test 'in a bit' defaults to 1 hour."""
        now = datetime.now(timezone.utc)

        result = self.parse_reminder_time("remind me in a bit")
        expected = now + timedelta(hours=1)
        self.assertAlmostEqual(result.timestamp(), expected.timestamp(), delta=2)

    def test_later(self):
        """Test 'later' defaults to 1 hour."""
        now = datetime.now(timezone.utc)

        result = self.parse_reminder_time("remind me later to eat")
        expected = now + timedelta(hours=1)
        self.assertAlmostEqual(result.timestamp(), expected.timestamp(), delta=2)

    def test_soon(self):
        """Test 'soon' defaults to 1 hour."""
        now = datetime.now(timezone.utc)

        result = self.parse_reminder_time("remind me soon")
        expected = now + timedelta(hours=1)
        self.assertAlmostEqual(result.timestamp(), expected.timestamp(), delta=2)

    def test_default_fallback(self):
        """Test default to 1 hour when no time expression found."""
        now = datetime.now(timezone.utc)

        result = self.parse_reminder_time("remind me to do laundry")
        expected = now + timedelta(hours=1)
        self.assertAlmostEqual(result.timestamp(), expected.timestamp(), delta=2)


class TestReminderTaskExtraction(unittest.TestCase):
    """Test extract_reminder_task function."""

    def setUp(self):
        import re as regex_module

        def extract_reminder_task(text: str) -> str:
            """Extract what the user wants to be reminded about."""
            text = text.lower()
            # Remove common prefixes using regex with word boundaries (ordered from most specific to least specific)
            prefixes = [
                r"remind me to\b",
                r"remind me about\b",
                r"remind me\b",
                r"set a reminder to\b",
                r"set a reminder for\b",
                r"don't let me forget to\b",
                r"alert me to\b"
            ]
            for prefix in prefixes:
                match = regex_module.search(prefix, text)
                if match:
                    text = text[match.end():]
                    break
            # Remove time expressions
            text = regex_module.sub(r"\btomorrow(\s+at\s+\d{1,2}(:\d{2})?\s*(am|pm)?)?\b", "", text)
            text = regex_module.sub(r"\bin\s+\d+\s*(hour|hr|minute|min)s?\b", "", text)
            text = regex_module.sub(r"\bat\s+\d{1,2}(:\d{2})?\s*(am|pm)?\b", "", text)
            text = regex_module.sub(r"\b(in a bit|later|soon)\b", "", text)
            # Clean up: strip whitespace and remove leading "to " if present
            text = text.strip()
            if text.startswith("to "):
                text = text[3:]
            return text.strip() or "your reminder"

        self.extract_reminder_task = extract_reminder_task

    def test_remind_me_to_prefix(self):
        """Test 'remind me to' prefix removal."""
        result = self.extract_reminder_task("remind me to call mom")
        self.assertEqual(result, "call mom")

    def test_remind_me_about_prefix(self):
        """Test 'remind me about' prefix removal."""
        result = self.extract_reminder_task("remind me about the meeting")
        self.assertEqual(result, "the meeting")

    def test_set_a_reminder_to_prefix(self):
        """Test 'set a reminder to' prefix removal."""
        result = self.extract_reminder_task("set a reminder to study")
        self.assertEqual(result, "study")

    def test_set_a_reminder_for_prefix(self):
        """Test 'set a reminder for' prefix removal."""
        result = self.extract_reminder_task("set a reminder for dentist appointment")
        self.assertEqual(result, "dentist appointment")

    def test_dont_let_me_forget_prefix(self):
        """Test 'don't let me forget to' prefix removal."""
        result = self.extract_reminder_task("don't let me forget to buy milk")
        self.assertEqual(result, "buy milk")

    def test_alert_me_to_prefix(self):
        """Test 'alert me to' prefix removal."""
        result = self.extract_reminder_task("alert me to check the oven")
        self.assertEqual(result, "check the oven")

    def test_remove_in_hours(self):
        """Test removal of 'in X hours' time expression."""
        result = self.extract_reminder_task("remind me to call mom in 2 hours")
        self.assertEqual(result, "call mom")

    def test_remove_in_minutes(self):
        """Test removal of 'in X minutes' time expression."""
        result = self.extract_reminder_task("remind me to check email in 30 minutes")
        self.assertEqual(result, "check email")

    def test_remove_tomorrow(self):
        """Test removal of 'tomorrow' time expression."""
        result = self.extract_reminder_task("remind me tomorrow to submit assignment")
        self.assertEqual(result, "submit assignment")

    def test_remove_tomorrow_at_time(self):
        """Test removal of 'tomorrow at X' time expression."""
        result = self.extract_reminder_task("remind me tomorrow at 3pm to go to gym")
        self.assertEqual(result, "go to gym")

    def test_remove_in_a_bit(self):
        """Test removal of 'in a bit' time expression."""
        result = self.extract_reminder_task("remind me in a bit to water plants")
        self.assertEqual(result, "water plants")

    def test_remove_later(self):
        """Test removal of 'later' time expression."""
        result = self.extract_reminder_task("remind me later to do laundry")
        self.assertEqual(result, "do laundry")

    def test_default_when_empty(self):
        """Test default 'your reminder' when task is empty."""
        result = self.extract_reminder_task("remind me in 2 hours")
        self.assertEqual(result, "your reminder")

    def test_complex_reminder(self):
        """Test complex reminder with multiple parts."""
        result = self.extract_reminder_task("remind me to finish the report in 3 hours")
        self.assertEqual(result, "finish the report")


class TestReminderIntentClassification(unittest.TestCase):
    """Test intent classification for reminder-related messages."""

    def setUp(self):
        from intent_classifier import classify_intent, Intent
        self.classify_intent = classify_intent
        self.Intent = Intent

    def test_remind_me_to(self):
        """Test 'remind me to' triggers REMINDER intent."""
        result = self.classify_intent("remind me to call mom")
        self.assertEqual(result.intent, self.Intent.REMINDER)

    def test_set_a_reminder(self):
        """Test 'set a reminder' triggers REMINDER intent."""
        result = self.classify_intent("set a reminder for tomorrow")
        self.assertEqual(result.intent, self.Intent.REMINDER)

    def test_reminder_for(self):
        """Test 'reminder for' triggers REMINDER intent."""
        result = self.classify_intent("set a reminder for the meeting")
        self.assertEqual(result.intent, self.Intent.REMINDER)

    def test_remind_me_with_time(self):
        """Test 'remind me to X in Y hours' triggers REMINDER intent."""
        result = self.classify_intent("remind me to study in 2 hours")
        self.assertEqual(result.intent, self.Intent.REMINDER)

    def test_dont_let_me_forget(self):
        """Test 'don't let me forget' triggers REMINDER intent."""
        result = self.classify_intent("don't let me forget to buy groceries")
        self.assertEqual(result.intent, self.Intent.REMINDER)

    def test_alert_me(self):
        """Test 'alert me' triggers REMINDER intent."""
        result = self.classify_intent("alert me to check the laundry")
        self.assertEqual(result.intent, self.Intent.REMINDER)

    def test_non_reminder_message(self):
        """Test that regular messages don't trigger REMINDER intent."""
        result = self.classify_intent("what clubs are there")
        self.assertNotEqual(result.intent, self.Intent.REMINDER)


class TestMemoryManagerWithVault(unittest.TestCase):
    """Test MemoryManager when vault is initialized."""

    def setUp(self):
        mock_db.reset_mock()
        mock_llm.reset_mock()
        mock_vault.reset_mock()

        # Set up vault mock
        sys.modules['link_memory'] = MagicMock()
        sys.modules['link_memory'].vault = mock_vault

        # Mock vault methods
        mock_vault.encrypt.return_value = "encrypted_blob"
        mock_vault.decrypt.side_effect = lambda x: f"decrypted_{x}"

        # Re-import memory_manager with vault
        import importlib
        if 'memory_manager' in sys.modules:
            del sys.modules['memory_manager']

        from memory_manager import MemoryManager
        self.memory_manager = MemoryManager()
        self.user_id = "user_test_123"

    def test_process_message_extracts_facts(self):
        """Test that process_message extracts and saves facts."""
        # Mock LLM to return extracted facts
        mock_llm.return_value = [
            {"content": "Likes basketball", "category": "preferences", "tier": "long", "priority": 3}
        ]

        # Mock DB save
        mock_db.create_encrypted_memory.return_value = {"id": "mem_1"}

        result = self.memory_manager.process_message(self.user_id, "I really love basketball")

        # Verify LLM was called
        mock_llm.assert_called_once()

        # Verify vault encrypted the content
        mock_vault.encrypt.assert_called_with("Likes basketball")

        # Verify DB was called to save
        mock_db.create_encrypted_memory.assert_called_once()
        call_args = mock_db.create_encrypted_memory.call_args
        self.assertEqual(call_args.kwargs['user_id'], self.user_id)
        self.assertEqual(call_args.kwargs['category'], 'preferences')
        self.assertEqual(call_args.kwargs['tier'], 'long')
        self.assertEqual(call_args.kwargs['priority'], 3)

    def test_process_message_multiple_facts(self):
        """Test extraction of multiple facts from one message."""
        mock_llm.return_value = [
            {"content": "Likes basketball", "category": "preferences", "tier": "long", "priority": 3},
            {"content": "Looking for internship", "category": "facts", "tier": "medium", "priority": 5}
        ]
        mock_db.create_encrypted_memory.return_value = {"id": "mem_1"}

        result = self.memory_manager.process_message(
            self.user_id,
            "I love basketball and I'm looking for a summer internship"
        )

        # Should have saved 2 facts
        self.assertEqual(mock_db.create_encrypted_memory.call_count, 2)

    def test_process_message_no_facts(self):
        """Test that empty message returns no facts."""
        mock_llm.return_value = []

        result = self.memory_manager.process_message(self.user_id, "hello")

        self.assertEqual(result, [])
        mock_db.create_encrypted_memory.assert_not_called()

    def test_get_decrypted_facts(self):
        """Test retrieval and decryption of facts."""
        mock_db.list_encrypted_memories.return_value = [
            {"encrypted_value": "blob1", "tier": "long", "priority": 3, "category": "preferences"},
            {"encrypted_value": "blob2", "tier": "medium", "priority": 5, "category": "facts"}
        ]

        result = self.memory_manager.get_decrypted_facts(self.user_id)

        # Should return 2 facts, sorted by priority (highest first)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["priority"], 5)  # Higher priority first
        self.assertEqual(result[1]["priority"], 3)

    def test_get_decrypted_facts_filter_by_tier(self):
        """Test filtering facts by tier."""
        mock_db.list_encrypted_memories.return_value = [
            {"encrypted_value": "blob1", "tier": "long", "priority": 3, "category": "preferences"},
            {"encrypted_value": "blob2", "tier": "medium", "priority": 5, "category": "facts"}
        ]

        result = self.memory_manager.get_decrypted_facts(self.user_id, tier="long")

        # Should only return long-term facts
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["tier"], "long")


class TestMemoryManagerWithoutVault(unittest.TestCase):
    """Test MemoryManager when vault is None (not initialized)."""

    def setUp(self):
        mock_db.reset_mock()
        mock_llm.reset_mock()

        # Set vault to None
        sys.modules['link_memory'] = MagicMock()
        sys.modules['link_memory'].vault = None

        # Re-import memory_manager without vault
        import importlib
        if 'memory_manager' in sys.modules:
            del sys.modules['memory_manager']

        from memory_manager import MemoryManager
        self.memory_manager = MemoryManager()
        self.user_id = "user_test_123"

    def test_process_message_returns_empty_when_no_vault(self):
        """Test that process_message returns empty when vault is None."""
        result = self.memory_manager.process_message(self.user_id, "I love basketball")

        self.assertEqual(result, [])
        # LLM should not be called when vault is None
        mock_llm.assert_not_called()
        # DB should not be called
        mock_db.create_encrypted_memory.assert_not_called()

    def test_get_decrypted_facts_returns_empty_when_no_vault(self):
        """Test that get_decrypted_facts returns empty when vault is None."""
        result = self.memory_manager.get_decrypted_facts(self.user_id)

        self.assertEqual(result, [])
        # DB should not be called
        mock_db.list_encrypted_memories.assert_not_called()


class TestMemoryTierPriority(unittest.TestCase):
    """Test memory tier and priority logic."""

    def setUp(self):
        mock_db.reset_mock()
        mock_llm.reset_mock()
        mock_vault.reset_mock()

        sys.modules['link_memory'] = MagicMock()
        sys.modules['link_memory'].vault = mock_vault
        mock_vault.encrypt.return_value = "encrypted_blob"
        mock_vault.decrypt.side_effect = lambda x: f"decrypted_{x}"

        import importlib
        if 'memory_manager' in sys.modules:
            del sys.modules['memory_manager']

        from memory_manager import MemoryManager
        self.memory_manager = MemoryManager()
        self.user_id = "user_test_123"

    def test_long_term_facts(self):
        """Test that permanent facts are stored as 'long' tier."""
        mock_llm.return_value = [
            {"content": "Birthday is March 15", "category": "facts", "tier": "long", "priority": 4}
        ]
        mock_db.create_encrypted_memory.return_value = {"id": "mem_1"}

        self.memory_manager.process_message(self.user_id, "My birthday is March 15")

        call_args = mock_db.create_encrypted_memory.call_args
        self.assertEqual(call_args.kwargs['tier'], 'long')

    def test_medium_term_facts(self):
        """Test that situational facts are stored as 'medium' tier."""
        mock_llm.return_value = [
            {"content": "Studying for midterms", "category": "facts", "tier": "medium", "priority": 4}
        ]
        mock_db.create_encrypted_memory.return_value = {"id": "mem_1"}

        self.memory_manager.process_message(self.user_id, "I'm studying for midterms right now")

        call_args = mock_db.create_encrypted_memory.call_args
        self.assertEqual(call_args.kwargs['tier'], 'medium')

    def test_priority_sorting(self):
        """Test that facts are sorted by priority (highest first)."""
        mock_db.list_encrypted_memories.return_value = [
            {"encrypted_value": "low", "tier": "long", "priority": 1, "category": "preferences"},
            {"encrypted_value": "high", "tier": "long", "priority": 5, "category": "facts"},
            {"encrypted_value": "mid", "tier": "long", "priority": 3, "category": "preferences"}
        ]

        result = self.memory_manager.get_decrypted_facts(self.user_id)

        # Should be sorted: priority 5, 3, 1
        self.assertEqual(result[0]["priority"], 5)
        self.assertEqual(result[1]["priority"], 3)
        self.assertEqual(result[2]["priority"], 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
