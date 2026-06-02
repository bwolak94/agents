"""Knowledge-base / RAG / upload endpoints."""
import hashlib
import os
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

import api.db as _db
from api.models import KnowledgeRequest, DocumentLoadRequest
from api.validators import validate_session_id

router = APIRouter()

UPLOADS_DIR = Path(os.getenv("UPLOADS_DIR", "/tmp/agent_uploads"))
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


# ── Knowledge base (RAG) ──────────────────────────────────────────────────────

@router.post("/knowledge")
async def add_knowledge(req: KnowledgeRequest):
    chunk_ids = await _db.rag_db.add_document(req.session_id, req.title, req.content)
    return {"chunks": len(chunk_ids), "status": "indexed"}


@router.get("/knowledge/{session_id}")
async def list_knowledge(session_id: str):
    validate_session_id(session_id)
    return {"documents": await _db.rag_db.list_documents(session_id)}


@router.get("/knowledge/{session_id}/search")
async def search_knowledge(session_id: str, q: str = Query(..., min_length=1)):
    validate_session_id(session_id)
    results = await _db.rag_db.search(session_id, q)
    return {"results": results}


@router.delete("/knowledge/{session_id}/{doc_id}")
async def delete_knowledge(session_id: str, doc_id: str):
    validate_session_id(session_id)
    deleted = await _db.rag_db.delete_document(session_id, doc_id)
    return {"deleted_chunks": deleted}


@router.post("/knowledge/load")
async def load_document_to_knowledge(req: DocumentLoadRequest):
    from tools.langchain_loaders import load_document
    chunks = await load_document(req.source, chunk_size=req.chunk_size)
    if not chunks:
        raise HTTPException(status_code=422, detail="No content loaded from source")
    title = req.title or req.source[:80]
    combined = "\n\n".join(c.content for c in chunks[:20])
    chunk_ids = await _db.rag_db.add_document(req.session_id, title, combined)
    return {
        "status": "loaded",
        "source": req.source,
        "chunks_loaded": len(chunks),
        "chunks_indexed": len(chunk_ids),
        "session_id": req.session_id,
    }


# ── File upload ───────────────────────────────────────────────────────────────

@router.post("/upload")
async def upload_file(file: UploadFile = File(...), session_id: str = "default"):
    validate_session_id(session_id)
    if file.size and file.size > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 10MB)")

    file_id = hashlib.sha256(
        f"{session_id}{file.filename}{uuid.uuid4()}".encode()
    ).hexdigest()[:16]
    session_dir = UPLOADS_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    suffix = Path(file.filename or "upload").suffix
    dest = session_dir / f"{file_id}{suffix}"

    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    return {
        "file_id": file_id,
        "filename": file.filename,
        "size": dest.stat().st_size,
        "reference": f"upload::{file_id}",
        "hint": f"Use this in your message: 'Analyse upload::{file_id}'",
    }


@router.get("/uploads/{session_id}")
async def list_uploads(session_id: str):
    validate_session_id(session_id)
    session_dir = UPLOADS_DIR / session_id
    if not session_dir.exists():
        return {"uploads": []}
    uploads = [
        {"filename": f.name, "size": f.stat().st_size, "reference": f"upload::{f.stem}"}
        for f in session_dir.iterdir() if f.is_file()
    ]
    return {"uploads": uploads}
