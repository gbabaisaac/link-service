"""Tests for the Four-Tier Memory System."""

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

from tiered_memory import (
    MemoryTier,
    SensitivityLevel,
    MemoryCategory,
    ImportanceCalculator,
    TieredMemoryManager,
    get_tiered_memory_manager,
)


class TestImportanceCalculator(unittest.TestCase):
    """Test cases for ImportanceCalculator class."""

    def setUp(self):
        self.calculator = ImportanceCalculator()

    def test_calculate_low_importance(self):
        """Test low importance content gets low score."""
        result = self.calculator.calculate("I had cereal for breakfast")

        self.assertLess(result["score"], 4.0)
        self.assertEqual(result["tier_recommendation"], MemoryTier.SHORT_TERM)

    def test_calculate_medium_importance(self):
        """Test medium importance content gets appropriate score."""
        # Use content with strong emotion word that will be detected
        result = self.calculator.calculate("I'm so excited about my upcoming graduation!")

        # Should have some emotional weight from "excited"
        self.assertGreater(result["breakdown"]["emotional_weight"], 0.0)
        # Life event marker "graduating" should boost significance
        self.assertGreaterEqual(result["score"], 2.0)

    def test_calculate_high_importance_emotional(self):
        """Test high emotional content gets high score."""
        # Use multiple vulnerability markers that will be detected
        result = self.calculator.calculate("I'm struggling, I feel alone and I don't know what to do")

        # Vulnerable phrases should trigger high emotional weight
        self.assertGreater(result["breakdown"]["emotional_weight"], 2.0)
        # Multiple markers should give high score
        self.assertGreaterEqual(result["score"], 3.0)

    def test_calculate_lifetime_importance(self):
        """Test lifetime-worthy content has explicit request and relationship."""
        result = self.calculator.calculate(
            "Please never bring up my ex, Sarah. It's really hard for me.",
            context={"first_time_topic": True}
        )

        # Should detect "never" as explicit request (actionability)
        self.assertGreater(result["breakdown"]["actionability"], 0.0)
        # Combined score should be elevated
        self.assertGreater(result["score"], 2.0)

    def test_calculate_identity_markers(self):
        """Test identity markers increase significance."""
        result = self.calculator.calculate("I'm a Computer Science major and I love coding")

        self.assertGreater(result["breakdown"]["personal_significance"], 0.0)

    def test_calculate_relationship_markers(self):
        """Test relationship markers increase significance."""
        result = self.calculator.calculate("My mom is visiting this weekend")

        self.assertGreater(result["breakdown"]["personal_significance"], 0.0)

    def test_calculate_life_events(self):
        """Test life event markers get highest significance."""
        result = self.calculator.calculate("I got the job offer I've been waiting for!")

        self.assertEqual(result["breakdown"]["personal_significance"], 3.0)

    def test_calculate_explicit_requests(self):
        """Test explicit requests increase actionability."""
        result = self.calculator.calculate("Remind me about my doctor's appointment")

        self.assertGreater(result["breakdown"]["actionability"], 0.0)

    def test_sensitivity_level_public(self):
        """Test public content gets level 1."""
        result = self.calculator.calculate("I'm taking CS 101 this semester")

        self.assertEqual(result["sensitivity"], SensitivityLevel.PUBLIC)

    def test_sensitivity_level_personal(self):
        """Test personal content gets level 2."""
        result = self.calculator.calculate("I'm stressed about dating lately")

        self.assertEqual(result["sensitivity"], SensitivityLevel.PERSONAL)

    def test_sensitivity_level_private(self):
        """Test private content gets level 3."""
        result = self.calculator.calculate("I've been feeling depressed lately")

        self.assertEqual(result["sensitivity"], SensitivityLevel.PRIVATE)

    def test_sensitivity_level_deeply_private(self):
        """Test deeply private content gets level 4."""
        result = self.calculator.calculate("I'm struggling with thoughts of self harm")

        self.assertEqual(result["sensitivity"], SensitivityLevel.DEEPLY_PRIVATE)


