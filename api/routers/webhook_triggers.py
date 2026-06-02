"""Webhook triggers — CRUD + fire endpoint."""
import hashlib
import hmac
import logging

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

import api.db as _db
import api.state as _state
from api.validators import validate_session_id

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhook-triggers", tags=["Webhooks"])


class TriggerCreateRequest(BaseModel):
    session_id: str = "default"
    name: str = Field(..., min_length=1, max_length=100)
    event_type: str = Field(..., min_length=1, max_length=100)
    task_template: str = Field(..., min_length=1, max_length=2000)
    secret: str = ""


@router.get("")
async def list_triggers(session_id: str = "default"):
    validate_session_id(session_id)
    triggers = await _db.webhook_triggers_db.list_triggers(session_id)
    return {"triggers": triggers}


@router.post("", status_code=201)
async def create_trigger(req: TriggerCreateRequest):
    validate_session_id(req.session_id)
    trigger_id = await _db.webhook_triggers_db.create_trigger(
        session_id=req.session_id,
        name=req.name,
        event_type=req.event_type,
        task_template=req.task_template,
        secret=req.secret,
    )
    return {"trigger_id": trigger_id, "status": "created"}


@router.delete("/{trigger_id}")
async def delete_trigger(trigger_id: str):
    deleted = await _db.webhook_triggers_db.delete_trigger(trigger_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Trigger not found")
    return {"trigger_id": trigger_id, "status": "deleted"}


@router.post("/{trigger_id}/fire")
async def fire_trigger(
    trigger_id: str,
    request: Request,
    x_hub_signature_256: str = Header(default=""),
):
    """Fire a trigger. If the trigger has a secret, validates HMAC-SHA256 signature."""
    trigger = await _db.webhook_triggers_db.get_trigger(trigger_id)
    if not trigger:
        raise HTTPException(status_code=404, detail="Trigger not found")
    if not trigger.get("active"):
        raise HTTPException(status_code=409, detail="Trigger is inactive")

    # #22 HMAC signature validation
    secret = trigger.get("secret", "")
    if secret:
        body = await request.body()
        expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, x_hub_signature_256):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    session_id = trigger["session_id"]
    task_template = trigger["task_template"]

    await _db.webhook_triggers_db.record_fire(trigger_id)

    try:
        orch = await _state.get_session(session_id)
        response = await orch.process(message=task_template, stream=False, session_id=session_id)
    except Exception as exc:
        logger.exception("Trigger %s fire failed", trigger_id)
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "trigger_id": trigger_id,
        "session_id": session_id,
        "response": response,
        "status": "fired",
    }
