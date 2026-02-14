import logging
import re


EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\\.[A-Z]{2,}", re.IGNORECASE)
PHONE_RE = re.compile(r"(\\+?\\d{1,3}[\\s-]?)?(\\(?\\d{3}\\)?[\\s-]?)\\d{3}[\\s-]?\\d{4}")
HANDLE_RE = re.compile(r"@\\w+")


class PiiRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = str(record.getMessage())
        message = EMAIL_RE.sub("[redacted]", message)
        message = PHONE_RE.sub("[redacted]", message)
        message = HANDLE_RE.sub("[redacted]", message)
        record.msg = message
        record.args = ()
        return True


def configure_logging() -> None:
    root = logging.getLogger()
    if not any(isinstance(f, PiiRedactionFilter) for f in root.filters):
        root.addFilter(PiiRedactionFilter())
