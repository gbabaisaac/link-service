"""
Response Pre-loading and Caching for Link AI.

Pre-computes likely response branches during idle time:
- Caches common intent responses per user
- Tracks intent frequency for personalization
- Provides fast response retrieval
"""

from __future__ import annotations
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from collections import defaultdict
import json
import hashlib


class ResponseCache:
    """
    Manages pre-computed responses for faster user interactions.
    Uses in-memory cache with optional persistence.
    """

    # Cache settings
    MAX_CACHE_SIZE_PER_USER = 20
    CACHE_TTL_HOURS = 24
    TOP_INTENTS_TO_CACHE = 5

    def __init__(self):
        # In-memory cache: {user_id: {cache_key: {response, timestamp, hits}}}
        self._cache: Dict[str, Dict[str, Dict[str, Any]]] = {}

        # Intent frequency tracking: {user_id: {intent: count}}
        self._intent_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

    def preload_common_responses(self, user_id: str) -> int:
        """
        Pre-generate responses for a user's most common intents.

        Returns:
            Number of responses pre-loaded
        """
        # Get user's top intents
        top_intents = self.get_top_intents(user_id, limit=self.TOP_INTENTS_TO_CACHE)

        if not top_intents:
            # Default intents for new users
            top_intents = ["greeting", "small_talk", "profile_question"]

        preloaded = 0

        for intent in top_intents:
            try:
                response = self._generate_cached_response(user_id, intent)
                if response:
                    self._set_cache(user_id, intent, response)
                    preloaded += 1
            except Exception:
                continue

        return preloaded

    def get_cached_response(self, user_id: str, intent: str, context: Optional[Dict] = None) -> Optional[str]:
        """
        Retrieve a cached response for an intent.

        Args:
            user_id: User ID
            intent: Intent type (e.g., "greeting", "small_talk")
            context: Optional context for cache key generation

        Returns:
            Cached response string or None
        """
        cache_key = self._make_cache_key(intent, context)
        cached = self._get_cache(user_id, cache_key)

        if cached:
            # Update hit count
            cached["hits"] = cached.get("hits", 0) + 1
            return cached.get("response")

        return None

    def cache_response(self, user_id: str, intent: str, response: str, context: Optional[Dict] = None) -> None:
        """
        Cache a generated response for future use.

        Args:
            user_id: User ID
            intent: Intent type
            response: Response to cache
            context: Optional context for cache key
        """
        cache_key = self._make_cache_key(intent, context)
        self._set_cache(user_id, cache_key, response)

    def invalidate_cache(self, user_id: str, intent: Optional[str] = None) -> int:
        """
        Invalidate cache entries for a user.

        Args:
            user_id: User ID
            intent: Optional specific intent to invalidate (all if None)

        Returns:
            Number of entries invalidated
        """
        if user_id not in self._cache:
            return 0

        if intent is None:
            count = len(self._cache[user_id])
            self._cache[user_id] = {}
            return count

        # Invalidate specific intent
        count = 0
        keys_to_remove = [k for k in self._cache[user_id] if k.startswith(f"{intent}:")]
        for key in keys_to_remove:
            del self._cache[user_id][key]
            count += 1

        return count

    def track_intent(self, user_id: str, intent: str) -> None:
        """Track that a user used a particular intent."""
        self._intent_counts[user_id][intent] += 1

    def get_top_intents(self, user_id: str, limit: int = 5) -> List[str]:
        """Get user's most frequent intents."""
        counts = self._intent_counts.get(user_id, {})
        sorted_intents = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        return [intent for intent, _ in sorted_intents[:limit]]

    def get_cache_stats(self, user_id: str) -> Dict[str, Any]:
        """Get cache statistics for a user."""
        user_cache = self._cache.get(user_id, {})

        total_entries = len(user_cache)
        total_hits = sum(e.get("hits", 0) for e in user_cache.values())
        oldest_entry = None
        newest_entry = None

        for entry in user_cache.values():
            ts = entry.get("timestamp")
            if ts:
                if oldest_entry is None or ts < oldest_entry:
                    oldest_entry = ts
                if newest_entry is None or ts > newest_entry:
                    newest_entry = ts

        return {
            "total_entries": total_entries,
            "total_hits": total_hits,
            "oldest_entry": oldest_entry,
            "newest_entry": newest_entry,
            "top_intents": self.get_top_intents(user_id),
        }

    def cleanup_expired(self) -> int:
        """Remove expired cache entries across all users."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.CACHE_TTL_HOURS)
        removed = 0

        for user_id in list(self._cache.keys()):
            user_cache = self._cache[user_id]
            keys_to_remove = []

            for key, entry in user_cache.items():
                ts = entry.get("timestamp")
                if ts and datetime.fromisoformat(ts) < cutoff:
                    keys_to_remove.append(key)

            for key in keys_to_remove:
                del user_cache[key]
                removed += 1

            # Clean up empty user caches
            if not user_cache:
                del self._cache[user_id]

        return removed

    # ============ Private Helpers ============

    def _make_cache_key(self, intent: str, context: Optional[Dict] = None) -> str:
        """Generate a cache key from intent and context."""
        if context:
            # Include relevant context in the key
            context_str = json.dumps(context, sort_keys=True)
            context_hash = hashlib.md5(context_str.encode()).hexdigest()[:8]
            return f"{intent}:{context_hash}"
        return f"{intent}:default"

    def _get_cache(self, user_id: str, cache_key: str) -> Optional[Dict[str, Any]]:
        """Get a cache entry if it exists and is not expired."""
        if user_id not in self._cache:
            return None

        entry = self._cache[user_id].get(cache_key)
        if not entry:
            return None

        # Check expiration
        ts = entry.get("timestamp")
        if ts:
            created = datetime.fromisoformat(ts)
            if datetime.now(timezone.utc) - created > timedelta(hours=self.CACHE_TTL_HOURS):
                del self._cache[user_id][cache_key]
                return None

        return entry

    def _set_cache(self, user_id: str, cache_key: str, response: str) -> None:
        """Set a cache entry."""
        if user_id not in self._cache:
            self._cache[user_id] = {}

        # Enforce max cache size
        if len(self._cache[user_id]) >= self.MAX_CACHE_SIZE_PER_USER:
            self._evict_oldest(user_id)

        self._cache[user_id][cache_key] = {
            "response": response,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "hits": 0,
        }

    def _evict_oldest(self, user_id: str) -> None:
        """Evict the oldest cache entry for a user."""
        if user_id not in self._cache or not self._cache[user_id]:
            return

        oldest_key = None
        oldest_time = None

        for key, entry in self._cache[user_id].items():
            ts = entry.get("timestamp")
            if ts:
                if oldest_time is None or ts < oldest_time:
                    oldest_time = ts
                    oldest_key = key

        if oldest_key:
            del self._cache[user_id][oldest_key]

    def _generate_cached_response(self, user_id: str, intent: str) -> Optional[str]:
        """Generate a response to cache for an intent."""
        import supabase_client as db

        # Get user context for personalization
        user_context = db.get_user_context(user_id)
        profile = user_context.get("profile", {}) if user_context else {}

        first_name = profile.get("first_name", "")

        # Generate template responses based on intent
        templates = {
            "greeting": [
                f"hey{' ' + first_name if first_name else ''}! what's good?",
                f"yo{' ' + first_name if first_name else ''}! what's up?",
                "hey! how's it going?",
            ],
            "small_talk": [
                "i'm good! just here whenever you need me",
                "doing well! what's on your mind?",
                "all good here! what can i help with?",
            ],
            "profile_question": [
                f"you're {first_name}, " if first_name else "let me check... ",
            ],
        }

        if intent in templates:
            import random
            return random.choice(templates[intent])

        return None


# Singleton export
response_cache = ResponseCache()
