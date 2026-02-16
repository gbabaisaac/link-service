"""Tests for the Friend Graph module."""

import sys
import os
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

# Setup path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock dependencies
sys.modules['config'] = MagicMock()
sys.modules['config'].settings = MagicMock()
sys.modules['config'].settings.TEST_MODE = True

mock_db = MagicMock()
sys.modules['supabase_client'] = mock_db

from friend_graph import FriendGraph


class TestFriendGraph(unittest.TestCase):
    """Test cases for FriendGraph class."""

    def setUp(self):
        mock_db.reset_mock()
        # Reset side_effect for all commonly used functions
        mock_db.get_user_connections.side_effect = None
        mock_db.get_profile.side_effect = None
        mock_db.get_user_context.side_effect = None
        mock_db.get_classmates.side_effect = None
        mock_db.get_profiles.side_effect = None
        mock_db.get_connection_between.side_effect = None

        self.graph = FriendGraph()
        self.user_id = "test_user_123"

    def test_get_connections_direct(self):
        """Test getting direct connections."""
        mock_db.get_user_connections.return_value = [
            {
                "id": "conn_1",
                "user_a": self.user_id,
                "user_b": "friend_1",
                "connection_type": "friend",
                "strength": 0.8,
            },
            {
                "id": "conn_2",
                "user_a": "friend_2",
                "user_b": self.user_id,
                "connection_type": "classmate",
                "strength": 0.6,
            },
        ]

        def mock_get_profile(user_id, enforce_public=True):
            profiles = {
                "friend_1": {"id": "friend_1", "first_name": "Alice", "major": "CS"},
                "friend_2": {"id": "friend_2", "first_name": "Bob", "major": "Math"},
            }
            return profiles.get(user_id)

        mock_db.get_profile.side_effect = mock_get_profile

        result = self.graph.get_connections(self.user_id, depth=1)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["depth"], 1)
        self.assertIn("profile", result[0])

    def test_get_connections_second_degree(self):
        """Test getting second degree connections (friends of friends)."""
        # Direct connections
        mock_db.get_user_connections.side_effect = [
            # User's direct connections
            [{"id": "conn_1", "user_a": self.user_id, "user_b": "friend_1", "strength": 0.8}],
            # Friend's connections
            [{"id": "conn_2", "user_a": "friend_1", "user_b": "fof_1", "strength": 0.7}],
        ]

        mock_db.get_profile.side_effect = [
            {"id": "friend_1", "first_name": "Alice"},
            {"id": "fof_1", "first_name": "Charlie"},
        ]

        result = self.graph.get_connections(self.user_id, depth=2)

        # Should have both direct and second-degree connections
        depths = [c["depth"] for c in result]
        self.assertIn(1, depths)
        self.assertIn(2, depths)

    def test_find_common_connections(self):
        """Test finding common connections between two users."""
        mock_db.get_user_connections.side_effect = [
            # User A's connections
            [
                {"user_a": "user_a", "user_b": "common_1"},
                {"user_a": "user_a", "user_b": "only_a"},
            ],
            # User B's connections
            [
                {"user_a": "user_b", "user_b": "common_1"},
                {"user_a": "only_b", "user_b": "user_b"},
            ],
        ]

        mock_db.get_profile.return_value = {"id": "common_1", "first_name": "Common"}

        result = self.graph.find_common_connections("user_a", "user_b")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["user_id"], "common_1")

    def test_get_relationship_strength_direct(self):
        """Test relationship strength for direct connections."""
        mock_db.get_connection_between.return_value = {
            "strength": 0.85
        }

        result = self.graph.get_relationship_strength("user_a", "user_b")

        self.assertEqual(result, 0.85)

    def test_get_relationship_strength_indirect(self):
        """Test relationship strength through common connections."""
        mock_db.get_connection_between.return_value = None

        with patch.object(self.graph, 'find_common_connections') as mock_common:
            mock_common.return_value = [{"user_id": "common_1"}, {"user_id": "common_2"}]

            with patch.object(self.graph, '_get_shared_classes') as mock_classes:
                mock_classes.return_value = []

                with patch.object(self.graph, '_get_shared_organizations') as mock_orgs:
                    mock_orgs.return_value = []

                    result = self.graph.get_relationship_strength("user_a", "user_b")

                    # Should have some strength due to common connections
                    self.assertGreater(result, 0)
                    self.assertLessEqual(result, 0.5)

    def test_get_relationship_strength_none(self):
        """Test relationship strength when no connection exists."""
        mock_db.get_connection_between.return_value = None

        with patch.object(self.graph, 'find_common_connections') as mock_common:
            mock_common.return_value = []

            with patch.object(self.graph, '_get_shared_classes') as mock_classes:
                mock_classes.return_value = []

                with patch.object(self.graph, '_get_shared_organizations') as mock_orgs:
                    mock_orgs.return_value = []

                    result = self.graph.get_relationship_strength("user_a", "user_b")

                    self.assertEqual(result, 0.0)

    def test_suggest_connections_classmates(self):
        """Test connection suggestions from classmates."""
        mock_db.get_user_connections.return_value = []  # No existing connections
        mock_db.get_user_context.return_value = {
            "profile": {
                "interests": ["gaming", "music"],
                "major": "Computer Science",
                "university_id": "uni_1",
            },
            "clubs": [],
        }
        mock_db.get_classmates.return_value = ["classmate_1", "classmate_2"]

        def mock_get_profile(user_id, enforce_public=True):
            profiles = {
                "classmate_1": {"id": "classmate_1", "first_name": "Alice", "major": "CS"},
                "classmate_2": {"id": "classmate_2", "first_name": "Bob", "major": "CS"},
            }
            return profiles.get(user_id)

        mock_db.get_profile.side_effect = mock_get_profile
        mock_db.get_profiles.return_value = []

        result = self.graph.suggest_connections(self.user_id, limit=5)

        # Should suggest classmates
        self.assertGreater(len(result), 0)
        for s in result:
            self.assertIn("score", s)
            self.assertIn("reason", s)

    def test_create_connection_new(self):
        """Test creating a new connection."""
        mock_db.get_connection_between.return_value = None
        mock_db.create_user_connection.return_value = {
            "id": "new_conn",
            "user_a": "user_a",
            "user_b": "user_b",
            "strength": 0.5,
        }

        result = self.graph.create_connection("user_a", "user_b", "friend")

        mock_db.create_user_connection.assert_called_once()
        self.assertEqual(result["strength"], 0.5)

    def test_create_connection_existing(self):
        """Test updating existing connection."""
        mock_db.get_connection_between.return_value = {
            "id": "existing_conn",
            "strength": 0.7,
        }
        mock_db.update_connection_strength.return_value = {
            "id": "existing_conn",
            "strength": 0.8,
        }

        result = self.graph.create_connection("user_a", "user_b", "friend")

        mock_db.update_connection_strength.assert_called_once()

    def test_update_interaction_message(self):
        """Test updating connection strength from message interaction."""
        mock_db.get_connection_between.return_value = {
            "id": "conn_1",
            "strength": 0.5,
        }
        mock_db.update_connection_strength.return_value = {
            "id": "conn_1",
            "strength": 0.52,  # +0.02 for message
        }

        result = self.graph.update_interaction("user_a", "user_b", "message")

        mock_db.update_connection_strength.assert_called_once()

    def test_update_interaction_no_connection(self):
        """Test update interaction when no connection exists."""
        mock_db.get_connection_between.return_value = None

        result = self.graph.update_interaction("user_a", "user_b", "message")

        self.assertIsNone(result)

    def test_infer_connections_from_classes(self):
        """Test automatic classmate connection inference."""
        mock_db.get_classmates.return_value = ["classmate_1", "classmate_2"]
        mock_db.get_connection_between.return_value = None  # No existing connections
        mock_db.create_user_connection.side_effect = [
            {"id": "conn_1"},
            {"id": "conn_2"},
        ]

        result = self.graph.infer_connections_from_classes(self.user_id)

        self.assertEqual(len(result), 2)
        self.assertEqual(mock_db.create_user_connection.call_count, 2)


if __name__ == '__main__':
    unittest.main()
