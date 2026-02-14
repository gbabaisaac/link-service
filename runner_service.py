import random
from datetime import datetime, timezone
from typing import Any
import supabase_client as db


MAX_TARGETS = 5


def _matches_tags(profile: dict, tags: dict) -> bool:
    major = tags.get("major")
    interests = tags.get("interests") or []
    if major and profile.get("major") != major:
        return False
    if interests:
        prof_interests = profile.get("interests") or []
        overlap = set(i.lower() for i in interests) & set(i.lower() for i in prof_interests)
        return bool(overlap)
    return True


def _select_targets(university_id: str, tags: dict, limit: int = MAX_TARGETS) -> list[dict]:
    profiles = db.get_profiles_runner(university_id=university_id, limit=500)
    if not profiles:
        return []
    matched = [p for p in profiles if _matches_tags(p, tags)]
    pool = matched if matched else profiles
    random.shuffle(pool)
    return pool[:limit]


def _send_anonymous_outreach(link_user_id: str, target_user_id: str, text: str, work_order_id: str) -> None:
    convo = db.get_or_create_dm_conversation_runner(link_user_id, target_user_id)
    if not convo:
        return
    db.insert_message_runner(convo["id"], link_user_id, text, {"shareType": "text", "work_order_id": work_order_id})


def wipe_state(*objs: Any) -> None:
    for obj in objs:
        try:
            if isinstance(obj, dict):
                obj.clear()
            elif isinstance(obj, list):
                obj.clear()
        except Exception:
            pass


def process_pending_work_orders(limit: int = 25) -> int:
    orders = db.list_pending_work_orders_runner(limit=limit)
    if not orders:
        return 0

    for order in orders:
        try:
            db.update_work_order_status_runner(order["id"], "processing")
            university_id = order["university_id"]
            tags = order.get("public_tags") or {}
            targets = _select_targets(university_id, tags, limit=MAX_TARGETS)

            link_profile = db.get_link_system_profile_runner(university_id)
            link_user_id = link_profile.get("link_user_id") if link_profile else None
            message_text = f"Someone is looking for: \"{order.get('query')}\". Reply YES if you can help."

            for t in targets:
                if not link_user_id:
                    break
                db.create_work_order_result_runner(
                    {
                        "work_order_id": order["id"],
                        "target_user_id": t["id"],
                        "status": "notified",
                    }
                )
                _send_anonymous_outreach(link_user_id, t["id"], message_text, order["id"])

            db.update_work_order_status_runner(order["id"], "completed")
        except Exception:
            db.update_work_order_status_runner(order["id"], "failed")
        finally:
            wipe_state(order, tags, targets)

    return len(orders)


if __name__ == "__main__":
    processed = process_pending_work_orders()
    print(f"[{datetime.now(timezone.utc).isoformat()}] Processed {processed} work orders")
