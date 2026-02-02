from __future__ import annotations
import uuid
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

import supabase_client as db
from config import settings
from link_logic import llm_json
import link_orchestrator
from intent_classifier import classify_intent, Intent

import link_state_manager
from intent_classifier import classify_intent, Intent

class LinkInstance:
    """
    Represents a single, isolated Link agent for a specific user.
    This class enforces the federated model by scoping all actions to the user_id.
    """

    def __init__(self, user_id: str, access_token: Optional[str] = None, university_id: Optional[str] = None):
        self.user_id = user_id
        self.access_token = access_token
        self.conversation_id = None
        self.university_id = university_id
        
        # Load user context on init (or lazily)
        self.user_context = self._load_context()
        if not self.university_id and self.user_context.get("profile"):
            self.university_id = self.user_context["profile"].get("university_id")
            
        self.sharing_rules = db.get_link_sharing_rules(self.user_id) if hasattr(db, "get_link_sharing_rules") else {}

    def _load_context(self) -> Dict[str, Any]:
        """Load user profile and basic context."""
        if self.access_token:
            return db.get_user_context_rls(self.access_token, self.user_id)
        return db.get_user_context(self.user_id)

    def process_message(self, message: str, conversation_id: str) -> Dict[str, Any]:
        """
        Main entry point for processing a user message.
        """
        self.conversation_id = conversation_id
        
        # 1. Update Vibe/Style Memory
        # Use VibeMatcher to analyze and persist user style
        if self.university_id:
            from vibe_matcher import vibe_matcher
            vibe_matcher.update_user_vibe(self.user_id, message, self.university_id)

        # 2. Check for Life Events (Emotional Intelligence)
        # Scan for exams/interviews and schedule check-ins
        from life_event_detector import life_event_detector
        detected_events = life_event_detector.process_message(self.user_id, message)
        
        # 3. Update Personal Memory (The Vault)
        # Extract new facts/interests from the message
        from memory_manager import memory_manager
        memory_manager.process_message(self.user_id, message)
        
        # 4. Get Persistent State (Runner Logic)
        state = db.get_or_create_link_conversation_state(self.user_id, conversation_id)
        current_mode = state.get("mode", "idle")
        active_task = state.get("active_task") or {}

        # 3. Classify Intent
        intent_result = classify_intent(message, active_task=active_task)
        
        # 4. Determine State Transition (The Runner Logic)
        transition = link_state_manager.determine_transition(current_mode, active_task, intent_result)
        
        # 5. Persist New State (if changed)
        if transition.mode != current_mode or transition.active_task != active_task:
            db.update_link_conversation_state(conversation_id, {
                "mode": transition.mode,
                "active_task": transition.active_task
            })
            
        # 6. Execute Logic based on NEW mode
        if transition.mode == "agent":
            return self._handle_agent_mode(message, transition.active_task)
        elif transition.mode == "outreach":
            return self._handle_distributed_query(transition.active_task, message)
        elif transition.mode == "awaiting_consent":
            return self._handle_consent_mode(message, transition.active_task, intent_result)
        else:
            return self._handle_conversation_mode(message)

    def _handle_agent_mode(self, message: str, task: Dict) -> Dict[str, Any]:
        """Handle DB Queries and Information Retrieval."""
        intent_type = task.get("intent")
        entities = task.get("entities", [])
        
        if intent_type in {"profile_classes", "profile_question", "activity_recall"}:
             return self._handle_memory_query(intent_type)
        
        # Local DB Query
        if not self.university_id:
             return {"response": "I don't know which university you're at yet.", "action": "error"}

        results = link_orchestrator.retrieve_candidates(
            intent_type, # Pass raw intent string (e.g. 'event_search')
            entities,
            None,
            self.university_id,
            access_token=self.access_token
        )
        return {"response": "Here is what I found.", "action": "db_lookup", "data": results}

    def _handle_distributed_query(self, intent: Dict, message: str) -> Dict[str, Any]:
        """Initiate valid cross-link requests."""
        # For now, we assume simple intro request.
        # Future: Parse "Find chess players" -> Query multiple.
        # MVP: "Connect me with [John]"
        entities = intent.get("entities", [])
        if not entities:
            return {"response": "Who do you want to connect with?", "action": "chat"}
        
        target_name = entities[0] 
        # Ideally, we resolve name to UUID here using lookup. 
        # For MVP, we simulate a lookup or fail.
        # target_user = db.lookup_user_by_name(target_name, self.university_id) ...
        
        # Placeholder response for now as we don't have name->uuid in simple mock
        return {"response": f"I can try to connect you with {target_name}. Shall I send a request?", "action": "confirm_outreach"}

    def _handle_consent_mode(self, message: str, task: Dict, intent_result: Any) -> Dict[str, Any]:
        """Handle Consent Responses (Yes/No to sharing data)."""
        # User is responding to "Can I share your info with X?"
        consent = intent_result.base_intent.intent
        
        request_id = task.get("request_id")
        if not request_id:
             return {"response": "I lost track of the request. idle.", "action": "error"}

        if consent == Intent.CONSENT_RESPONSE: # IntentClassifier maps 'yes'/'sure' to CONSENT_RESPONSE
            # Determine if it was a positive or negative consent
            # IntentClassifier maps 'yes'/'sure' to CONSENT_RESPONSE if active task is 'awaiting_consent'
            # We need to peek at the raw text or sub-intent for polarity
            if any(x in message.lower() for x in ["yes", "sure", "ok", "yeah"]):
                db.update_cross_request(request_id, {"status": "approved", "response_payload": {"contact": "email@example.com"}}) # Mock payload
                return {"response": "Cool, I sent them your info.", "action": "consent_given"}
            else:
                db.update_cross_request(request_id, {"status": "rejected", "rejection_reason": "user_declined"})
                return {"response": "Got it, I told them you're busy (anonymized denial).", "action": "consent_denied"}
        
        return {"response": "Please say yes or no.", "action": "clarify"}

    def _handle_conversation_mode(self, message: str) -> Dict[str, Any]:
        """General Chat."""
        # Fetch history
        history_rows = db.list_link_messages(self.conversation_id, limit=10) if self.conversation_id else []
        recent_messages = [h.get("content") for h in history_rows if h.get("sender_type") == "user" and h.get("content")]
        formatted_history = "\n".join([f"{h['sender_type']}: {h['content']}" for h in reversed(history_rows)])

        # Fetch and Decrypt long-term memory (Multi-Tier)
        from memory_manager import memory_manager
        vault_facts = memory_manager.get_decrypted_facts(self.user_id)
        
        user_memory = db.get_user_memory(self.user_id) or {}
        # Merge legacy memory with new multi-tier vault memory
        if vault_facts:
            user_memory.setdefault("known_preferences", {}).setdefault("vault_facts", [])
            user_memory["known_preferences"]["vault_facts"] = vault_facts

        response = link_orchestrator.generate_small_talk_response(
            message,
            user_memory,
            recent_user_messages=recent_messages,
            conversation_history=formatted_history,
            user_context=self.user_context
        )
        return {"response": response, "action": "chat"}

    def _handle_memory_query(self, intent_type: str) -> Dict[str, Any]:
        """Access user's private encrypted memory (Audit Feature)."""
        if intent_type == "profile_classes":
            classes = self.user_context.get("classes", [])
            names = [c.get("name") for c in classes] if classes else []
            if names:
                return {"response": f"You are taking: {', '.join(names)}", "action": "memory_read"}
        
        # Real Audit Feature from the Vault
        from memory_manager import memory_manager
        facts = memory_manager.get_decrypted_facts(self.user_id)
        
        if intent_type == "profile_question":
            # Combine static profile info with dynamic vault facts
            profile = self.user_context.get("profile") or {}
            major = profile.get("major", "Psychology")
            name = profile.get("first_name", "Isaac")
            static_interests = ", ".join(profile.get("interests", ["Drawing", "Painting", "Parties"]))
            
            # Format facts by tier
            long_facts = [f["content"] for f in facts if f["tier"] == "long"]
            med_facts = [f["content"] for f in facts if f["tier"] == "medium"]
            
            vault_str = f"Long-term: {', '.join(long_facts) if long_facts else 'none'}. Medium-term/Current: {', '.join(med_facts) if med_facts else 'none'}."
            response = f"you're {name}, {major} major, into {static_interests}. {vault_str} want me to update anything?"
            return {"response": response, "action": "memory_read"}

        return {"response": "Checking your memory...", "action": "memory_lookup"}

    def handle_incoming_request(self, origin_link_id: str, request_type: str, payload: Dict) -> Dict[str, Any]:
        """Handle cross-link request from another instance."""
        # Phase 3 logic
        db.create_cross_request({
            "requester_user_id": origin_link_id,
            "target_user_id": self.user_id,
            "request_type": request_type,
            "payload": payload,
            "status": "pending_consent"
        })
        return {"status": "pending_consent"}

    def run_scheduled_job(self, job: Dict[str, Any]) -> None:
        """
        Execute a scheduled job (e.g. check-in).
        Called by the external Scheduler Worker.
        """
        job_type = job.get("job_type")
        payload = job.get("payload") or {}
        
        if job_type == "check_in":
            # Context-aware checkin
            event_type = payload.get("event_type")
            context = payload.get("context")
            
            # Generate Message using Orchestrator (with context)
            # We treat this as a "system prompt" to Link to start a convo
            message = link_orchestrator.generate_checkin_message(
                self.user_context, 
                event_type, 
                context
            )
            
            # Send (Insert into DB)
            # effectively "Pushing" the message to the user
            if self.conversation_id:
                db.insert_link_message(
                    conversation_id=self.conversation_id,
                    sender_id=None, # System/Link
                    content=message,
                    sender_type="link"
                )
            else:
                # If no active conversation, find recent or create one
                # For MVP, assume one exists or fail silently (logging)
                pass
