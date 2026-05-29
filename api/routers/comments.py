"""Session message comments — feature #7."""
from fastapi import APIRouter, HTTPException

import api.db as _db
from api.models import CommentRequest
from api.validators import validate_session_id

router = APIRouter(prefix="/sessions", tags=["Comments"])


@router.get("/{session_id}/comments")
async def list_session_comments(session_id: str):
    validate_session_id(session_id)
    return {"comments": await _db.comments_db.list_all_for_session(session_id)}


@router.get("/{session_id}/messages/{message_idx}/comments")
async def list_message_comments(session_id: str, message_idx: int):
    validate_session_id(session_id)
    return {"comments": await _db.comments_db.list_comments(session_id, message_idx)}


@router.post("/{session_id}/messages/{message_idx}/comments", status_code=201)
async def add_comment(session_id: str, message_idx: int, req: CommentRequest):
    validate_session_id(session_id)
    comment_id = await _db.comments_db.add_comment(
        session_id=session_id,
        message_idx=message_idx,
        author=req.author,
        text=req.text,
    )
    return {"comment_id": comment_id, "status": "created"}


@router.delete("/comments/{comment_id}")
async def delete_comment(comment_id: str):
    deleted = await _db.comments_db.delete_comment(comment_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Comment not found")
    return {"comment_id": comment_id, "status": "deleted"}
