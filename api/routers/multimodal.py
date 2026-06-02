"""Multi-modal endpoints — audio (#7), image generation (#8), OCR (#9), chart (#10)."""
import base64
import io
import logging
import os
import re
import tempfile
import textwrap
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

import api.state as _state

logger = logging.getLogger(__name__)
router = APIRouter()

_ALLOWED_AUDIO_TYPES = {"audio/mpeg", "audio/wav", "audio/webm", "audio/ogg", "audio/mp4", "audio/x-m4a"}
_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}


# ── #7 Audio transcription ────────────────────────────────────────────────────

@router.post("/chat/audio")
async def chat_audio(
    file: UploadFile = File(..., description="Audio file (mp3, wav, webm, ogg, m4a)"),
    session_id: str = Form(default="default"),
    model: str = Form(default="claude"),
):
    """Transcribe audio then route to agent. Uses OpenAI Whisper API if available,
    falls back to returning an error with instructions."""
    content_type = file.content_type or ""
    if content_type not in _ALLOWED_AUDIO_TYPES:
        raise HTTPException(status_code=415, detail=f"Unsupported audio type: {content_type}")

    audio_bytes = await file.read()
    if len(audio_bytes) > 25 * 1024 * 1024:  # 25MB limit
        raise HTTPException(status_code=413, detail="Audio file too large (max 25MB)")

    # Transcribe using OpenAI Whisper API if key is set
    whisper_key = os.getenv("OPENAI_API_KEY", "")
    transcript = ""
    if whisper_key:
        try:
            import httpx
            with tempfile.NamedTemporaryFile(suffix=Path(file.filename or "audio.mp3").suffix, delete=False) as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name
            async with httpx.AsyncClient(timeout=60) as client:
                with open(tmp_path, "rb") as f:
                    resp = await client.post(
                        "https://api.openai.com/v1/audio/transcriptions",
                        headers={"Authorization": f"Bearer {whisper_key}"},
                        files={"file": (file.filename or "audio.mp3", f, content_type)},
                        data={"model": "whisper-1"},
                    )
                    resp.raise_for_status()
                    transcript = resp.json().get("text", "")
            Path(tmp_path).unlink(missing_ok=True)
        except Exception as exc:
            logger.warning("Whisper transcription failed: %s", exc)
            raise HTTPException(status_code=502, detail=f"Transcription failed: {exc}")
    else:
        # Try local faster-whisper
        try:
            from faster_whisper import WhisperModel  # type: ignore
            wm = WhisperModel("base", device="cpu", compute_type="int8")
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name
            segments, _ = wm.transcribe(tmp_path)
            transcript = " ".join(s.text for s in segments).strip()
            Path(tmp_path).unlink(missing_ok=True)
        except ImportError:
            raise HTTPException(
                status_code=501,
                detail="Audio transcription requires either OPENAI_API_KEY or `pip install faster-whisper`",
            )

    if not transcript:
        raise HTTPException(status_code=422, detail="Could not transcribe audio")

    # Route transcript to agent
    orch = await _state.get_session(session_id)
    response = await orch.process(message=transcript, session_id=session_id, preferred_model=model)
    return {"transcript": transcript, "response": response, "session_id": session_id}


# ── #8 Image generation ───────────────────────────────────────────────────────

@router.post("/generate/image")
async def generate_image(
    prompt: str = Form(...),
    size: str = Form(default="1024x1024"),
    quality: str = Form(default="standard"),
    session_id: str = Form(default="default"),
):
    """Generate an image via DALL-E 3. Requires OPENAI_API_KEY."""
    if size not in ("256x256", "512x512", "1024x1024", "1792x1024", "1024x1792"):
        raise HTTPException(status_code=422, detail="Invalid size")

    dalle_key = os.getenv("OPENAI_API_KEY", "")
    if not dalle_key:
        raise HTTPException(
            status_code=501,
            detail="Image generation requires OPENAI_API_KEY (DALL-E 3)",
        )
    try:
        import httpx
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://api.openai.com/v1/images/generations",
                headers={"Authorization": f"Bearer {dalle_key}", "Content-Type": "application/json"},
                json={"model": "dall-e-3", "prompt": prompt[:4000], "n": 1, "size": size, "quality": quality, "response_format": "b64_json"},
            )
            resp.raise_for_status()
            data = resp.json()["data"][0]
            image_b64 = data["b64_json"]
            revised_prompt = data.get("revised_prompt", prompt)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Image generation failed: {exc}")

    return {
        "image_b64": image_b64,
        "revised_prompt": revised_prompt,
        "size": size,
        "session_id": session_id,
    }


