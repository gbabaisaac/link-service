import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Add parent directory to path so we can import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock config before importing modules that use it
sys.modules['config'] = MagicMock()
sys.modules['config'].settings = MagicMock()
sys.modules['config'].settings.TEST_MODE = True
sys.modules['config'].settings.SUPABASE_URL = "https://mock.supabase.co"
sys.modules['config'].settings.SUPABASE_KEY = "mock-key"

# Mock supabase_client
mock_db = MagicMock()
sys.modules['supabase_client'] = mock_db

# Mock link_orchestrator
mock_orch = MagicMock()
sys.modules['link_orchestrator'] = mock_orch

from link_instance import LinkInstance
from intent_classifier import Intent

class TestPhase1Runner(unittest.TestCase):
    def setUp(self):
        # Reset mocks
        mock_db.reset_mock()
        mock_orch.reset_mock()
        
        # Setup default mock returns
        mock_db.get_user_context_rls.return_value = {
            "profile": {"first_name": "Isaac", "university_id": "uni_123", "major": "CS"}
        }
        mock_db.get_or_create_link_conversation_state.return_value = {
            "mode": "idle",
            "active_task": {}
        }
        mock_db.list_link_messages.return_value = []
        mock_db.get_user_memory.return_value = {}
        
        self.user_id = "user_test_123"
        self.access_token = "token_123"
        self.instance = LinkInstance(self.user_id, self.access_token)

    def test_initialization_scoping(self):
        """Verify that LinkInstance loads context scoped to the user."""
        mock_db.get_user_context_rls.assert_called_with(self.access_token, self.user_id)
        self.assertEqual(self.instance.university_id, "uni_123")

    def test_transition_to_agent_mode(self):
        """Test that a query transitions the state to 'agent'."""
        # Query that should trigger DB_QUERY/EVENT_SEARCH
        message = "When is the hackathon?"
        conversation_id = "convo_123"
        
        # Act
        response = self.instance.process_message(message, conversation_id)
        
        # Assert
        # 1. Check State Update
        mock_db.update_link_conversation_state.assert_called()
        args = mock_db.update_link_conversation_state.call_args[0]
        self.assertEqual(args[0], conversation_id)
        self.assertEqual(args[1]['mode'], 'agent')
        
        # 2. Check Candidate Retrieval (The Action)
        mock_orch.retrieve_candidates.assert_called()
        # Verify it passed the intent string correctly (e.g., 'event_search' or 'campus_info')
        call_args = mock_orch.retrieve_candidates.call_args[0]
        print(f"DEBUG: retrieve_candidates called with: {call_args}")
        self.assertIn(call_args[0], ['event_search', 'campus_info', 'db_query']) 

    def test_chat_mode_stability(self):
        """Test that small talk stays in 'conversation' mode."""
        message = "What's good?"
        conversation_id = "convo_123"
        
        # Act
        self.instance.process_message(message, conversation_id)
        
        # Assert
        # Should NOT switch to agent
        # We perform an update even if mode is same (to update last_updated potentially, or maybe not if optimized)
        # But let's check the result action
        mock_orch.generate_small_talk_response.assert_called()
        
        # Verify context injection
        call_kwargs = mock_orch.generate_small_talk_response.call_args[1]
        self.assertEqual(call_kwargs['user_context'], self.instance.user_context)

    def test_outreach_placeholder(self):
        """Test transition to outreach mode (Phase 3 placeholder)."""
        message = "Find me someone who likes chess."
        conversation_id = "convo_123"
        
        response = self.instance.process_message(message, conversation_id)
        
        self.assertEqual(response['action'], 'outreach_placeholder')
        
        # Check State Update to outreach
        args = mock_db.update_link_conversation_state.call_args[0]
        self.assertEqual(args[1]['mode'], 'outreach')

    def test_connect_friends_routing(self):
        """Test 'Connect me to friends' routes to Outreach Mode."""
        message = "Connect me with John"
        conversation_id = "convo_connect"
        
        response = self.instance.process_message(message, conversation_id)
        
        # Should route to 'people_search' / 'outreach'
        # Currently _classify_intent maps PEOPL_SEARCH to 'distributed_query' -> 'outreach' mode
        # or 'agent' mode if handled locally.
        # Let's verify the State Machine decided 'outreach' or 'agent' depending on implementation
        # Our State Manager routes PEOPLE_SEARCH to 'outreach'
        
        # Check Db Update
        mock_db.update_link_conversation_state.assert_called()
        args = mock_db.update_link_conversation_state.call_args[0]
        self.assertEqual(args[1]['mode'], 'outreach')
        self.assertEqual(response['action'], 'outreach_placeholder')

    def test_event_finding(self):
        """Test 'Letting them know about event' (User asking for event)."""
        message = "Is there a party tonight?"
        conversation_id = "convo_event"
        
        response = self.instance.process_message(message, conversation_id)
        
        # Should route to Agent
        args = mock_db.update_link_conversation_state.call_args[0]
        self.assertEqual(args[1]['mode'], 'agent')
        
        # Should result in DB Lookup
        call_args = mock_orch.retrieve_candidates.call_args[0]
        self.assertEqual(call_args[0], 'event_search')
        self.assertEqual(response['action'], 'db_lookup')

    def test_interview_mention_routing(self):
        """
        Test 'Asking about their interview'.
        This tests the REACTIVE side: User mentions interview -> Link acknowledges.
        (Proactive asking requires Phase 2 Scheduler).
        """
        message = "I'm so nervous about my interview"
        conversation_id = "convo_interview"
        
        # Act
        response = self.instance.process_message(message, conversation_id)
        
        # Assert
        # Should stay in Conversation mode (Small Talk)
        # But we want to ensure it didn't crash or try to run a DB query
        mock_orch.generate_small_talk_response.assert_called()
        self.assertEqual(response['action'], 'chat')
        
        # Verify user context was passed (Link knows who they are checking in on)
        call_kwargs = mock_orch.generate_small_talk_response.call_args[1]
        self.assertIsNotNone(call_kwargs.get('user_context'))

    def test_basketball_friend_routing(self):
        """Test 'looking for a friend to play basketball with'."""
        message = "im looking for a friend to play basketball with"
        conversation_id = "convo_basketball"
        
        response = self.instance.process_message(message, conversation_id)
        
        # 'looking for' -> PEOPLE_SEARCH -> Outreach Mode
        args = mock_db.update_link_conversation_state.call_args[0]
        self.assertEqual(args[1]['mode'], 'outreach')
        self.assertEqual(response['action'], 'outreach_placeholder')

if __name__ == '__main__':
    unittest.main()
