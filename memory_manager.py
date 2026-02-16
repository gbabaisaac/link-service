from typing import List, Dict, Any, Optional
import json
import supabase_client as db
from link_logic import llm_json
from link_memory import vault

# Import tiered memory system
try:
    from tiered_memory import (
        TieredMemoryManager,
        ImportanceCalculator,
        MemoryCategory,
        MemoryTier,
        get_tiered_memory_manager
    )
    TIERED_MEMORY_AVAILABLE = True
except ImportError:
    TIERED_MEMORY_AVAILABLE = False


class MemoryManager:
    """
    Handles extracting facts (interests, preferences, facts) from user messages
    and persisting them to the encrypted Vault (link_memory) AND the tiered memory system.
    """

    # Map old categories to new MemoryCategory
    CATEGORY_MAP = {
        "preferences": "preference",
        "facts": "fact",
        "interests": "preference",
        "events": "event",
        "relationships": "relationship",
        "commitments": "commitment",
    }

    # Map old tier names to new MemoryTier
    TIER_MAP = {
        "long": MemoryTier.LONG_TERM if TIERED_MEMORY_AVAILABLE else "long",
        "medium": MemoryTier.MEDIUM_TERM if TIERED_MEMORY_AVAILABLE else "medium",
    }

    def process_message(self, user_id: str, message: str, context: Optional[Dict] = None) -> List[Dict[str, Any]]:
        """
        Extract facts and save to Vault with tier/priority.
        Also stores in the four-tier memory system if available.
        """
        # If vault is not initialized, skip memory storage
        if vault is None:
            return []

        # 1. Extract facts using LLM (with Tiering)
        facts = self._extract_facts(message)
        if not facts:
            return []

        saved_facts = []
        for fact in facts:
            # 2. Encrypt
            plain_text = fact.get("content")
            category = fact.get("category", "preferences")
            tier = fact.get("tier", "long")  # 'long' or 'medium'
            priority = fact.get("priority", 1)

            if not plain_text:
                continue

            encrypted_value = vault.encrypt(plain_text)

            # 3. Persist to encrypted DB (legacy)
            saved = db.create_encrypted_memory(
                user_id=user_id,
                encrypted_value=encrypted_value,
                category=category,
                source="chat",
                tier=tier,
                priority=priority
            )
            saved_facts.append(saved)

            # 4. Also store in tiered memory system (new system)
            if TIERED_MEMORY_AVAILABLE:
                self._store_in_tiered_system(user_id, plain_text, category, context or {})

        return saved_facts

    def _store_in_tiered_system(self, user_id: str, content: str, category: str, context: Dict) -> Optional[Dict]:
        """Store a fact in the four-tier memory system."""
        try:
            manager = get_tiered_memory_manager(user_id)

            # Map category
            mapped_category = self.CATEGORY_MAP.get(category, "fact")
            memory_category = MemoryCategory(mapped_category)

            # Store (let the importance calculator determine tier)
            result = manager.store_memory(
                content=content,
                category=memory_category,
                context=context,
            )
            return result
        except Exception:
            # Fail silently - tiered memory is enhancement, not critical
            return None

    def store_tiered_memory(
        self,
        user_id: str,
        content: str,
        category: str = "fact",
        context: Optional[Dict] = None
    ) -> Optional[Dict]:
        """
        Direct interface to store a memory in the tiered system.
        Use this for explicit memory storage outside of message processing.
        """
        if not TIERED_MEMORY_AVAILABLE:
            return None

        try:
            manager = get_tiered_memory_manager(user_id)

            mapped_category = self.CATEGORY_MAP.get(category, category)
            try:
                memory_category = MemoryCategory(mapped_category)
            except ValueError:
                memory_category = MemoryCategory.FACT

            return manager.store_memory(
                content=content,
                category=memory_category,
                context=context or {},
            )
        except Exception:
            return None

    def get_tiered_context(self, user_id: str) -> Dict[str, Any]:
        """
        Get full tiered memory context for a conversation.
        Returns organized memories from all tiers.
        """
        if not TIERED_MEMORY_AVAILABLE:
            return {"error": "Tiered memory not available"}

        try:
            manager = get_tiered_memory_manager(user_id)
            return manager.get_conversation_context(user_id)
        except Exception as e:
            return {"error": str(e)}

    def get_memory_summary(self, user_id: str) -> Dict[str, Any]:
        """
        Get a human-readable summary of what Link remembers about the user.
        """
        if not TIERED_MEMORY_AVAILABLE:
            # Fallback to legacy system
            return self._get_legacy_summary(user_id)

        try:
            manager = get_tiered_memory_manager(user_id)
            return manager.get_memory_summary()
        except Exception:
            return self._get_legacy_summary(user_id)

    def _get_legacy_summary(self, user_id: str) -> Dict[str, Any]:
        """Get memory summary from legacy encrypted storage."""
        facts = self.get_decrypted_facts(user_id)
        return {
            "core_identity": [f["content"] for f in facts if f.get("tier") == "long"],
            "recent_context": [f["content"] for f in facts if f.get("tier") == "medium"],
        }

    def forget_topic(self, user_id: str, topic: str) -> Dict[str, Any]:
        """
        User-requested deletion of memories about a topic.
        Deletes from both legacy and tiered systems.
        """
        result = {"legacy_deleted": 0, "tiered_deleted": 0}

        # Delete from tiered system
        if TIERED_MEMORY_AVAILABLE:
            try:
                manager = get_tiered_memory_manager(user_id)
                tiered_result = manager.forget_memory(topic)
                result["tiered_deleted"] = tiered_result.get("deleted_count", 0)
            except Exception:
                pass

        # TODO: Also delete from legacy encrypted storage if needed

        return result

    def get_decrypted_facts(self, user_id: str, category: Optional[str] = None, tier: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch and decrypt facts, returning rich objects with tier/priority."""
        # If vault is not initialized, return empty
        if vault is None:
            return []

        encrypted_rows = db.list_encrypted_memories(user_id, category=category)
        
        results = []
        for row in encrypted_rows:
            if tier and row.get("tier") != tier:
                continue
            try:
                decrypted = vault.decrypt(row["encrypted_value"])
                results.append({
                    "content": decrypted,
                    "tier": row.get("tier", "long"),
                    "priority": row.get("priority", 1),
                    "category": row.get("category")
                })
            except Exception:
                continue
        # Sort by priority
        results.sort(key=lambda x: x["priority"], reverse=True)
        return results

    def _extract_facts(self, message: str) -> List[Dict[str, Any]]:
        """Use LLM to identify facts/interests and rank their 'Tier'."""
        prompt = f"""You are a memory assistant for 'Link'. 
        Extract facts/interests and categorize them into Tiers:
        - LONG: Permanent facts (Likes basketball, Birthday, Major).
        - MEDIUM: Situational context (Looking for a job, Studying for midterms, Feeling stressed).
        
        Rank PRIORITY from 1 (Small detail) to 5 (Crucial for a friend to know).
        
        Examples:
        - "I like basketball" -> {{"content": "Likes basketball", "category": "preferences", "tier": "long", "priority": 3}}
        - "I'm looking for a summer internship" -> {{"content": "Looking for summer internship", "category": "facts", "tier": "medium", "priority": 5}}
        - "I love red velvet cake" -> {{"content": "Loves red velvet cake", "category": "preferences", "tier": "long", "priority": 2}}
        
        Message: "{message}"
        
        Return JSON list: [{{"content": "...", "category": "...", "tier": "...", "priority": <int>}}]
        If no facts found, return empty list []."""
        
        try:
            result = llm_json(prompt, temperature=0.1)
            if isinstance(result, list):
                return result
            return []
        except Exception:
            return []

memory_manager = MemoryManager()
