from typing import List, Dict, Any, Optional
import json
import supabase_client as db
from link_logic import llm_json
from link_memory import vault

class MemoryManager:
    """
    Handles extracting facts (interests, preferences, facts) from user messages
     and persisting them to the encrypted Vault (link_memory).
    """

    def process_message(self, user_id: str, message: str) -> List[Dict[str, Any]]:
        """
        Extract facts and save to Vault with tier/priority.
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
            tier = fact.get("tier", "long") # 'long' or 'medium'
            priority = fact.get("priority", 1)
            
            if not plain_text: continue
            
            encrypted_value = vault.encrypt(plain_text)
            
            # 3. Persist to DB
            saved = db.create_encrypted_memory(
                user_id=user_id,
                encrypted_value=encrypted_value,
                category=category,
                source="chat",
                tier=tier,
                priority=priority
            )
            saved_facts.append(saved)
            
        return saved_facts

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
