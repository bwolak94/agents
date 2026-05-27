"""
RAG (Retrieval-Augmented Generation) knowledge base.
Stores chunked text documents with MongoDB text search.
"""
import hashlib
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorDatabase

_db: AsyncIOMotorDatabase | None = None


def set_db(db: AsyncIOMotorDatabase) -> None:
    global _db
    _db = db


async def ensure_indexes() -> None:
    if _db is None:
        return
    await _db["knowledge"].create_index([("session_id", 1), ("doc_id", 1)])
    await _db["knowledge"].create_index([("content", "text"), ("title", "text")])


async def add_document(session_id: str, title: str, content: str, chunk_size: int = 500) -> list[str]:
    """Split content into chunks and store them. Returns list of chunk IDs."""
    if _db is None:
        return []
    chunks = _split_chunks(content, chunk_size)
    now = datetime.now(timezone.utc).isoformat()
    doc_id = hashlib.sha256(f"{session_id}{title}{now}".encode()).hexdigest()[:16]
    docs = []
    for i, chunk in enumerate(chunks):
        chunk_id = f"{doc_id}_{i}"
        docs.append({
            "chunk_id": chunk_id,
            "doc_id": doc_id,
            "session_id": session_id,
            "title": title,
            "content": chunk,
            "chunk_index": i,
            "total_chunks": len(chunks),
            "created_at": now,
        })
    if docs:
        await _db["knowledge"].insert_many(docs)
    return [d["chunk_id"] for d in docs]


async def search(session_id: str, query: str, limit: int = 5) -> list[dict]:
    """Full-text search over knowledge base for a session."""
    if _db is None:
        return []
    cursor = _db["knowledge"].find(
        {"session_id": session_id, "$text": {"$search": query}},
        {"_id": 0, "chunk_id": 1, "doc_id": 1, "title": 1, "content": 1, "chunk_index": 1, "score": {"$meta": "textScore"}},
    ).sort([("score", {"$meta": "textScore"})]).limit(limit)
    return await cursor.to_list(length=limit)


async def list_documents(session_id: str) -> list[dict]:
    """Return distinct documents (not chunks) for a session."""
    if _db is None:
        return []
    pipeline = [
        {"$match": {"session_id": session_id}},
        {"$group": {
            "_id": "$doc_id",
            "doc_id": {"$first": "$doc_id"},
            "title": {"$first": "$title"},
            "total_chunks": {"$first": "$total_chunks"},
            "created_at": {"$first": "$created_at"},
        }},
        {"$sort": {"created_at": -1}},
        {"$project": {"_id": 0}},
    ]
    cursor = _db["knowledge"].aggregate(pipeline)
    return await cursor.to_list(length=200)


async def delete_document(session_id: str, doc_id: str) -> int:
    """Delete all chunks for a document. Returns deleted count."""
    if _db is None:
        return 0
    result = await _db["knowledge"].delete_many({"session_id": session_id, "doc_id": doc_id})
    return result.deleted_count


def _split_chunks(text: str, chunk_size: int) -> list[str]:
    """Split text into overlapping chunks by word count."""
    words = text.split()
    if not words:
        return []
    overlap = chunk_size // 5
    chunks = []
    start = 0
    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunks.append(" ".join(words[start:end]))
        if end >= len(words):
            break
        start += chunk_size - overlap
    return chunks
