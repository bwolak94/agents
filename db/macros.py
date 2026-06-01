"""
Prompt macros — named shortcuts that expand to full prompts.
Supports {{variable}} slot filling for templated macros.
"""
import re
from datetime import datetime, timezone

_db = None

_BUILTIN_MACROS: dict[str, str] = {
    "/code":     "Write clean, production-ready code for the following task. Include type annotations, error handling, and a brief explanation of the approach:\n\n",
    "/explain":  "Explain the following concept clearly. Start with a one-sentence summary, then give a detailed explanation with an analogy and a concrete example:\n\n",
    "/debug":    "Debug the following code or error. Identify the root cause, explain why it happens, and provide a minimal fix with explanation:\n\n",
    # F6 — quick-access shortcut aliases
    "/fix":      "Fix the following bug or error. Identify the root cause, explain why it happens, and provide the corrected code:\n\n",
    "/doc":      "Write clear, concise documentation (docstrings + README section) for the following code. Include parameters, return values, and usage examples:\n\n",
    "/refactor": "Refactor the following code to improve readability, performance, and maintainability. Preserve all existing behaviour. Explain each change:\n\n",
    "/test":     "Write comprehensive tests for the following code. Cover happy path, edge cases, and error conditions. Use pytest:\n\n",
    "/review":   "Review the following code for correctness, security vulnerabilities, performance issues, and style. Provide specific, actionable feedback:\n\n",
    "/summarize":"Summarize the following in 3-5 concise bullet points. Capture the key facts, decisions, and any action items:\n\n",
    "/tldr":     "Give me a TL;DR of the following in 2-3 sentences:\n\n",
    "/steps":    "Break down the following task into clear, numbered step-by-step instructions:\n\n",
    "/compare":  "Compare and contrast the following options. Present the analysis as a structured table with pros, cons, and a recommendation:\n\n",
    "/rewrite":  "Rewrite the following text to be clear, concise, and professional:\n\n",
    "/translate":"Translate the following text to English. Preserve tone and meaning:\n\n",
}


def set_db(db) -> None:
    global _db
    _db = db


async def ensure_indexes() -> None:
    if _db is None:
        return
    await _db["macros"].create_index([("name", 1)], unique=True)


async def save_macro(name: str, template: str, description: str = "") -> None:
    """Save or update a named macro."""
    if _db is None:
        return
    if not name.startswith("/"):
        name = "/" + name
    now = datetime.now(timezone.utc).isoformat()
    await _db["macros"].update_one(
        {"name": name},
        {"$set": {"name": name, "template": template, "description": description, "updated_at": now},
         "$setOnInsert": {"created_at": now}},
        upsert=True,
    )


async def get_macro(name: str) -> dict | None:
    """Return macro dict or None. Checks builtins first."""
    if not name.startswith("/"):
        name = "/" + name
    if name in _BUILTIN_MACROS:
        return {"name": name, "template": _BUILTIN_MACROS[name], "builtin": True}
    if _db is None:
        return None
    doc = await _db["macros"].find_one({"name": name}, {"_id": 0})
    return doc


async def list_macros() -> list[dict]:
    """Return all macros (builtins + user-defined)."""
    builtins = [
        {"name": k, "template": v, "description": "", "builtin": True}
        for k, v in _BUILTIN_MACROS.items()
    ]
    if _db is None:
        return builtins
    cursor = _db["macros"].find({}, {"_id": 0}).sort("name", 1)
    user_macros = await cursor.to_list(200)
    return builtins + user_macros


async def delete_macro(name: str) -> bool:
    """Delete a user-defined macro (cannot delete builtins)."""
    if not name.startswith("/"):
        name = "/" + name
    if name in _BUILTIN_MACROS:
        return False
    if _db is None:
        return False
    result = await _db["macros"].delete_one({"name": name})
    return result.deleted_count > 0


def expand_macro(text: str, variables: dict[str, str] | None = None) -> str:
    """Replace {{variable}} slots in a template."""
    if not variables:
        return text
    for k, v in variables.items():
        text = text.replace("{{" + k + "}}", v)
    return text


def extract_macro_from_message(message: str) -> tuple[str, str]:
    """
    If message starts with a macro name, return (macro_name, rest_of_message).
    Otherwise return ("", message).
    """
    stripped = message.strip()
    for macro in sorted(_BUILTIN_MACROS.keys(), key=len, reverse=True):
        if stripped.lower().startswith(macro):
            rest = stripped[len(macro):].strip()
            return macro, rest
    # Check user macro pattern /word
    match = re.match(r"^(/[a-zA-Z_\-]+)\s*(.*)", stripped, re.DOTALL)
    if match:
        return match.group(1), match.group(2)
    return "", message