# ── #9 Document OCR ───────────────────────────────────────────────────────────

@router.post("/knowledge/ocr")
async def ocr_upload(
    file: UploadFile = File(..., description="PDF or image file for OCR"),
    session_id: str = Form(default="default"),
    title: str = Form(default=""),
    ingest: bool = Form(default=True, description="Also add extracted text to RAG knowledge base"),
):
    """Extract text from a PDF or image and optionally ingest into the knowledge base."""
    content_type = file.content_type or ""
    filename = file.filename or "upload"
    data = await file.read()
    if len(data) > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 50MB)")

    extracted_text = ""

    if "pdf" in content_type or filename.lower().endswith(".pdf"):
        try:
            from pdfminer.high_level import extract_text  # type: ignore
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(data)
                tmp_path = tmp.name
            extracted_text = extract_text(tmp_path)
            Path(tmp_path).unlink(missing_ok=True)
        except ImportError:
            # Fallback: read bytes as text if possible
            raise HTTPException(
                status_code=501,
                detail="PDF extraction requires `pip install pdfminer.six`",
            )
    elif content_type in _ALLOWED_IMAGE_TYPES or any(filename.lower().endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".tiff", ".bmp")):
        try:
            import pytesseract  # type: ignore
            from PIL import Image  # type: ignore
            img = Image.open(io.BytesIO(data))
            extracted_text = pytesseract.image_to_string(img)
        except ImportError:
            raise HTTPException(
                status_code=501,
                detail="Image OCR requires `pip install pytesseract pillow` + Tesseract binary",
            )
    else:
        raise HTTPException(status_code=415, detail="Unsupported file type for OCR")

    extracted_text = extracted_text.strip()
    if not extracted_text:
        raise HTTPException(status_code=422, detail="No text could be extracted")

    chunk_ids: list[str] = []
    if ingest:
        import api.db as _db
        doc_title = title or Path(filename).stem
        chunk_ids = await _db.rag_db.add_document(session_id, doc_title, extracted_text, chunk_size=1000)

    return {
        "filename": filename,
        "session_id": session_id,
        "characters_extracted": len(extracted_text),
        "chunk_ids": chunk_ids,
        "preview": extracted_text[:500],
    }


# ── #10 Chart generation ──────────────────────────────────────────────────────

@router.post("/generate/chart")
async def generate_chart(
    prompt: str = Form(..., description="Natural language description of the chart"),
    data: str = Form(default="", description="Optional CSV data to plot"),
    session_id: str = Form(default="default"),
):
    """Ask the LLM to write matplotlib code, execute it in a sandbox, return PNG."""
    system = textwrap.dedent("""
        You are a Python data visualization expert.
        Write ONLY executable Python code using matplotlib to create the requested chart.
        - Use `import matplotlib.pyplot as plt` and `import io, base64`
        - Save the chart: `buf = io.BytesIO(); plt.savefig(buf, format='png', bbox_inches='tight', dpi=100); buf.seek(0); print(base64.b64encode(buf.read()).decode())`
        - Do NOT use plt.show()
        - Do NOT include any explanation or markdown fences
    """).strip()

    data_hint = f"\n\nUse this CSV data:\n```\n{data[:2000]}\n```" if data.strip() else ""
    orch = await _state.get_session(session_id)
    code = await orch.llm.call(
        model="claude",
        messages=[{"role": "user", "content": prompt + data_hint}],
        system_prompt=system,
        max_tokens=1024,
        temperature=0.2,
    )

    # Strip markdown fences if LLM added them
    code = re.sub(r"^```python\s*", "", code.strip(), flags=re.MULTILINE)
    code = re.sub(r"```$", "", code.strip(), flags=re.MULTILINE).strip()

    # Execute in restricted sandbox
    try:
        import matplotlib  # type: ignore
        matplotlib.use("Agg")
        namespace: dict = {}
        exec(compile(code, "<chart>", "exec"), namespace)  # noqa: S102
        # Collect printed output (base64 PNG)
        import sys
        old_stdout = sys.stdout
        sys.stdout = cap = io.StringIO()
        try:
            exec(compile(code, "<chart>", "exec"), {})  # noqa: S102
        finally:
            sys.stdout = old_stdout
        image_b64 = cap.getvalue().strip()
    except ImportError:
        raise HTTPException(status_code=501, detail="Chart generation requires `pip install matplotlib`")
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Chart code execution failed: {exc}")

    if not image_b64:
        raise HTTPException(status_code=422, detail="Chart generation produced no output")

    return {"image_b64": image_b64, "code": code, "session_id": session_id}