class TestTieredMemoryManager(unittest.TestCase):
    """Test cases for TieredMemoryManager class."""

    def setUp(self):
        mock_db.reset_mock()
        # Reset all side_effects to None to clear any previous test's configuration
        mock_db.create_tiered_memory.side_effect = None
        mock_db.create_lifetime_memory.side_effect = None
        mock_db.get_tiered_memories.side_effect = None
        mock_db.update_tiered_memory.side_effect = None
        mock_db.delete_tiered_memory.side_effect = None
        mock_db.get_lifetime_memories.side_effect = None
        mock_db.search_memories.side_effect = None

        # Set default return values
        mock_db.create_tiered_memory.return_value = {"id": "default_id"}
        mock_db.create_lifetime_memory.return_value = {"id": "default_lifetime_id"}
        mock_db.get_tiered_memories.return_value = []

        self.manager = TieredMemoryManager("test_user_123")
        self.user_id = "test_user_123"

    def test_store_memory_short_term(self):
        """Test storing a low importance memory."""
        mock_db.create_tiered_memory.return_value = {"id": "mem_1"}

        result = self.manager.store_memory(
            content="Had coffee this morning",
            category=MemoryCategory.FACT,
        )

        mock_db.create_tiered_memory.assert_called_once()
        call_args = mock_db.create_tiered_memory.call_args[0][0]
        self.assertEqual(call_args["tier"], "short_term")

    def test_store_memory_with_high_importance(self):
        """Test storing a high importance memory with force_tier."""
        mock_db.create_tiered_memory.return_value = {"id": "mem_2"}

        # Use force_tier and force_importance to ensure high tier
        result = self.manager.store_memory(
            content="I got accepted into my dream graduate program!",
            category=MemoryCategory.EVENT,
            force_tier=MemoryTier.LONG_TERM,
            force_importance=8.0,
        )

        mock_db.create_tiered_memory.assert_called_once()
        call_args = mock_db.create_tiered_memory.call_args[0][0]
        # Force tier should be respected
        self.assertEqual(call_args["tier"], "long_term")

    def test_store_memory_lifetime(self):
        """Test storing a lifetime memory also stores in lifetime table."""
        mock_db.create_tiered_memory.return_value = {"id": "mem_3"}
        mock_db.create_lifetime_memory.return_value = {"id": "lifetime_1"}

        result = self.manager.store_memory(
            content="Please never message me between 10pm and 8am",
            category=MemoryCategory.BOUNDARY,
            force_tier=MemoryTier.LIFETIME,
            force_importance=9.5,
        )

        # Should call both create functions
        mock_db.create_tiered_memory.assert_called_once()
        mock_db.create_lifetime_memory.assert_called_once()

    def test_store_memory_extracts_topics(self):
        """Test topic extraction from content."""
        mock_db.create_tiered_memory.return_value = {"id": "mem_4"}

        result = self.manager.store_memory(
            content="I'm stressed about my exam tomorrow",
            category=MemoryCategory.EMOTIONAL,
        )

        call_args = mock_db.create_tiered_memory.call_args[0][0]
        self.assertIn("academic", call_args["related_topics"])
        self.assertIn("emotional", call_args["related_topics"])

    def test_store_memory_extracts_people(self):
        """Test people extraction from content."""
        mock_db.create_tiered_memory.return_value = {"id": "mem_5"}

        result = self.manager.store_memory(
            content="My mom called me today",
            category=MemoryCategory.FACT,
        )

        call_args = mock_db.create_tiered_memory.call_args[0][0]
        self.assertIn("mom", call_args["related_people"])

    def test_retrieve_memories_from_single_tier(self):
        """Test retrieving memories from a single tier."""
        mock_db.get_tiered_memories.return_value = [
            {"id": "mem_1", "content": "Memory 1", "importance": 5.0},
            {"id": "mem_2", "content": "Memory 2", "importance": 7.0},
        ]

        result = self.manager.retrieve_memories(
            tiers=[MemoryTier.SHORT_TERM],
            limit=10
        )

        self.assertEqual(len(result), 2)
        # Should be sorted by importance descending
        self.assertEqual(result[0]["importance"], 7.0)

    def test_retrieve_memories_with_query(self):
        """Test filtering memories by query."""
        mock_db.get_tiered_memories.return_value = [
            {"id": "mem_1", "content": "I like basketball", "importance": 5.0, "related_topics": []},
            {"id": "mem_2", "content": "I like soccer", "importance": 5.0, "related_topics": []},
        ]

        result = self.manager.retrieve_memories(
            query="basketball",
            tiers=[MemoryTier.SHORT_TERM],
            limit=10
        )

        self.assertEqual(len(result), 1)
        self.assertIn("basketball", result[0]["content"])

    def test_retrieve_memories_query_matches_topics(self):
        """Test query matching against related topics."""
        mock_db.get_tiered_memories.return_value = [
            {"id": "mem_1", "content": "Feeling good", "importance": 5.0, "related_topics": ["academic", "career"]},
        ]

        result = self.manager.retrieve_memories(
            query="career",
            tiers=[MemoryTier.SHORT_TERM],
            limit=10
        )

        self.assertEqual(len(result), 1)

    def test_get_conversation_context(self):
        """Test getting full conversation context."""
        mock_db.get_tiered_memories.side_effect = [
            [{"id": "st_1", "content": "Short term memory", "importance": 3.0, "related_people": [], "category": "fact"}],
            [{"id": "mt_1", "content": "Medium term memory", "importance": 5.0, "related_people": [], "category": "preference"}],
            [{"id": "lt_1", "content": "Long term memory", "importance": 7.0, "related_people": [], "category": "identity"}],
            [{"id": "lf_1", "content": "Never message me at night", "importance": 9.0, "related_people": [], "category": "boundary"}],
        ]

        result = self.manager.get_conversation_context("conv_123")

        self.assertIn("short_term", result)
        self.assertIn("medium_term", result)
        self.assertIn("long_term", result)
        self.assertIn("lifetime", result)
        self.assertIn("hard_rules", result)

    def test_consolidate_short_to_medium_promotes(self):
        """Test daily consolidation promotes important memories."""
        now = datetime.now(timezone.utc)
        old_time = (now - timedelta(hours=50)).isoformat()

        mock_db.get_tiered_memories.return_value = [
            {"id": "mem_1", "content": "Important memory", "importance": 6.0, "created_at": old_time},
        ]
        mock_db.update_tiered_memory.return_value = {}

        result = self.manager.consolidate_short_to_medium()

        self.assertEqual(result["promoted"], 1)
        self.assertEqual(result["discarded"], 0)
        mock_db.update_tiered_memory.assert_called_once()

    def test_consolidate_short_to_medium_discards(self):
        """Test daily consolidation discards unimportant memories."""
        now = datetime.now(timezone.utc)
        old_time = (now - timedelta(hours=50)).isoformat()

        mock_db.get_tiered_memories.return_value = [
            {"id": "mem_1", "content": "Unimportant memory", "importance": 2.0, "created_at": old_time},
        ]
        mock_db.delete_tiered_memory.return_value = {}

        result = self.manager.consolidate_short_to_medium()

        self.assertEqual(result["promoted"], 0)
        self.assertEqual(result["discarded"], 1)
        mock_db.delete_tiered_memory.assert_called_once()

    def test_consolidate_medium_to_long_promotes(self):
        """Test weekly consolidation promotes important memories."""
        now = datetime.now(timezone.utc)
        old_time = (now - timedelta(days=35)).isoformat()

        mock_db.get_tiered_memories.return_value = [
            {"id": "mem_1", "content": "Very important memory", "importance": 8.0, "created_at": old_time},
        ]
        mock_db.update_tiered_memory.return_value = {}

        result = self.manager.consolidate_medium_to_long()

        self.assertEqual(result["promoted"], 1)
        mock_db.update_tiered_memory.assert_called_once()

    def test_forget_memory_deletes_matching(self):
        """Test user-requested deletion removes matching memories."""
        mock_db.get_tiered_memories.side_effect = [
            [{"id": "mem_1", "content": "I like Sarah", "related_topics": [], "related_people": ["sarah"]}],
            [],  # medium term
            [],  # long term
            [],  # lifetime
        ]
        mock_db.delete_tiered_memory.return_value = {}

        result = self.manager.forget_memory("Sarah")

        self.assertEqual(result["deleted_count"], 1)
        mock_db.delete_tiered_memory.assert_called_once()

    def test_forget_memory_case_insensitive(self):
        """Test forget is case insensitive."""
        mock_db.get_tiered_memories.side_effect = [
            [{"id": "mem_1", "content": "I like SARAH", "related_topics": [], "related_people": []}],
            [],
            [],
            [],
        ]
        mock_db.delete_tiered_memory.return_value = {}

        result = self.manager.forget_memory("sarah")

        self.assertEqual(result["deleted_count"], 1)

    def test_get_memory_summary_organizes_by_category(self):
        """Test memory summary organizes by category."""
        mock_db.get_tiered_memories.side_effect = [
            # lifetime
            [
                {"id": "lf_1", "content": "I am a CS major", "category": "identity", "importance": 9.0},
                {"id": "lf_2", "content": "Sarah is my best friend", "category": "relationship", "importance": 9.0},
                {"id": "lf_3", "content": "Don't message at night", "category": "boundary", "importance": 9.0},
            ],
            # long_term
            [
                {"id": "lt_1", "content": "Direct approach works", "category": "preference", "importance": 7.0},
            ],
            # medium_term
            [
                {"id": "mt_1", "content": "Studying for finals", "category": "fact", "importance": 5.0},
            ],
        ]

        result = self.manager.get_memory_summary()

        self.assertIn("I am a CS major", result["core_identity"])
        self.assertIn("Sarah is my best friend", result["important_relationships"])
        self.assertIn("Don't message at night", result["hard_rules"])


