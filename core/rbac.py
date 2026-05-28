"""Role-Based Access Control.

Three roles: viewer (read-only), user (chat + read), admin (all endpoints).
API keys are mapped to roles via env vars defined in config.settings:
    ADMIN_API_KEY → role=admin
    USER_API_KEY  → role=user
    API_KEY       → role=user (legacy compat)
    (no key set)  → role=admin (open mode)
"""
import logging
import os
from enum import IntEnum

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from config.settings import ADMIN_API_KEY_ENV, API_KEY_ENV, USER_API_KEY_ENV

logger = logging.getLogger(__name__)


class Role(IntEnum):
    VIEWER = 0
    USER   = 1
    ADMIN  = 2


# Read-only HTTP methods
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

# Paths accessible to all roles (including viewers)
_VIEWER_PREFIXES = (
    "/", "/docs", "/openapi", "/redoc", "/health",
    "/models", "/analytics", "/marketplace", "/agents/collab-graph",
)

# Paths that require admin role
_ADMIN_PREFIXES = (
    "/admin", "/tenants", "/schedule", "/webhooks",
    "/canary", "/plugins", "/cache",
)


def _load_keys() -> dict[str, Role]:
    mapping: dict[str, Role] = {}
    for env_var, role in (
        (ADMIN_API_KEY_ENV, Role.ADMIN),
        (API_KEY_ENV,       Role.USER),
        (USER_API_KEY_ENV,  Role.USER),
    ):
        key = os.getenv(env_var, "")
        if key:
            mapping[key] = role
    return mapping


_KEY_ROLES: dict[str, Role] = _load_keys()


def get_role_for_key(api_key: str) -> Role:
    """Return the role associated with an API key, or ADMIN if auth is disabled."""
    if not _KEY_ROLES:
        return Role.ADMIN  # open mode — no keys configured
    return _KEY_ROLES.get(api_key, Role.VIEWER)


def require_role(minimum: Role):
    """FastAPI dependency factory: raises 403 if request role < minimum."""
    async def _check(request: Request):
        role = getattr(request.state, "role", Role.ADMIN)
        if role < minimum:
            raise HTTPException(
                status_code=403,
                detail=f"Requires role '{minimum.name}'. Your role: '{Role(role).name}'.",
            )
    return _check


require_user  = require_role(Role.USER)
require_admin = require_role(Role.ADMIN)


async def rbac_middleware(request: Request, call_next):
    """Inject request.state.role based on Bearer token."""
    auth = request.headers.get("Authorization", "")
    token = auth.removeprefix("Bearer ").strip()
    role = get_role_for_key(token)
    request.state.role = role

    if role == Role.VIEWER and request.method not in _SAFE_METHODS:
        return JSONResponse(
            status_code=403,
            content={"detail": "Viewer role cannot perform write operations."},
        )

    if role < Role.ADMIN and any(request.url.path.startswith(p) for p in _ADMIN_PREFIXES):
        return JSONResponse(
            status_code=403,
            content={"detail": "This endpoint requires admin role."},
        )

    return await call_next(request)
