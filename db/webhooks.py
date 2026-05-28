"""#29 — Outbound webhook registry.

Agents can fire POSTs to registered URLs when they complete tasks.
Schema: {webhook_id, session_id, url, events, secret, active, created_at}
"""
import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)
_db = None


def set_db(db) -> None:
    global _db
    _db = db


async def ensure_indexes() -> None:
    if _db is None:
        return
    await _db["webhooks"].create_index("session_id")
    await _db["webhooks"].create_index("webhook_id", unique=True)


async def register(session_id: str, url: str, events: list[str], secret: str = "") -> str:
    """Register a webhook. Returns webhook_id."""
    if _db is None:
        return ""
    wid = hashlib.sha256(f"{session_id}{url}{datetime.now().isoformat()}".encode()).hexdigest()[:16]
    await _db["webhooks"].update_one(
        {"webhook_id": wid},
        {"$setOnInsert": {
            "webhook_id": wid,
            "session_id": session_id,
            "url": url,
            "events": events or ["agent_done"],
            "secret": secret,
            "active": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "delivery_count": 0,
            "last_delivered": None,
        }},
        upsert=True,
    )
    return wid


async def list_webhooks(session_id: str) -> list[dict]:
    if _db is None:
        return []
    cursor = _db["webhooks"].find({"session_id": session_id}, {"_id": 0})
    return await cursor.to_list(50)


async def delete_webhook(webhook_id: str) -> bool:
    if _db is None:
        return False
    r = await _db["webhooks"].delete_one({"webhook_id": webhook_id})
    return r.deleted_count > 0


async def fire(session_id: str, event: str, payload: dict) -> list[dict]:
    """Fire webhooks for a session+event combination. Returns delivery results."""
    if _db is None:
        return []
    cursor = _db["webhooks"].find(
        {"session_id": session_id, "active": True, "events": event},
        {"_id": 0},
    )
    webhooks = await cursor.to_list(20)
    results = []
    async with httpx.AsyncClient(timeout=10) as client:
        for wh in webhooks:
            body = json.dumps({"event": event, "session_id": session_id, **payload})
            headers = {"Content-Type": "application/json", "X-Webhook-Event": event}
            if wh.get("secret"):
                sig = hmac.new(wh["secret"].encode(), body.encode(), hashlib.sha256).hexdigest()
                headers["X-Webhook-Signature"] = f"sha256={sig}"
            try:
                resp = await client.post(wh["url"], content=body, headers=headers)
                status = resp.status_code
            except Exception as exc:
                logger.warning("Webhook delivery failed %s: %s", wh["url"], exc)
                status = 0
            await _db["webhooks"].update_one(
                {"webhook_id": wh["webhook_id"]},
                {"$inc": {"delivery_count": 1}, "$set": {"last_delivered": datetime.now(timezone.utc).isoformat()}},
            )
            results.append({"webhook_id": wh["webhook_id"], "url": wh["url"], "status": status})
    return results
