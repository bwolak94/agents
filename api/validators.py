"""Shared validation helpers — no imports from other api.* modules."""
import re
from fastapi import HTTPException

SESSION_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")


def validate_session_id(session_id: str) -> str:
    if not SESSION_ID_RE.match(session_id):
        raise HTTPException(
            status_code=400,
            detail="session_id must be 1-64 alphanumeric characters, hyphens, or underscores.",
        )
    return session_id
