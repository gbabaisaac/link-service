from typing import List, Dict, Any, Optional
import supabase_client as db

class SmartQueryRouter:
    """
    Manages the 'Group Mind' logic.
    1. Resolves WHO to ask (Targets).
    2. Dispatches queries to their Link Instances.
    3. Enforces the 'Public Info = Auto Reply, Private Info = Ask' rule.
    """

    def start_distributed_query(self, requester_id: str, query_text: str, intent: str, filters: Dict) -> str:
        """
        Start a new query. 
        Example: "Who plays chess?" -> intent="find_activity_partner", filters={"interest": "chess"}
        """
        # 1. Create Query Record
        query = db.create_knowledge_query({
            "requester_user_id": requester_id,
            "query_text": query_text,
            "query_intent": intent,
            "query_filters": filters
        })
        query_id = query["id"]

        # 2. Resolve Targets (Who determines the scope?)
        # For MVP, we broadcast to 'friends' or 'classmates' if specified.
        # Simplification: Fetch all active users in same university (Mock)
        # In prod, this would use a Graph Traversal (Friends of Friends).
        requester_profile = db.get_profile(requester_id) or {}
        uni_id = requester_profile.get("university_id")
        
        candidates = db.get_profiles(university_id=uni_id, limit=50) # Broad sweep
        target_rows = []
        for c in candidates:
            if c["id"] == requester_id: continue # Don't ask yourself
            target_rows.append({
                "query_id": query_id,
                "target_user_id": c["id"],
                "status": "pending"
            })
        
        if target_rows:
            db.create_knowledge_targets(target_rows)
            
        return query_id

    def process_target_request(self, target_user_id: str, query_id: str, filters: Dict) -> Dict[str, Any]:
        """
        The Logic executed on the TARGET's Link Instance.
        Decides: Auto-Reply or Ask Consent?
        """
        # 1. Check if the requested info is PUBLIC
        # Example: filters={"interest": "chess"}
        interest_query = filters.get("interest")
        
        is_public = self._check_public_interest(target_user_id, interest_query)
        
        if is_public:
            # AUTO REPLY
            db.update_knowledge_target(query_id, { # Need to find the row ID first in real flow
                # optimization: process_target_request should take row_id
                "status": "auto_replied",
                "response_payload": {"match": True, "info": f"{interest_query} (Public)"} 
            })
            return {"status": "auto_replied"}
        else:
            # PRIVATE -> ASK CONSENT
            # In Phase 4, we mark it as 'consent_needed' and notify the user
            # db.update_knowledge_target(..., "consent_needed")
            return {"status": "consent_needed"}

    def _check_public_interest(self, user_id: str, interest: Optional[str]) -> bool:
        """Check if interest is in public profile/clubs."""
        if not interest: return False
        
        context = db.get_user_context(user_id)
        clubs = context.get("clubs", [])
        
        # Check Clubs
        for club in clubs:
            if interest.lower() in club["name"].lower():
                return True
                
        return False

smart_query_router = SmartQueryRouter()
