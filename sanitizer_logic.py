import re
from typing import Dict, Any, Optional


EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
PHONE_RE = re.compile(r"(\+?\d{1,3}[\s-]?)?(\(?\d{3}\)?[\s-]?)\d{3}[\s-]?\d{4}")
HANDLE_RE = re.compile(r"@\w+")
URL_RE = re.compile(r"https?://\S+")


def _redact_pii(text: str) -> str:
    text = EMAIL_RE.sub("[redacted]", text)
    text = PHONE_RE.sub("[redacted]", text)
    text = HANDLE_RE.sub("[redacted]", text)
    text = URL_RE.sub("[redacted]", text)
    return text


def sanitize_text(text: str, known_pii: Optional[list[str]] = None) -> str:
    sanitized = _redact_pii(text)
    if known_pii:
        for token in known_pii:
            if not token:
                continue
            sanitized = sanitized.replace(token, "[redacted]")
    return sanitized


def build_public_tags(user_context: Dict[str, Any]) -> Dict[str, Any]:
    profile = user_context.get("profile") or {}
    interests = profile.get("interests") or []
    major = profile.get("major")
    year = profile.get("grad_year") or profile.get("year")
    tags: Dict[str, Any] = {
        "interests": interests,
    }
    if major:
        tags["major"] = major
    if year:
        tags["year"] = year
    return tags
