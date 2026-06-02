"""#1 — Agent memory graph: persist named facts/relationships across sessions.

Schema: {session_id, entity, relation, value, confidence, ts}
Supports: upsert by (session_id, entity, relation), fuzzy search, export.
"""
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)
_db = None


def set_db(db) -> None:
    global _db
    _db = db


async def ensure_indexes() -> None:
    if _db is None:
        return
    await _db["memory_graph"].create_index([("session_id", 1), ("entity", 1), ("relation", 1)], unique=True)
    await _db["memory_graph"].create_index([("entity", "text"), ("value", "text")])


async def upsert_fact(session_id: str, entity: str, relation: str, value: str, confidence: float = 1.0) -> dict:
    """Store or update a single fact triple (entity, relation, value)."""
    if _db is None:
        return {}
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "session_id": session_id,
        "entity": entity.lower().strip(),
        "relation": relation.lower().strip(),
        "value": value,
        "confidence": max(0.0, min(1.0, confidence)),
        "updated_at": now,
    }
    await _db["memory_graph"].update_one(
        {"session_id": session_id, "entity": doc["entity"], "relation": doc["relation"]},
        {"$set": doc, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    return doc


async def get_facts(session_id: str, entity: str | None = None, relation: str | None = None) -> list[dict]:
    """Retrieve facts for a session, optionally filtered by entity or relation."""
    if _db is None:
        return []
    filt: dict = {"session_id": session_id}
    if entity:
        filt["entity"] = entity.lower().strip()
    if relation:
        filt["relation"] = relation.lower().strip()
    cursor = _db["memory_graph"].find(filt, {"_id": 0}).sort("updated_at", -1).limit(200)
    return await cursor.to_list(200)


async def search_facts(session_id: str, query: str, limit: int = 10) -> list[dict]:
    """Full-text search over entity/value fields."""
    if _db is None:
        return []
    try:
        cursor = _db["memory_graph"].find(
            {"session_id": session_id, "$text": {"$search": query}},
            {"_id": 0, "score": {"$meta": "textScore"}},
        ).sort([("score", {"$meta": "textScore"})]).limit(limit)
        return await cursor.to_list(limit)
    except Exception:
        return []


async def delete_fact(session_id: str, entity: str, relation: str) -> bool:
    if _db is None:
        return False
    r = await _db["memory_graph"].delete_one(
        {"session_id": session_id, "entity": entity.lower(), "relation": relation.lower()}
    )
    return r.deleted_count > 0


async def clear_graph(session_id: str) -> int:
    if _db is None:
        return 0
    r = await _db["memory_graph"].delete_many({"session_id": session_id})
    return r.deleted_count


async def extract_and_store(session_id: str, text: str, llm) -> list[dict]:
    """Use an LLM to extract facts from text and store them in the graph."""
    prompt = (
        "Extract factual triples from the following text. "
        "Output ONLY a JSON array like: "
        '[{"entity":"X","relation":"Y","value":"Z","confidence":0.9},...]\n\n'
        f"Text:\n{text[:2000]}"
    )
    try:
        raw = await llm.call(
            model="claude-haiku",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=512,
            temperature=0.1,
        )
        import json, re
        m = re.search(r"\[.*\]", raw, re.DOTALL)
        if not m:
            return []
        triples = json.loads(m.group(0))
        stored = []
        for t in triples[:20]:
            if all(k in t for k in ("entity", "relation", "value")):
                fact = await upsert_fact(
                    session_id, t["entity"], t["relation"], t["value"],
                    float(t.get("confidence", 0.8)),
                )
                stored.append(fact)
        return stored
    except Exception as exc:
        logger.debug("extract_and_store failed: %s", exc)
        return []
