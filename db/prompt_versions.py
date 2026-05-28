"""
Semantic versioning for agent system prompts.
Each agent has a versioned history of system prompts.
"""
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_db = None


def set_db(database) -> None:
    global _db
    _db = database


async def ensure_indexes() -> None:
    await _db["prompt_versions"].create_index(
        [("agent_name", 1), ("version", -1)]
    )
    await _db["prompt_versions"].create_index(
        [("agent_name", 1), ("is_active", 1)]
    )


def _parse_semver(version: str) -> tuple[int, int, int]:
    parts = version.lstrip("v").split(".")
    return int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 0


def _bump_version(version: str, bump: str = "patch") -> str:
    major, minor, patch = _parse_semver(version)
    if bump == "major":
        return f"{major + 1}.0.0"
    elif bump == "minor":
        return f"{major}.{minor + 1}.0"
    else:
        return f"{major}.{minor}.{patch + 1}"


async def save_version(agent_name: str, system_prompt: str,
                        bump: str = "patch", author: str = "system",
                        changelog: str = "") -> str:
    """Save a new version of an agent's system prompt. Returns new version string."""
    # Get latest version
    latest = await _db["prompt_versions"].find_one(
        {"agent_name": agent_name, "is_active": True},
        sort=[("version", -1)]
    )
    if latest:
        new_version = _bump_version(latest["version"], bump)
        # Deactivate previous active
        await _db["prompt_versions"].update_many(
            {"agent_name": agent_name, "is_active": True},
            {"$set": {"is_active": False}},
        )
    else:
        new_version = "1.0.0"

    now = datetime.now(timezone.utc).isoformat()
    await _db["prompt_versions"].insert_one({
        "agent_name": agent_name,
        "version": new_version,
        "system_prompt": system_prompt,
        "is_active": True,
        "author": author,
        "changelog": changelog,
        "created_at": now,
    })
    return new_version


async def get_active_version(agent_name: str) -> dict | None:
    return await _db["prompt_versions"].find_one(
        {"agent_name": agent_name, "is_active": True},
        {"_id": 0},
        sort=[("version", -1)],
    )


async def get_version(agent_name: str, version: str) -> dict | None:
    return await _db["prompt_versions"].find_one(
        {"agent_name": agent_name, "version": version},
        {"_id": 0},
    )


async def list_versions(agent_name: str) -> list:
    cursor = _db["prompt_versions"].find(
        {"agent_name": agent_name},
        {"_id": 0, "agent_name": 0, "system_prompt": 0},
        sort=[("version", -1)],
    )
    return await cursor.to_list(length=50)


async def rollback_to(agent_name: str, version: str) -> bool:
    """Set a specific version as the active one."""
    target = await get_version(agent_name, version)
    if not target:
        return False
    await _db["prompt_versions"].update_many(
        {"agent_name": agent_name},
        {"$set": {"is_active": False}},
    )
    await _db["prompt_versions"].update_one(
        {"agent_name": agent_name, "version": version},
        {"$set": {"is_active": True}},
    )
    return True
