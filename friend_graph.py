"""
Friend Graph for Link AI.

Builds and maintains user relationship networks:
- Connection tracking (friends, classmates, clubmates)
- Relationship strength calculation
- Connection suggestions
- Common connection discovery
"""

from __future__ import annotations
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Set, Tuple
from collections import defaultdict
import supabase_client as db


class FriendGraph:
    """
    Manages the social graph of user connections.
    Provides relationship analysis and connection suggestions.
    """

    # Connection type weights for suggestions
    CONNECTION_WEIGHTS = {
        "friend": 1.0,
        "classmate": 0.7,
        "clubmate": 0.6,
        "roommate": 0.9,
    }

    # Minimum strength threshold for suggestions
    MIN_SUGGESTION_STRENGTH = 0.3

    def get_connections(
        self,
        user_id: str,
        depth: int = 1,
        connection_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get user connections up to a certain depth.

        Args:
            user_id: The user to get connections for
            depth: How many degrees of separation (1=direct, 2=friends of friends)
            connection_type: Optional filter by connection type

        Returns:
            List of connection dicts with user info and relationship data
        """
        if depth < 1:
            return []

        # Get direct connections
        direct = db.get_user_connections(user_id, connection_type)

        # Enrich with user profile info
        connections = []
        for conn in direct:
            other_user_id = conn["user_b"] if conn["user_a"] == user_id else conn["user_a"]

            profile = db.get_profile(other_user_id, enforce_public=True)
            if not profile:
                continue

            connections.append({
                "user_id": other_user_id,
                "connection_type": conn.get("connection_type"),
                "strength": conn.get("strength", 0.5),
                "depth": 1,
                "profile": {
                    "first_name": profile.get("first_name"),
                    "last_name": profile.get("last_name"),
                    "major": profile.get("major"),
                    "interests": profile.get("interests", []),
                },
            })

        if depth == 1:
            return connections

        # Get second-degree connections
        seen_ids = {user_id} | {c["user_id"] for c in connections}
        second_degree = []

        for conn in connections:
            friend_id = conn["user_id"]
            friend_connections = db.get_user_connections(friend_id, connection_type)

            for fc in friend_connections:
                other_id = fc["user_b"] if fc["user_a"] == friend_id else fc["user_a"]

                if other_id in seen_ids:
                    continue

                seen_ids.add(other_id)
                profile = db.get_profile(other_id, enforce_public=True)
                if not profile:
                    continue

                # Calculate combined strength
                combined_strength = conn["strength"] * fc.get("strength", 0.5) * 0.5

                second_degree.append({
                    "user_id": other_id,
                    "connection_type": fc.get("connection_type"),
                    "strength": combined_strength,
                    "depth": 2,
                    "connected_through": conn["user_id"],
                    "profile": {
                        "first_name": profile.get("first_name"),
                        "last_name": profile.get("last_name"),
                        "major": profile.get("major"),
                        "interests": profile.get("interests", []),
                    },
                })

        return connections + second_degree

    def find_common_connections(
        self,
        user_a: str,
        user_b: str,
    ) -> List[Dict[str, Any]]:
        """
        Find users connected to both user_a and user_b.

        Returns:
            List of common connection dicts
        """
        connections_a = db.get_user_connections(user_a)
        connections_b = db.get_user_connections(user_b)

        # Extract user IDs from connections
        ids_a = set()
        for c in connections_a:
            ids_a.add(c["user_b"] if c["user_a"] == user_a else c["user_a"])

        ids_b = set()
        for c in connections_b:
            ids_b.add(c["user_b"] if c["user_a"] == user_b else c["user_a"])

        # Find intersection
        common_ids = ids_a & ids_b

        # Build result with profile info
        common = []
        for uid in common_ids:
            profile = db.get_profile(uid, enforce_public=True)
            if profile:
                common.append({
                    "user_id": uid,
                    "profile": {
                        "first_name": profile.get("first_name"),
                        "last_name": profile.get("last_name"),
                    },
                })

        return common

    def get_relationship_strength(
        self,
        user_a: str,
        user_b: str,
    ) -> float:
        """
        Calculate the relationship strength between two users.

        Returns:
            Float between 0 (no relationship) and 1 (strong relationship)
        """
        # Check direct connection
        connection = db.get_connection_between(user_a, user_b)
        if connection:
            return connection.get("strength", 0.5)

        # Check for indirect connections
        common = self.find_common_connections(user_a, user_b)
        if common:
            # Indirect strength based on number of common connections
            return min(0.3 + len(common) * 0.1, 0.5)

        # Check for shared classes
        shared_classes = self._get_shared_classes(user_a, user_b)
        if shared_classes:
            return min(0.2 + len(shared_classes) * 0.1, 0.4)

        # Check for shared organizations
        shared_orgs = self._get_shared_organizations(user_a, user_b)
        if shared_orgs:
            return min(0.15 + len(shared_orgs) * 0.1, 0.35)

        return 0.0

    def suggest_connections(
        self,
        user_id: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Suggest new connections for a user based on various signals.

        Returns:
            List of suggested user dicts with reasons
        """
        suggestions = []
        seen_ids = {user_id}

        # Get existing connections to exclude
        existing = db.get_user_connections(user_id)
        for c in existing:
            seen_ids.add(c["user_b"] if c["user_a"] == user_id else c["user_a"])

        # Get user context for matching
        user_context = db.get_user_context(user_id)
        profile = user_context.get("profile", {}) if user_context else {}
        user_interests = set(i.lower() for i in profile.get("interests", []))
        user_major = (profile.get("major") or "").lower()
        university_id = profile.get("university_id")

        # Strategy 1: Friends of friends
        fof_suggestions = self._suggest_friends_of_friends(user_id, seen_ids)
        suggestions.extend(fof_suggestions)

        # Strategy 2: Classmates
        classmate_suggestions = self._suggest_classmates(user_id, seen_ids)
        suggestions.extend(classmate_suggestions)

        # Strategy 3: Similar interests
        interest_suggestions = self._suggest_by_interests(
            user_id, user_interests, university_id, seen_ids
        )
        suggestions.extend(interest_suggestions)

        # Strategy 4: Same major
        if user_major:
            major_suggestions = self._suggest_by_major(
                user_id, user_major, university_id, seen_ids
            )
            suggestions.extend(major_suggestions)

        # Deduplicate and sort by score
        unique_suggestions = {}
        for s in suggestions:
            uid = s["user_id"]
            if uid not in unique_suggestions or s["score"] > unique_suggestions[uid]["score"]:
                unique_suggestions[uid] = s

        sorted_suggestions = sorted(
            unique_suggestions.values(),
            key=lambda x: x["score"],
            reverse=True
        )

        return sorted_suggestions[:limit]

    def create_connection(
        self,
        user_a: str,
        user_b: str,
        connection_type: str = "friend",
        source: str = "manual",
    ) -> Dict[str, Any]:
        """
        Create a connection between two users.

        Returns:
            Created connection dict
        """
        # Ensure consistent ordering
        if user_a > user_b:
            user_a, user_b = user_b, user_a

        # Check if connection already exists
        existing = db.get_connection_between(user_a, user_b)
        if existing:
            # Update existing connection
            return db.update_connection_strength(
                existing["id"],
                min(existing.get("strength", 0.5) + 0.1, 1.0)
            )

        # Create new connection
        return db.create_user_connection({
            "user_a": user_a,
            "user_b": user_b,
            "connection_type": connection_type,
            "source": source,
            "strength": 0.5,
        })

    def update_interaction(
        self,
        user_a: str,
        user_b: str,
        interaction_type: str = "message",
    ) -> Optional[Dict[str, Any]]:
        """
        Update connection strength based on interaction.

        Returns:
            Updated connection dict or None
        """
        connection = db.get_connection_between(user_a, user_b)
        if not connection:
            return None

        # Increase strength based on interaction
        strength_delta = {
            "message": 0.02,
            "meetup": 0.1,
            "collaboration": 0.15,
            "mention": 0.01,
        }.get(interaction_type, 0.01)

        new_strength = min(connection.get("strength", 0.5) + strength_delta, 1.0)

        return db.update_connection_strength(connection["id"], new_strength)

    def infer_connections_from_classes(self, user_id: str) -> List[Dict]:
        """
        Automatically infer classmate connections.

        Returns:
            List of created connections
        """
        classmates = db.get_classmates(user_id)
        created = []

        for classmate_id in classmates:
            if classmate_id == user_id:
                continue

            # Check if connection exists
            existing = db.get_connection_between(user_id, classmate_id)
            if existing:
                continue

            conn = self.create_connection(
                user_id,
                classmate_id,
                connection_type="classmate",
                source="inferred"
            )
            created.append(conn)

        return created

    # ============ Private Helpers ============

    def _suggest_friends_of_friends(
        self,
        user_id: str,
        seen_ids: Set[str],
    ) -> List[Dict[str, Any]]:
        """Generate suggestions from friends of friends."""
        suggestions = []
        connections = db.get_user_connections(user_id)

        for conn in connections[:10]:  # Limit to avoid too many queries
            friend_id = conn["user_b"] if conn["user_a"] == user_id else conn["user_a"]
            friend_connections = db.get_user_connections(friend_id)

            for fc in friend_connections[:10]:
                fof_id = fc["user_b"] if fc["user_a"] == friend_id else fc["user_a"]

                if fof_id in seen_ids:
                    continue

                seen_ids.add(fof_id)
                profile = db.get_profile(fof_id, enforce_public=True)
                if not profile:
                    continue

                # Calculate suggestion score
                score = conn.get("strength", 0.5) * fc.get("strength", 0.5)

                suggestions.append({
                    "user_id": fof_id,
                    "score": score,
                    "reason": f"Friends with {self._get_name(friend_id)}",
                    "profile": {
                        "first_name": profile.get("first_name"),
                        "last_name": profile.get("last_name"),
                        "major": profile.get("major"),
                    },
                })

        return suggestions

    def _suggest_classmates(
        self,
        user_id: str,
        seen_ids: Set[str],
    ) -> List[Dict[str, Any]]:
        """Generate suggestions from classmates."""
        suggestions = []
        classmates = db.get_classmates(user_id)

        for classmate_id in classmates[:20]:
            if classmate_id in seen_ids:
                continue

            seen_ids.add(classmate_id)
            profile = db.get_profile(classmate_id, enforce_public=True)
            if not profile:
                continue

            suggestions.append({
                "user_id": classmate_id,
                "score": 0.6,
                "reason": "In your class",
                "profile": {
                    "first_name": profile.get("first_name"),
                    "last_name": profile.get("last_name"),
                    "major": profile.get("major"),
                },
            })

        return suggestions

    def _suggest_by_interests(
        self,
        user_id: str,
        user_interests: Set[str],
        university_id: Optional[str],
        seen_ids: Set[str],
    ) -> List[Dict[str, Any]]:
        """Generate suggestions based on shared interests."""
        suggestions = []

        if not user_interests or not university_id:
            return suggestions

        # Get profiles with overlapping interests
        profiles = db.get_profiles(university_id, limit=100)

        for profile in profiles:
            pid = profile.get("id")
            if pid in seen_ids:
                continue

            profile_interests = set(i.lower() for i in profile.get("interests", []))
            shared = user_interests & profile_interests

            if len(shared) >= 2:
                seen_ids.add(pid)
                score = min(0.3 + len(shared) * 0.1, 0.7)

                suggestions.append({
                    "user_id": pid,
                    "score": score,
                    "reason": f"Shared interests: {', '.join(list(shared)[:3])}",
                    "profile": {
                        "first_name": profile.get("first_name"),
                        "last_name": profile.get("last_name"),
                        "major": profile.get("major"),
                    },
                })

        return suggestions[:10]

    def _suggest_by_major(
        self,
        user_id: str,
        user_major: str,
        university_id: Optional[str],
        seen_ids: Set[str],
    ) -> List[Dict[str, Any]]:
        """Generate suggestions based on same major."""
        suggestions = []

        if not university_id:
            return suggestions

        profiles = db.get_profiles(university_id, limit=100)

        for profile in profiles:
            pid = profile.get("id")
            if pid in seen_ids:
                continue

            profile_major = (profile.get("major") or "").lower()
            if profile_major and user_major in profile_major:
                seen_ids.add(pid)

                suggestions.append({
                    "user_id": pid,
                    "score": 0.4,
                    "reason": f"Same major: {profile.get('major')}",
                    "profile": {
                        "first_name": profile.get("first_name"),
                        "last_name": profile.get("last_name"),
                        "major": profile.get("major"),
                    },
                })

        return suggestions[:5]

    def _get_shared_classes(self, user_a: str, user_b: str) -> List[str]:
        """Get classes shared by two users."""
        classmates_a = set(db.get_classmates(user_a))
        if user_b in classmates_a:
            # They share at least one class
            return ["shared_class"]  # Simplified
        return []

    def _get_shared_organizations(self, user_a: str, user_b: str) -> List[str]:
        """Get organizations shared by two users."""
        context_a = db.get_user_context(user_a)
        context_b = db.get_user_context(user_b)

        clubs_a = set(c.get("id") for c in context_a.get("clubs", []) if c.get("id"))
        clubs_b = set(c.get("id") for c in context_b.get("clubs", []) if c.get("id"))

        return list(clubs_a & clubs_b)

    def _get_name(self, user_id: str) -> str:
        """Get display name for a user."""
        profile = db.get_profile(user_id, enforce_public=True)
        if profile:
            return profile.get("first_name") or "a friend"
        return "a friend"


# Singleton export
friend_graph = FriendGraph()
