"""
Four-Tier Memory System for Link AI.

Implements a living, evolving memory system that mirrors human memory:
- SHORT-TERM (0-48 hours): Everything, perfect recall
- MEDIUM-TERM (3-30 days): Selective, consolidated
- LONG-TERM (30 days - 6 months): Story arc, identity
- LIFETIME (Permanent): Sacred core, never forgotten

Memory decays naturally except for important events which are preserved.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Dict, Any, List, Optional, Set
import json
import re
import supabase_client as db


class MemoryTier(str, Enum):
    """Memory storage tiers with different retention and consolidation rules."""
    SHORT_TERM = "short_term"      # 0-48 hours, everything
    MEDIUM_TERM = "medium_term"    # 3-30 days, selective
    LONG_TERM = "long_term"        # 30 days - 6 months, story arc
    LIFETIME = "lifetime"          # Permanent, sacred core


class SensitivityLevel(int, Enum):
    """Sensitivity levels for memory privacy protection."""
    PUBLIC = 1        # Anyone could know (major, classes, clubs)
    PERSONAL = 2      # Friends might know (dating, general stress)
    PRIVATE = 3       # Close friends might know (mental health, family issues)
    DEEPLY_PRIVATE = 4  # User might tell therapist (trauma, abuse, suicidal thoughts)


class MemoryCategory(str, Enum):
    """Categories for organizing memories."""
    CONVERSATION = "conversation"
    EMOTIONAL = "emotional"
    BEHAVIORAL = "behavioral"
    FACT = "fact"
    PREFERENCE = "preference"
    RELATIONSHIP = "relationship"
    EVENT = "event"
    COMMITMENT = "commitment"
    BOUNDARY = "boundary"
    IDENTITY = "identity"


@dataclass
class MemoryEntry:
    """A single memory entry with metadata."""
    content: str
    category: MemoryCategory
    tier: MemoryTier
    importance: float  # 0-10
    sensitivity: SensitivityLevel
    created_at: datetime
    user_id: str

    # Optional metadata
    emotional_weight: float = 0.0
    related_topics: List[str] = field(default_factory=list)
    related_people: List[str] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)

    # Consolidation tracking
    consolidation_count: int = 0
    last_accessed: Optional[datetime] = None
    access_count: int = 0

    # Flags
    never_forget: bool = False  # Lifetime memory flag
    user_requested_forget: bool = False


class ImportanceCalculator:
    """
    Calculates memory importance score (0-10) based on:
    - Emotional weight (40%)
    - Personal significance (30%)
    - Actionability (20%)
    - Uniqueness (10%)
    """

    # Emotional indicators
    STRONG_EMOTIONS = {
        "excited", "thrilled", "amazing", "incredible", "best", "worst",
        "terrified", "devastated", "heartbroken", "overwhelmed", "depressed",
        "anxious", "scared", "crying", "tears", "love", "hate"
    }

    VULNERABLE_PHRASES = {
        "i need to tell you", "i've never told anyone", "this is hard to say",
        "i'm struggling", "i feel alone", "i can't handle", "i'm scared",
        "i don't know what to do", "help me", "i'm worried"
    }

    # Significance indicators
    IDENTITY_MARKERS = {
        "i am", "i'm a", "my major", "my passion", "i love", "i hate",
        "i always", "i never", "my dream", "my goal"
    }

    RELATIONSHIP_MARKERS = {
        "my mom", "my dad", "my parents", "my sister", "my brother",
        "my girlfriend", "my boyfriend", "my best friend", "dating",
        "broke up", "engaged", "married"
    }

    LIFE_EVENT_MARKERS = {
        "got the job", "got accepted", "got rejected", "diagnosed",
        "died", "passed away", "pregnant", "graduating", "dropping out",
        "moving", "got fired", "promoted"
    }

    # Actionability indicators
    EXPLICIT_REQUESTS = {
        "remind me", "don't forget", "remember that", "please remember",
        "never", "always", "don't message me", "don't bring up"
    }

    def calculate(self, content: str, context: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Calculate importance score for a piece of content.

        Returns:
            Dict with 'score' (0-10), 'breakdown', 'tier_recommendation'
        """
        content_lower = content.lower()
        context = context or {}

        # Calculate emotional weight (0-4 points, 40% of score)
        emotional = self._calculate_emotional_weight(content_lower, context)

        # Calculate personal significance (0-3 points, 30% of score)
        significance = self._calculate_significance(content_lower, context)

        # Calculate actionability (0-2 points, 20% of score)
        actionability = self._calculate_actionability(content_lower, context)

        # Calculate uniqueness (0-1 point, 10% of score)
        uniqueness = self._calculate_uniqueness(content_lower, context)

        total = emotional + significance + actionability + uniqueness

        # Determine tier recommendation
        if total >= 9:
            tier = MemoryTier.LIFETIME
        elif total >= 7:
            tier = MemoryTier.LONG_TERM
        elif total >= 4:
            tier = MemoryTier.MEDIUM_TERM
        else:
            tier = MemoryTier.SHORT_TERM

        # Determine sensitivity
        sensitivity = self._determine_sensitivity(content_lower, context)

        return {
            "score": min(10.0, total),
            "breakdown": {
                "emotional_weight": emotional,
                "personal_significance": significance,
                "actionability": actionability,
                "uniqueness": uniqueness,
            },
            "tier_recommendation": tier,
            "sensitivity": sensitivity,
        }

    def _calculate_emotional_weight(self, content: str, context: Dict) -> float:
        """Emotional weight: 0-4 points."""
        score = 0.0

        # Strong emotions present
        if any(word in content for word in self.STRONG_EMOTIONS):
            score += 2.0

        # Vulnerable phrases
        if any(phrase in content for phrase in self.VULNERABLE_PHRASES):
            score += 3.0

        # Context emotional indicators
        if context.get("user_emotional"):
            score += 1.0
        if context.get("user_crying") or context.get("user_laughing_hard"):
            score += 1.5

        return min(4.0, score)

    def _calculate_significance(self, content: str, context: Dict) -> float:
        """Personal significance: 0-3 points."""
        score = 0.0

        # Identity markers
        if any(marker in content for marker in self.IDENTITY_MARKERS):
            score += 1.5

        # Relationship markers
        if any(marker in content for marker in self.RELATIONSHIP_MARKERS):
            score += 2.0

        # Life event markers
        if any(marker in content for marker in self.LIFE_EVENT_MARKERS):
            score += 3.0

        return min(3.0, score)

    def _calculate_actionability(self, content: str, context: Dict) -> float:
        """Actionability: 0-2 points."""
        score = 0.0

        # Explicit requests
        if any(req in content for req in self.EXPLICIT_REQUESTS):
            score += 2.0

        # Future commitment or expectation
        if "will" in content or "going to" in content:
            if context.get("is_commitment"):
                score += 1.5

        # User expects Link to act on this
        if context.get("expects_followup"):
            score += 1.0

        return min(2.0, score)

    def _calculate_uniqueness(self, content: str, context: Dict) -> float:
        """Uniqueness: 0-1 point."""
        score = 0.0

        # First time sharing
        if context.get("first_time_topic"):
            score += 0.5

        # Rare occurrence
        if context.get("rare_event"):
            score += 0.5

        return min(1.0, score)

    def _determine_sensitivity(self, content: str, context: Dict) -> SensitivityLevel:
        """Determine sensitivity level of content."""

        # Level 4 - Deeply Private
        deeply_private_markers = {
            "abuse", "suicidal", "kill myself", "trauma", "assault",
            "raped", "molested", "cutting", "self harm", "eating disorder"
        }
        if any(marker in content for marker in deeply_private_markers):
            return SensitivityLevel.DEEPLY_PRIVATE

        # Level 3 - Private
        private_markers = {
            "depressed", "depression", "anxiety", "therapy", "therapist",
            "medication", "financial", "debt", "broke", "family problem",
            "parents fighting", "divorce"
        }
        if any(marker in content for marker in private_markers):
            return SensitivityLevel.PRIVATE

        # Level 2 - Personal
        personal_markers = {
            "dating", "relationship", "stressed", "struggling", "lonely",
            "worried about", "nervous", "failing"
        }
        if any(marker in content for marker in personal_markers):
            return SensitivityLevel.PERSONAL

        # Default - Public
        return SensitivityLevel.PUBLIC