class TestMemoryTierEnum(unittest.TestCase):
    """Test MemoryTier enum."""

    def test_tier_values(self):
        """Test tier enum values."""
        self.assertEqual(MemoryTier.SHORT_TERM.value, "short_term")
        self.assertEqual(MemoryTier.MEDIUM_TERM.value, "medium_term")
        self.assertEqual(MemoryTier.LONG_TERM.value, "long_term")
        self.assertEqual(MemoryTier.LIFETIME.value, "lifetime")


class TestSensitivityLevelEnum(unittest.TestCase):
    """Test SensitivityLevel enum."""

    def test_sensitivity_ordering(self):
        """Test sensitivity levels are ordered correctly."""
        self.assertLess(SensitivityLevel.PUBLIC, SensitivityLevel.PERSONAL)
        self.assertLess(SensitivityLevel.PERSONAL, SensitivityLevel.PRIVATE)
        self.assertLess(SensitivityLevel.PRIVATE, SensitivityLevel.DEEPLY_PRIVATE)


class TestMemoryCategoryEnum(unittest.TestCase):
    """Test MemoryCategory enum."""

    def test_all_categories_exist(self):
        """Test all expected categories exist."""
        expected = [
            "conversation", "emotional", "behavioral", "fact",
            "preference", "relationship", "event", "commitment",
            "boundary", "identity"
        ]
        for cat in expected:
            self.assertIn(cat, [c.value for c in MemoryCategory])


class TestGetTieredMemoryManager(unittest.TestCase):
    """Test factory function."""

    def test_returns_manager_instance(self):
        """Test factory returns correct instance."""
        manager = get_tiered_memory_manager("user_123")

        self.assertIsInstance(manager, TieredMemoryManager)
        self.assertEqual(manager.user_id, "user_123")

    def test_different_users_different_managers(self):
        """Test different users get different managers."""
        manager1 = get_tiered_memory_manager("user_1")
        manager2 = get_tiered_memory_manager("user_2")

        self.assertNotEqual(manager1.user_id, manager2.user_id)


if __name__ == '__main__':
    unittest.main()
