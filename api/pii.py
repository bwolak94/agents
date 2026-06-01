"""
Shared PII redaction utilities (#2).
Single source of truth for patterns used by:
  - api/server.py pii_redaction_middleware
  - api/routers/chat.py request-log scrubbing
"""
import re

_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"), "[EMAIL]"),
    (re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),  "[PHONE]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),                                      "[SSN]"),
    (re.compile(r"\b(?:4\d{12}(?:\d{3})?|5[1-5]\d{14}|3[47]\d{13}|6(?:011|5\d{2})\d{12})\b"), "[CARD]"),
]


def scrub(text: str) -> str:
    """Replace PII tokens with redaction placeholders."""
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


# Expose patterns list for middleware that needs to iterate them
PATTERNS = _PATTERNS
