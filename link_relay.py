"""
Link Relay System for Link AI.

Implements direct Link-to-Link communication:
- Sanitizes messages for privacy
- Routes requests between user Link instances
- Handles anonymous relay responses
"""

from __future__ import annotations
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple
import uuid
import re
import supabase_client as db


class LinkRelay:
    """
    Handles direct communication between Link instances.
    Ensures privacy through sanitization and anonymization.
    """

    # Sensitive patterns to redact
    SENSITIVE_PATTERNS = [
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",  # Email
        r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b",  # Phone
        r"\b\d{5}(-\d{4})?\b",  # ZIP code
        r"@\w+",  # Social media handles
        r"\b\d{9}\b",  # SSN-like
    ]

    # Entity replacement templates
    ENTITY_REPLACEMENTS = {
        "name": "someone",
        "person": "a friend",
        "class": "their class",
        "professor": "their professor",
        "room": "a location",
        "building": "a building",
    }

    def create_relay_request(
        self,
        from_user: str,
        to_user: str,
        question: str,
        request_type: str = "question",
        context: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """
        Create a relay request from one user's Link to another's.

        Args:
            from_user: Requesting user ID
            to_user: Target user ID
            question: The question/request to relay
            request_type: Type of request ('question', 'intro', 'info')
            context: Optional context about the request

        Returns:
            Created relay run dict
        """
        # 1. Sanitize the question
        sanitized_question = self.sanitize_for_relay(question)

        # 2. Create the relay run
        payload = {
            "requester_user_id": from_user,
            "target_user_id": to_user,
            "request_type": request_type,
            "original_message": question,
            "sanitized_message": sanitized_question,
            "status": "pending",
            "context": context or {},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        return db.create_link_relay_run(payload)

    def get_relay_response(self, relay_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the response for a relay request.

        Returns:
            Dict with response data or None
        """
        relay = db.get_link_relay_run(relay_id)
        if not relay:
            return None

        targets = db.list_link_relay_targets(relay_id)
        responses = [t for t in targets if t.get("response")]

        return {
            "relay_id": relay_id,
            "status": relay.get("status"),
            "responses": responses,
            "created_at": relay.get("created_at"),
        }

    def sanitize_for_relay(self, message: str) -> str:
        """
        Sanitize a message for relay transmission.
        Removes or replaces sensitive information.

        Returns:
            Sanitized message string
        """
        sanitized = message

        # 1. Remove sensitive patterns
        for pattern in self.SENSITIVE_PATTERNS:
            sanitized = re.sub(pattern, "[redacted]", sanitized, flags=re.IGNORECASE)

        # 2. Anonymize entity references
        sanitized = self._anonymize_entities(sanitized)

        return sanitized

    def process_incoming_relay(
        self,
        relay_id: str,
        target_user_id: str,
    ) -> Dict[str, Any]:
        """
        Process an incoming relay request for a target user.

        Returns:
            Dict with processing status and any auto-responses
        """
        relay = db.get_link_relay_run(relay_id)
        if not relay:
            return {"error": "Relay not found"}

        # Check if target matches
        if relay.get("target_user_id") != target_user_id:
            return {"error": "Invalid target"}

        # Check user's sharing rules
        sharing_rules = db.get_link_sharing_rules(target_user_id)

        # Determine if auto-approval applies
        requester_id = relay.get("requester_user_id")
        auto_approved = self._check_auto_approval(target_user_id, requester_id, sharing_rules)

        if auto_approved:
            # Create target entry and mark as approved
            target_entry = db.create_link_relay_target({
                "run_id": relay_id,
                "target_user_id": target_user_id,
                "status": "approved",
                "consent_at": datetime.now(timezone.utc).isoformat(),
            })

            return {
                "status": "auto_approved",
                "target_id": target_entry.get("id"),
            }

        # Otherwise, mark as pending consent
        target_entry = db.create_link_relay_target({
            "run_id": relay_id,
            "target_user_id": target_user_id,
            "status": "pending_consent",
        })

        return {
            "status": "pending_consent",
            "target_id": target_entry.get("id"),
            "sanitized_question": relay.get("sanitized_message"),
        }

    def respond_to_relay(
        self,
        target_id: str,
        response: str,
        approved: bool = True,
    ) -> Dict[str, Any]:
        """
        Respond to a relay request.

        Args:
            target_id: The relay target ID
            response: The response message
            approved: Whether the user approved the relay

        Returns:
            Updated target dict
        """
        now = datetime.now(timezone.utc).isoformat()

        if approved:
            # Sanitize the response before sending
            sanitized_response = self.sanitize_for_relay(response)

            payload = {
                "status": "responded",
                "response": sanitized_response,
                "responded_at": now,
            }
        else:
            payload = {
                "status": "declined",
                "declined_at": now,
            }

        return db.update_link_relay_target(target_id, payload)

    def get_pending_relays(self, user_id: str) -> List[Dict[str, Any]]:
        """
        Get pending relay requests for a user.

        Returns:
            List of pending relay dicts
        """
        # This would query relay targets where user is target and status is pending
        # For now, use existing cross_requests table
        pending = db.get_cross_requests_for_user(user_id, status="pending")
        return pending

    def extract_public_tags(self, message: str, user_context: Optional[Dict] = None) -> List[str]:
        """
        Extract public tags from a message for anonymous matching.

        Returns:
            List of public tags (interests, topics, etc.)
        """
        tags = []

        # Extract potential interest/topic keywords
        interest_keywords = {
            "music", "sports", "gaming", "art", "reading", "movies",
            "food", "travel", "fitness", "photography", "coding",
            "basketball", "football", "soccer", "tennis", "volleyball",
            "anime", "hiking", "cooking", "dancing", "singing",
        }

        major_keywords = {
            "cs", "computer science", "engineering", "biology", "chemistry",
            "physics", "math", "psychology", "business", "economics",
            "english", "history", "art", "music", "communications",
        }

        message_lower = message.lower()

        for keyword in interest_keywords:
            if keyword in message_lower:
                tags.append(f"interest:{keyword}")

        for keyword in major_keywords:
            if keyword in message_lower:
                tags.append(f"major:{keyword}")

        # Add tags from user context if available
        if user_context:
            profile = user_context.get("profile", {})
            interests = profile.get("interests", [])
            for interest in interests[:5]:
                if isinstance(interest, str):
                    tags.append(f"interest:{interest.lower()}")

        return list(set(tags))[:10]

    # ============ Private Helpers ============

    def _anonymize_entities(self, text: str) -> str:
        """Replace named entities with anonymous placeholders."""
        # Simple heuristic-based anonymization
        # In production, use NER model

        # Replace capitalized words that might be names (after first word)
        words = text.split()
        anonymized_words = []

        for i, word in enumerate(words):
            # Skip first word (might be capitalized normally)
            if i > 0 and word[0].isupper() and word.isalpha():
                # Likely a proper noun
                anonymized_words.append("someone")
            else:
                anonymized_words.append(word)

        return " ".join(anonymized_words)

    def _check_auto_approval(
        self,
        target_user_id: str,
        requester_id: str,
        sharing_rules: Dict,
    ) -> bool:
        """Check if a relay request should be auto-approved."""
        # Check if requester is a friend
        friends = db.get_friends(target_user_id)
        if requester_id in friends:
            # Check if friends are auto-approved
            auto_approve_friends = sharing_rules.get("auto_approve_friends", {})
            if auto_approve_friends.get("value") == True:
                return True

        # Check other auto-approval rules
        # (classmates, same organizations, etc.)

        return False


# Singleton export
link_relay = LinkRelay()
