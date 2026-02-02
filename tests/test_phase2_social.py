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

from vibe_matcher import vibe_matcher
from life_event_detector import life_event_detector

class TestPhase2Social(unittest.TestCase):
    def setUp(self):
        mock_db.reset_mock()
        self.user_id = "user_social_123"
        self.uni_id = "uni_123"

    def test_vibe_update_slang(self):
        """Test that slang heavy message updates usage metric."""
        # 1. Setup existing vibe
        mock_db.get_user_vibe.return_value = {
            "slang_usage": 0.0,
            "formality_level": 0.5,
            "avg_sentence_length": 5.0
        }
        
        # 2. Process Slang Message
        # "fr no cap" -> 3 words, 3 slang words (fr, no, cap) -> 1.0 density? 
        # Actually our matcher does: words=[fr, no, cap]. slang=[fr, cap]. density=2/3 = 0.66
        msg = "fr no cap its lit"
        vibe_matcher.update_user_vibe(self.user_id, msg, self.uni_id)
        
        # 3. Verify DB Upsert
        mock_db.upsert_user_vibe.assert_called()
        payload = mock_db.upsert_user_vibe.call_args[0][1]
        
        # Initial 0.0, New 0.5. Weighted 0.8 / 0.2
        # slang = 0.0*0.8 + 0.5*0.2 = 0.1 (approx)
        self.assertGreater(payload["slang_usage"], 0.05)
        self.assertIn("Gen Z slang", payload["style_prompt"])

    def test_event_detector_interview(self):
        """Test detection of interview scheduling."""
        msg = "I have an interview on Friday for Google"
        
        # Mock create_life_event return
        mock_db.create_life_event.return_value = {"id": "event_123"}
        
        # Act
        events = life_event_detector.process_message(self.user_id, msg)
        
        # Assert
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["id"], "event_123")
        
        # Check Job Created
        mock_db.create_scheduled_job.assert_called()
        job = mock_db.create_scheduled_job.call_args[0][0]
        self.assertEqual(job["job_type"], "check_in")
        self.assertEqual(job["payload"]["event_type"], "interview")

if __name__ == '__main__':
    unittest.main()