class TieredMemoryManager:
    """
    Manages the four-tier memory system with consolidation and decay.
    """

    # Time windows
    SHORT_TERM_WINDOW = timedelta(hours=48)
    MEDIUM_TERM_WINDOW = timedelta(days=30)
    LONG_TERM_WINDOW = timedelta(days=180)  # 6 months

    # Importance thresholds for tier promotion
    MEDIUM_TERM_THRESHOLD = 4.0
    LONG_TERM_THRESHOLD = 7.0
    LIFETIME_THRESHOLD = 9.0

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.importance_calculator = ImportanceCalculator()

    def store_memory(
        self,
        content: str,
        category: MemoryCategory,
        context: Optional[Dict] = None,
        force_tier: Optional[MemoryTier] = None,
        force_importance: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Store a new memory, automatically calculating importance and tier.

        Returns:
            Dict with stored memory details
        """
        context = context or {}
        now = datetime.now(timezone.utc)

        # Calculate importance
        if force_importance is not None:
            importance_result = {
                "score": force_importance,
                "breakdown": {},
                "tier_recommendation": force_tier or MemoryTier.SHORT_TERM,
                "sensitivity": SensitivityLevel.PERSONAL,
            }
        else:
            importance_result = self.importance_calculator.calculate(content, context)

        importance = importance_result["score"]
        tier = force_tier or importance_result["tier_recommendation"]
        sensitivity = importance_result["sensitivity"]

        # Extract related entities
        related_people = self._extract_people(content)
        related_topics = self._extract_topics(content)

        # Build memory payload
        payload = {
            "user_id": self.user_id,
            "content": content,
            "category": category.value,
            "tier": tier.value,
            "importance": importance,
            "sensitivity": sensitivity.value,
            "emotional_weight": importance_result["breakdown"].get("emotional_weight", 0),
            "related_topics": related_topics,
            "related_people": related_people,
            "context": context,
            "created_at": now.isoformat(),
        }

        # Always start in short-term, but flag for immediate promotion if needed
        if tier == MemoryTier.LIFETIME:
            payload["never_forget"] = True
            # Also store in lifetime table immediately
            db.create_lifetime_memory(payload)

        # Store in appropriate tier table
        result = db.create_tiered_memory(payload)

        return {
            "memory_id": result.get("id"),
            "tier": tier.value,
            "importance": importance,
            "sensitivity": sensitivity.name,
        }

    def retrieve_memories(
        self,
        query: Optional[str] = None,
        tiers: Optional[List[MemoryTier]] = None,
        categories: Optional[List[MemoryCategory]] = None,
        time_range: Optional[tuple] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve memories with filtering.
        Searches all tiers in parallel for speed.
        """
        tiers = tiers or [MemoryTier.SHORT_TERM, MemoryTier.MEDIUM_TERM,
                          MemoryTier.LONG_TERM, MemoryTier.LIFETIME]

        all_memories = []

        for tier in tiers:
            tier_memories = db.get_tiered_memories(
                user_id=self.user_id,
                tier=tier.value,
                categories=[c.value for c in categories] if categories else None,
                time_range=time_range,
                limit=limit,
            )

            # Filter by query if provided
            if query:
                query_lower = query.lower()
                tier_memories = [
                    m for m in tier_memories
                    if query_lower in m.get("content", "").lower()
                    or any(query_lower in topic.lower() for topic in m.get("related_topics", []))
                ]

            all_memories.extend(tier_memories)

        # Sort by importance and recency
        all_memories.sort(
            key=lambda m: (m.get("importance", 0), m.get("created_at", "")),
            reverse=True
        )

        return all_memories[:limit]

    def get_conversation_context(self, conversation_id: str) -> Dict[str, Any]:
        """
        Get all relevant memory context for a conversation.
        Retrieves from all tiers with priority ordering.
        """
        now = datetime.now(timezone.utc)

        # SHORT-TERM: Everything from last 48 hours
        short_term_cutoff = now - self.SHORT_TERM_WINDOW
        short_term = self.retrieve_memories(
            tiers=[MemoryTier.SHORT_TERM],
            time_range=(short_term_cutoff, now),
            limit=100
        )

        # MEDIUM-TERM: Important patterns from last 30 days
        medium_term = self.retrieve_memories(
            tiers=[MemoryTier.MEDIUM_TERM],
            limit=50
        )

        # LONG-TERM: Story arc and identity
        long_term = self.retrieve_memories(
            tiers=[MemoryTier.LONG_TERM],
            limit=30
        )

        # LIFETIME: Critical info always included
        lifetime = self.retrieve_memories(
            tiers=[MemoryTier.LIFETIME],
            limit=50
        )

        return {
            "short_term": short_term,
            "medium_term": medium_term,
            "long_term": long_term,
            "lifetime": lifetime,
            "hard_rules": self._extract_hard_rules(lifetime),
            "important_relationships": self._extract_relationships(long_term + lifetime),
            "communication_preferences": self._extract_preferences(medium_term + long_term),
        }

    def consolidate_short_to_medium(self) -> Dict[str, Any]:
        """
        Daily consolidation: Move important short-term memories to medium-term.
        Run at 2:00 AM.
        """
        now = datetime.now(timezone.utc)
        cutoff = now - self.SHORT_TERM_WINDOW

        # Get expired short-term memories
        expired_memories = db.get_tiered_memories(
            user_id=self.user_id,
            tier=MemoryTier.SHORT_TERM.value,
            time_range=(None, cutoff),
            limit=1000
        )

        promoted = 0
        discarded = 0

        for memory in expired_memories:
            importance = memory.get("importance", 0)

            if importance >= self.MEDIUM_TERM_THRESHOLD:
                # Consolidate and promote
                consolidated = self._consolidate_memory(memory)
                consolidated["tier"] = MemoryTier.MEDIUM_TERM.value
                db.update_tiered_memory(memory["id"], consolidated)
                promoted += 1
            else:
                # Discard (delete from short-term)
                db.delete_tiered_memory(memory["id"])
                discarded += 1

        return {
            "processed": len(expired_memories),
            "promoted": promoted,
            "discarded": discarded,
        }

    def consolidate_medium_to_long(self) -> Dict[str, Any]:
        """
        Weekly consolidation: Move important medium-term memories to long-term.
        Run on Sundays at 1:00 AM.
        """
        now = datetime.now(timezone.utc)
        cutoff = now - self.MEDIUM_TERM_WINDOW

        # Get expired medium-term memories
        expired_memories = db.get_tiered_memories(
            user_id=self.user_id,
            tier=MemoryTier.MEDIUM_TERM.value,
            time_range=(None, cutoff),
            limit=500
        )

        promoted = 0
        discarded = 0

        for memory in expired_memories:
            importance = memory.get("importance", 0)

            if importance >= self.LONG_TERM_THRESHOLD:
                # Further consolidate and promote
                consolidated = self._deep_consolidate_memory(memory)
                consolidated["tier"] = MemoryTier.LONG_TERM.value
                db.update_tiered_memory(memory["id"], consolidated)
                promoted += 1
            else:
                # Discard
                db.delete_tiered_memory(memory["id"])
                discarded += 1

        return {
            "processed": len(expired_memories),
            "promoted": promoted,
            "discarded": discarded,
        }

    def forget_memory(self, topic: str) -> Dict[str, Any]:
        """
        User-requested deletion of memories about a topic.
        Searches and deletes from ALL tiers.
        """
        deleted_count = 0

        for tier in MemoryTier:
            memories = db.get_tiered_memories(
                user_id=self.user_id,
                tier=tier.value,
                limit=1000
            )

            for memory in memories:
                content = memory.get("content", "").lower()
                topics = [t.lower() for t in memory.get("related_topics", [])]
                people = [p.lower() for p in memory.get("related_people", [])]

                topic_lower = topic.lower()

                if (topic_lower in content or
                    topic_lower in topics or
                    topic_lower in people):
                    db.delete_tiered_memory(memory["id"])
                    deleted_count += 1

        return {
            "topic": topic,
            "deleted_count": deleted_count,
            "status": "complete",
        }

    def get_memory_summary(self) -> Dict[str, Any]:
        """
        Get a human-readable summary of what Link remembers about the user.
        """
        # Get all lifetime memories (core identity)
        lifetime = self.retrieve_memories(tiers=[MemoryTier.LIFETIME], limit=100)

        # Get long-term memories (story arc)
        long_term = self.retrieve_memories(tiers=[MemoryTier.LONG_TERM], limit=50)

        # Get recent medium-term (current situation)
        medium_term = self.retrieve_memories(tiers=[MemoryTier.MEDIUM_TERM], limit=30)

        # Organize by category
        summary = {
            "core_identity": [],
            "important_relationships": [],
            "communication_preferences": [],
            "hard_rules": [],
            "recent_context": [],
            "what_works": [],
            "what_doesnt_work": [],
        }

        for memory in lifetime:
            category = memory.get("category")
            content = memory.get("content", "")

            if category == "identity":
                summary["core_identity"].append(content)
            elif category == "relationship":
                summary["important_relationships"].append(content)
            elif category == "boundary":
                summary["hard_rules"].append(content)
            elif category == "preference":
                summary["communication_preferences"].append(content)

        for memory in long_term + medium_term:
            category = memory.get("category")
            content = memory.get("content", "")

            if category == "preference" and "works" in content.lower():
                summary["what_works"].append(content)
            elif category == "preference" and "doesn't" in content.lower():
                summary["what_doesnt_work"].append(content)
            else:
                summary["recent_context"].append(content)

        return summary

    # ============ Private Helpers ============

    def _extract_people(self, content: str) -> List[str]:
        """Extract mentioned people from content."""
        people = []

        # Common relationship references
        patterns = [
            r"my (mom|dad|mother|father|sister|brother|girlfriend|boyfriend|friend|roommate)",
            r"(sarah|emily|jordan|maya|jake|tom|alex)",  # Common names
        ]

        for pattern in patterns:
            matches = re.findall(pattern, content.lower())
            people.extend(matches)

        return list(set(people))

    def _extract_topics(self, content: str) -> List[str]:
        """Extract main topics from content."""
        topics = []

        # Academic
        if any(word in content.lower() for word in ["class", "exam", "study", "professor", "homework"]):
            topics.append("academic")

        # Social
        if any(word in content.lower() for word in ["friend", "party", "hang out", "dating", "meet"]):
            topics.append("social")

        # Emotional
        if any(word in content.lower() for word in ["stressed", "happy", "sad", "anxious", "excited"]):
            topics.append("emotional")

        # Family
        if any(word in content.lower() for word in ["mom", "dad", "family", "home", "parents"]):
            topics.append("family")

        # Career
        if any(word in content.lower() for word in ["job", "internship", "career", "interview", "work"]):
            topics.append("career")

        return topics

    def _consolidate_memory(self, memory: Dict) -> Dict:
        """Consolidate a memory for medium-term storage."""
        # Keep essence, reduce exact wording
        consolidated = dict(memory)
        consolidated["consolidation_count"] = memory.get("consolidation_count", 0) + 1

        # For conversations, summarize instead of exact quotes
        if memory.get("category") == "conversation":
            content = memory.get("content", "")
            # Simplified summarization
            if len(content) > 200:
                consolidated["content"] = content[:200] + "..."

        return consolidated

    def _deep_consolidate_memory(self, memory: Dict) -> Dict:
        """Deep consolidation for long-term storage."""
        consolidated = dict(memory)
        consolidated["consolidation_count"] = memory.get("consolidation_count", 0) + 1

        # Extract only the core meaning
        content = memory.get("content", "")

        # For very long content, extract key points
        if len(content) > 300:
            # Keep first and last sentences as summary
            sentences = content.split(".")
            if len(sentences) > 2:
                consolidated["content"] = sentences[0] + ". " + sentences[-1]

        return consolidated

    def _extract_hard_rules(self, memories: List[Dict]) -> List[str]:
        """Extract user's hard rules from lifetime memories."""
        rules = []

        rule_indicators = ["never", "always", "don't", "please don't", "don't message"]

        for memory in memories:
            content = memory.get("content", "").lower()
            if any(indicator in content for indicator in rule_indicators):
                rules.append(memory.get("content", ""))

        return rules

    def _extract_relationships(self, memories: List[Dict]) -> List[Dict]:
        """Extract important relationships from memories."""
        relationships = []
        seen_people = set()

        for memory in memories:
            for person in memory.get("related_people", []):
                if person not in seen_people:
                    seen_people.add(person)
                    relationships.append({
                        "person": person,
                        "context": memory.get("content", "")[:100],
                    })

        return relationships

    def _extract_preferences(self, memories: List[Dict]) -> Dict[str, Any]:
        """Extract communication preferences from memories."""
        preferences = {
            "timing": [],
            "tone": [],
            "approach": [],
        }

        for memory in memories:
            if memory.get("category") == "preference":
                content = memory.get("content", "")

                if any(word in content.lower() for word in ["morning", "evening", "night", "before", "after"]):
                    preferences["timing"].append(content)
                elif any(word in content.lower() for word in ["casual", "formal", "friendly", "direct"]):
                    preferences["tone"].append(content)
                else:
                    preferences["approach"].append(content)

        return preferences


# Singleton factory
def get_tiered_memory_manager(user_id: str) -> TieredMemoryManager:
    """Get a tiered memory manager for a specific user."""
    return TieredMemoryManager(user_id)
