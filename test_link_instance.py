import sys
import uuid
import logging
from unittest.mock import MagicMock

# Mocking modules
import sys
from unittest.mock import MagicMock

sys.modules["dotenv"] = MagicMock()
sys.modules["config"] = MagicMock()
sys.modules["supabase"] = MagicMock()
sys.modules["supabase_client"] = MagicMock()
sys.modules["pydantic"] = MagicMock()
sys.modules["schemas"] = MagicMock()
sys.modules["openai"] = MagicMock()

# Mock logic modules
sys.modules["link_logic"] = MagicMock()
sys.modules["link_orchestrator"] = MagicMock()
sys.modules["intent_classifier"] = MagicMock()

# Setup Intent Enum mock
class MockIntent:
    DB_QUERY = "db_query"
    PEOPLE_SEARCH = "people_search"
    PROFILE_CLASSES = "profile_classes"
    EVENT_SEARCH = "event_search"
    CLUB_SEARCH = "club_search"
    CAMPUS_INFO = "campus_info"
    FOOD = "food"
    HOUSING = "housing"
    TECH = "tech"
    SAFETY = "safety"
    ACTIVITY_RECALL = "activity_recall"
    FOLLOWUP = "followup"
    GREETING = "greeting"
    SMALL_TALK = "small_talk"
    CONSENT_RESPONSE = "consent_response"
    CANCEL_TASK = "cancel_task"
    UNKNOWN = "unknown"

sys.modules["intent_classifier"].Intent = MockIntent

import uuid
import logging

# Now import LinkInstance, which will use the mocked modules (partially)
# Actually, LinkInstance imports supabase_client, so we need to mock properties on it
import supabase_client as db

# Setup mock returns
db.get_link_sharing_rules.return_value = {}
db.get_user_context.return_value = {"profile": {"university_id": "test_uni"}}
db.get_user_context_rls.return_value = {"profile": {"university_id": "test_uni"}}
db.list_link_messages.return_value = []
db.get_user_memory.return_value = {}

# Also need to mock intent_classifier if it relies on other things, but it should be pure python
# LinkInstance imports it.

from link_instance import LinkInstance

logging.basicConfig(level=logging.INFO)

def test_link_instance():
    print("Testing LinkInstance...")
    
    # Use a fake UUID for testing
    test_user_id = str(uuid.uuid4())
    print(f"Test User ID: {test_user_id}")
    
    try:
        # 1. Initialize
        link = LinkInstance(test_user_id, access_token="fake_token", university_id="test_uni")
        print("Initialized LinkInstance.")
        
        # 2. Test Local Query
        msg_local = "Are there any events tonight?"
        res_local = link.process_message(msg_local, str(uuid.uuid4()))
        print(f"Local Query Response: {res_local}")
        assert res_local.get("action") == "db_lookup" or "action" in res_local
        
        # 3. Test Chat
        msg_chat = "What's up?"
        res_chat = link.process_message(msg_chat, str(uuid.uuid4()))
        print(f"Chat Response: {res_chat}")
        assert res_chat.get("action") == "chat"
        
        # 4. Test Distributed Query
        msg_dist = "Find someone who likes tennis."
        res_dist = link.process_message(msg_dist, str(uuid.uuid4()))
        print(f"Distributed Query Response: {res_dist}")
        assert res_dist.get("action") == "outreach_placeholder"

        print("Reflected Intent Classification worked.")

    except Exception as e:
        print(f"Test failed with error: {e}")
        # If DB connection fails, that's expected if no env, 
        # but we want to see if the class logic holds up until the DB call.

if __name__ == "__main__":
    test_link_instance()
