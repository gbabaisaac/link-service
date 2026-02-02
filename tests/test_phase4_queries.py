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

mock_db = MagicMock()
sys.modules['supabase_client'] = mock_db
sys.modules['link_orchestrator'] = MagicMock()

from smart_query_router import smart_query_router

class TestPhase4Queries(unittest.TestCase):
    def setUp(self):
        mock_db.reset_mock()
        self.requester_id = "user_alice"
        self.target_public = "user_bob_chess"
        self.target_private = "user_charlie_hidden"

    def test_auto_reply_public_info(self):
        """Test: Target HAS public info (Chess Club) -> Auto Reply."""
        
        # 1. Setup Mock: Bob is in Chess Club
        mock_db.get_user_context.return_value = {
            "clubs": [{"name": "University Chess Club", "id": "chess_123"}]
        }
        
        # 2. Process Request
        result = smart_query_router.process_target_request(
            self.target_public, 
            "query_111", 
            filters={"interest": "chess"}
        )
        
        # 3. Verify Auto Reply
        self.assertEqual(result["status"], "auto_replied")
        # Verify DB update call
        mock_db.update_knowledge_target.assert_called()
        call_args = mock_db.update_knowledge_target.call_args
        self.assertEqual(call_args[0][0], "query_111")
        self.assertEqual(call_args[0][1]["status"], "auto_replied")

    def test_consent_needed_private_info(self):
        """Test: Target validates FALSE for public info -> Consent Needed."""
        
        # 1. Setup Mock: Charlie has NO clubs
        mock_db.get_user_context.return_value = {
            "clubs": []
        }
        
        # 2. Process Request
        result = smart_query_router.process_target_request(
            self.target_private, 
            "query_222", 
            filters={"interest": "chess"}
        )
        
        # 3. Verify Consent Needed
        self.assertEqual(result["status"], "consent_needed")
        # In a real impl, this would trigger a notification. 
        # Here we just verify the status returned.

if __name__ == '__main__':
    unittest.main()
