import re
from datetime import datetime, timedelta, timezone
import supabase_client as db


PROBING_RE = re.compile(r"\\bwhere\\s+is\\b|\\bwhere's\\b", re.IGNORECASE)
MAX_PROBES_PER_HOUR = 3


def is_probing(message: str) -> bool:
    return bool(PROBING_RE.search(message))


def should_rate_limit(user_id: str, message: str) -> bool:
    if not is_probing(message):
        return False
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=1)
    db.create_probe_event(user_id, message, reason="where_is_probe")
    count = db.count_probe_events(user_id, since)
    return count > MAX_PROBES_PER_HOUR
