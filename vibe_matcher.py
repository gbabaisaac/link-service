import re
from typing import Dict, Any, List, Optional
import supabase_client as db

class VibeMatcher:
    """
    Analyzes user messages to update their 'Vibe Profile' in the database.
    Tracks formality, slang usage, sentence length, and favorite emojis.
    """
    
    # Common Gen Z / Campus Slang (Expanded)
    SLANG_TERMS = {
        "fr", "frfr", "ngl", "tbh", "lowkey", "highkey", "rn", "idk", "idc", "imo",
        "lmk", "brb", "btw", "omg", "lol", "lmao", "lmfao", "wtf", "vibe", "vibes",
        "bet", "cap", "nocap", "deadass", "slay", "ate", "goated", "rizz", "sus",
        "mid", "based", "cringe", "fam", "bestie", "lit", "yeet", "tea", "simp",
        "cooked", "cooking", "lock in", "locked in", "yap", "yapping"
    }

    EMOJI_RE = re.compile(
        "["
        "\U0001F300-\U0001F5FF"
        "\U0001F600-\U0001F64F"
        "\U0001F680-\U0001F6FF"
        "\U0001F700-\U0001F77F"
        "\U0001F780-\U0001F7FF"
        "\U0001F800-\U0001F8FF"
        "\U0001F900-\U0001F9FF"
        "\U0001FA00-\U0001FA6F"
        "\U0001FA70-\U0001FAFF"
        "\u2600-\u26FF"
        "\u2700-\u27BF"
        "]+",
        flags=re.UNICODE,
    )

    def update_user_vibe(self, user_id: str, message_text: str, university_id: str) -> Dict[str, Any]:
        """
        Main entry point: Analyze message, merge with existing DB state, and save.
        """
        if not message_text:
            return {}

        # 1. Fetch existing vibe (or default)
        existing_vibe = db.get_user_vibe(user_id) or {
            "formality_level": 0.5,
            "slang_usage": 0.0,
            "favorite_emojis": [],
            "avg_sentence_length": 10.0
        }

        # 2. Analyze current message
        features = self._analyze_text(message_text)

        # 3. Moving Average Update (Weight new message by 20% to keep it responsive but stable)
        alpha = 0.2
        new_formality = (existing_vibe.get("formality_level", 0.5) * (1-alpha)) + (features["formality"] * alpha)
        new_slang = (existing_vibe.get("slang_usage", 0.0) * (1-alpha)) + (features["slang_density"] * alpha)
        new_length = (existing_vibe.get("avg_sentence_length", 10.0) * (1-alpha)) + (features["avg_length"] * alpha)
        
        # 4. Update Favorite Emojis (Simple frequency counter simulation)
        current_favs = existing_vibe.get("favorite_emojis") or []
        new_emojis = features["emojis"]
        # Just keep a set of top emojis for now (simplification)
        updated_favs = list(set(current_favs + new_emojis))[:10] 

        # 5. Generate Instructions for LLM
        prompt = self._generate_style_prompt(new_formality, new_slang, new_length, updated_favs)

        # 6. Save to DB
        payload = {
            "university_id": university_id,
            "formality_level": round(new_formality, 2),
            "slang_usage": round(new_slang, 2),
            "avg_sentence_length": round(new_length, 1),
            "favorite_emojis": updated_favs,
            "style_prompt": prompt
        }
        
        return db.upsert_user_vibe(user_id, payload)

    def _analyze_text(self, text: str) -> Dict[str, Any]:
        """Extract style features from a single message."""
        raw = text
        lowered = raw.lower()
        words = re.findall(r"[a-zA-Z0-9']+", raw)
        
        # Basics
        word_count = len(words)
        if word_count == 0:
            return {"formality": 0.5, "slang_density": 0.0, "avg_length": 0, "emojis": []}

        # Formality: Capitalization ratio
        upper_chars = sum(1 for c in raw if c.isupper())
        alpha_chars = sum(1 for c in raw if c.isalpha())
        cap_ratio = upper_chars / alpha_chars if alpha_chars > 0 else 0
        
        # Formality: Punctuation (Ending with period = more formal)
        has_period = 1.0 if raw.strip().endswith(".") else 0.0
        
        # Simple Logic: Caps + Punctuation = Formal. Lowercase + No punctuation = Casual.
        formality = (cap_ratio + has_period) / 2.0

        # Slang
        slang_hits = sum(1 for w in words if w.lower() in self.SLANG_TERMS)
        slang_density = slang_hits / word_count
        
        # Emojis
        emojis = self.EMOJI_RE.findall(raw)
        
        return {
            "formality": formality,
            "slang_density": slang_density,
            "avg_length": word_count,
            "emojis": emojis
        }

    def _generate_style_prompt(self, formality: float, slang: float, length: float, emojis: List[str]) -> str:
        """Create the system prompt string for Link to act into."""
        tone = "casual"
        if formality > 0.7: tone = "formal and proper"
        elif formality < 0.3: tone = "very laid back and lowercase"
        
        vocab = "standard english"
        if slang > 0.1: vocab = "heavy Gen Z slang (fr, rn, bet)"
        elif slang > 0.05: vocab = "occasional slang"
        
        emoji_hint = ""
        if emojis:
            emoji_hint = f"Use these emojis occasionally: {' '.join(emojis[:5])}."
            
        return (
            f"Adopt a {tone} tone. Use {vocab}. "
            f"Keep average sentence length around {int(length)} words. {emoji_hint}"
        )

# Singleton Export
vibe_matcher = VibeMatcher()
