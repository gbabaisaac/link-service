import sys
import os
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime

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
sys.modules['vibe_matcher'] = MagicMock()
sys.modules['life_event_detector'] = MagicMock()

from intent_classifier import IntentResult, Intent
from link_instance import LinkInstance

class TestPhase3Consent(unittest.TestCase):
    def setUp(self):
        mock_db.reset_mock()
        self.alice_id = "user_alice"
        self.bob_id = "user_bob"
        self.bob_instance = LinkInstance(self.bob_id)
        self.bob_instance.conversation_id = "convo_bob"

    def test_consent_approval_flow(self):
        """Simulate Bob approving a request from Alice."""
        
        # 1. Setup the active task: Bob is being asked for consent
        task = {"request_id": "req_123", "requester": "Alice", "status": "awaiting_consent"}
        
        # 2. Bob says "Yes, sure"
        message = "yeah sure send it"
        intent_result = MagicMock()
        intent_result.base_intent.intent = Intent.CONSENT_RESPONSE
        
        # 3. Process
        response = self.bob_instance._handle_consent_mode(message, task, intent_result)
        
        # 4. Verify Approval
        mock_db.update_cross_request.assert_called_with(
            "req_123", 
            {"status": "approved", "response_payload": {"contact": "email@example.com"}}
        )
        self.assertEqual(response["action"], "consent_given")
        
    def test_consent_rejection_anonymized(self):
        """Simulate Bob rejecting Alice (Anonymized)."""
        
        # 1. Setup task
        task = {"request_id": "req_123", "requester": "Alice", "status": "awaiting_consent"}
        
        # 2. Bob says "No"
        message = "nah i dont want to"
        intent_result = MagicMock()
        intent_result.base_intent.intent = Intent.CONSENT_RESPONSE
        
        # 3. Process
        response = self.bob_instance._handle_consent_mode(message, task, intent_result)
        
        # 4. Verify Rejection
        mock_db.update_cross_request.assert_called_with(
            "req_123", 
            {"status": "rejected", "rejection_reason": "user_declined"}
        )
        self.assertEqual(response["action"], "consent_denied")
        # Ensure Link confirms to Bob but the reason stored is internal
        self.assertIn("told them you're busy", response["response"])

if __name__ == '__main__':
    unittest.main()
