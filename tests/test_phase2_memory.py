import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Setup Mocks
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.modules['config'] = MagicMock()
sys.modules['config'].settings = MagicMock()
sys.modules['config'].settings.TEST_MODE = True
sys.modules['config'].settings.SUPABASE_URL = "https://mock.supabase.co"
sys.modules['config'].settings.SUPABASE_KEY = "mock-key"
sys.modules['config'].settings.LINK_VAULT_KEY = "dmVyeS1zZWN1cmUtMzItYnl0ZS1rZXktZm9yLWRldgot"  # 32 bytes in base64

mock_db = MagicMock()
sys.modules['supabase_client'] = mock_db

# Mock LLM and Vault
mock_llm = MagicMock()
sys.modules['link_logic'] = MagicMock()
sys.modules['link_logic'].llm_json = mock_llm

mock_vault = MagicMock()
sys.modules['link_memory'] = MagicMock()
sys.modules['link_memory'].vault = mock_vault

from memory_manager import memory_manager
from link_instance import LinkInstance

class TestPhase2Memory(unittest.TestCase):
    def setUp(self):
        mock_db.reset_mock()
        mock_llm.reset_mock()
        
        # Mock Vibe DB to avoid TypeError
        mock_db.get_user_vibe.return_value = None
        mock_db.upsert_user_vibe.return_value = {}
        
        # Mock User Context
        mock_db.get_user_context.return_value = {
            "profile": {
                "first_name": "Isaac",
                "major": "Psychology",
                "interests": ["Drawing", "Painting", "Parties"]
            }
        }
        
        self.user_id = "user_isaac"
        self.instance = LinkInstance(self.user_id)
        self.instance.university_id = "uni_123"
        self.instance.conversation_id = "convo_123"

    def test_tiered_memory_flow(self):
        """Test: Mixture of Long/Medium memories -> Prioritized retrieval."""
        
        # 1. Mock Extraction: Long-term fact vs Medium-term context
        mock_llm.return_value = [
            {"content": "Likes basketball", "category": "preferences", "tier": "long", "priority": 3},
            {"content": "Looking for summer internship", "category": "facts", "tier": "medium", "priority": 5}
        ]
        
        # Act 1: Process message
        self.instance.process_message("I'm looking for a summer internship and I still love basketball", "convo_123")
        
        # 2. Mock DB retrieval with multi-tier structure
        mock_vault.decrypt.side_effect = [
            "Looking for summer internship", "Likes basketball", # Call 1
            "Looking for summer internship", "Likes basketball"  # Call 2
        ]
        mock_db.list_encrypted_memories.return_value = [
            {"encrypted_value": "intern_blob", "tier": "medium", "priority": 5},
            {"encrypted_value": "ball_blob", "tier": "long", "priority": 3}
        ]
        
        # Act 2: Handle memory query
        response = self.instance._handle_memory_query("profile_question")
        
        # Assert: Medium-term (Internship) and Long-term (Basketball) both present
        self.assertIn("Looking for summer internship", response["response"])
        self.assertIn("Likes basketball", response["response"])
        self.assertIn("Medium-term/Current", response["response"])
        
        # Verify Priority Sorting (Internship should be first in raw list if fetched)
        facts = memory_manager.get_decrypted_facts(self.user_id)
        self.assertEqual(facts[0]["content"], "Looking for summer internship")
        self.assertEqual(facts[0]["priority"], 5)

if __name__ == '__main__':
    unittest.main()
