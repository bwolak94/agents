"""Plugin marketplace — community tool definitions installable into the agent."""
import uuid

__all__ = ["set_db", "ensure_indexes", "list_plugins", "install_plugin", "uninstall_plugin"]
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorDatabase

_db: AsyncIOMotorDatabase | None = None

# Built-in catalogue shown before any DB records exist
_BUILTIN_PLUGINS = [
    {
        "plugin_id": "builtin-weather",
        "name": "weather",
        "description": "Fetch current weather for a location using Open-Meteo (free, no key).",
        "author": "community",
        "installed": False,
        "install_count": 142,
        "tool_definition": {"type": "http", "url": "https://api.open-meteo.com/v1/forecast"},
    },
    {
        "plugin_id": "builtin-calc",
        "name": "calculator",
        "description": "Safe expression evaluator — arithmetic, trig, logarithms.",
        "author": "community",
        "installed": False,
        "install_count": 311,
        "tool_definition": {"type": "python", "fn": "eval_expr"},
    },
    {
        "plugin_id": "builtin-summariser",
        "name": "url_summariser",
        "description": "Fetches a URL and returns a 3-sentence summary.",
        "author": "community",
        "installed": False,
        "install_count": 87,
        "tool_definition": {"type": "http", "url": "__internal__/summarise"},
    },
]


def set_db(db: AsyncIOMotorDatabase) -> None:
    global _db
    _db = db


async def ensure_indexes() -> None:
    if _db is None:
        return
    await _db["plugins"].create_index("name", unique=True)


async def list_plugins(installed_only: bool = False) -> list:
    db_plugins: list = []
    if _db is not None:
        query = {"installed": True} if installed_only else {}
        cursor = _db["plugins"].find(query, {"_id": 0}).sort("install_count", -1)
        db_plugins = await cursor.to_list(200)

    if installed_only:
        return db_plugins

    # Merge builtins with DB results (DB wins on name collision)
    db_names = {p["name"] for p in db_plugins}
    merged = db_plugins + [p for p in _BUILTIN_PLUGINS if p["name"] not in db_names]
    return merged


async def install_plugin(
    name: str,
    description: str,
    tool_definition: dict,
    author: str = "community",
) -> str:
    if _db is None:
        return ""
    plugin_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    await _db["plugins"].update_one(
        {"name": name},
        {
            "$set": {
                "plugin_id": plugin_id,
                "name": name,
                "description": description,
                "tool_definition": tool_definition,
                "author": author,
                "installed": True,
                "updated_at": now,
            },
            "$inc": {"install_count": 1},
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )
    return plugin_id


async def uninstall_plugin(name: str) -> bool:
    if _db is None:
        return False
    result = await _db["plugins"].update_one({"name": name}, {"$set": {"installed": False}})
    return result.modified_count > 0
