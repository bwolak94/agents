"""
LangChain Document Loaders — load documents from PDF, web, GitHub, CSV, plain text.
Falls back gracefully when optional dependencies are not installed.
"""
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class DocumentChunk:
    def __init__(self, content: str, metadata: dict | None = None) -> None:
        self.content = content
        self.metadata = metadata or {}

    def __repr__(self) -> str:
        return f"DocumentChunk(len={len(self.content)}, meta={self.metadata})"


# ─── PDF Loader ───────────────────────────────────────────────────────────────

async def load_pdf(path: str | Path, chunk_size: int = 2000) -> list[DocumentChunk]:
    """Load a PDF file and split into chunks."""
    try:
        import pypdf
        reader = pypdf.PdfReader(str(path))
        chunks: list[DocumentChunk] = []
        for page_num, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            if not text.strip():
                continue
            # Split into chunks of ~chunk_size chars
            for i in range(0, len(text), chunk_size):
                chunk = text[i:i + chunk_size]
                if chunk.strip():
                    chunks.append(DocumentChunk(
                        content=chunk,
                        metadata={"source": str(path), "page": page_num + 1, "type": "pdf"},
                    ))
        return chunks
    except ImportError:
        logger.warning("pypdf not installed — pip install pypdf")
        return []
    except Exception as exc:
        logger.error("PDF load failed: %s", exc)
        return []


# ─── Web Loader ───────────────────────────────────────────────────────────────

async def load_url(url: str, chunk_size: int = 2000) -> list[DocumentChunk]:
    """Fetch and parse a web page, returning text chunks."""
    try:
        import httpx
        from bs4 import BeautifulSoup

        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "AgentSystem/2.0"})
            resp.raise_for_status()
            html = resp.text

        soup = BeautifulSoup(html, "html.parser")
        # Remove boilerplate
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()

        text = soup.get_text(separator="\n", strip=True)
        chunks: list[DocumentChunk] = []
        for i in range(0, len(text), chunk_size):
            chunk = text[i:i + chunk_size].strip()
            if chunk:
                chunks.append(DocumentChunk(
                    content=chunk,
                    metadata={"source": url, "type": "web"},
                ))
        return chunks

    except ImportError as exc:
        logger.warning("Missing dependency for web loader: %s", exc)
        return []
    except Exception as exc:
        logger.error("Web load failed for %s: %s", url, exc)
        return []


# ─── GitHub Loader ────────────────────────────────────────────────────────────

async def load_github_repo(repo: str, branch: str = "main", file_pattern: str = "*.py",
                             max_files: int = 50) -> list[DocumentChunk]:
    """
    Load files from a GitHub repository via the GitHub API.
    repo format: "owner/repo-name"
    """
    import fnmatch
    try:
        import httpx

        api_url = f"https://api.github.com/repos/{repo}/git/trees/{branch}?recursive=1"
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(api_url)
            if resp.status_code == 404:
                logger.warning("GitHub repo not found: %s@%s", repo, branch)
                return []
            resp.raise_for_status()
            tree = resp.json().get("tree", [])

        chunks: list[DocumentChunk] = []
        count = 0
        for item in tree:
            if item["type"] != "blob":
                continue
            file_path = item["path"]
            if not fnmatch.fnmatch(file_path, file_pattern):
                continue
            if count >= max_files:
                break

            raw_url = f"https://raw.githubusercontent.com/{repo}/{branch}/{file_path}"
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    r = await client.get(raw_url)
                    content = r.text
                if content.strip():
                    chunks.append(DocumentChunk(
                        content=content[:5000],  # cap per file
                        metadata={"source": raw_url, "repo": repo, "path": file_path, "type": "github"},
                    ))
                    count += 1
            except Exception:
                continue

        return chunks

    except ImportError:
        logger.warning("httpx not installed")
        return []
    except Exception as exc:
        logger.error("GitHub load failed: %s", exc)
        return []


# ─── CSV Loader ───────────────────────────────────────────────────────────────

def load_csv(path: str | Path, max_rows: int = 500) -> list[DocumentChunk]:
    """Load a CSV file, returning each row as a document chunk."""
    import csv
    chunks: list[DocumentChunk] = []
    try:
        with open(path, newline="", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader):
                if i >= max_rows:
                    break
                content = " | ".join(f"{k}: {v}" for k, v in row.items())
                chunks.append(DocumentChunk(
                    content=content,
                    metadata={"source": str(path), "row": i, "type": "csv"},
                ))
    except Exception as exc:
        logger.error("CSV load failed: %s", exc)
    return chunks


# ─── Plain text / code Loader ─────────────────────────────────────────────────

def load_text(path: str | Path, chunk_size: int = 2000) -> list[DocumentChunk]:
    """Load any text or source code file."""
    try:
        content = Path(path).read_text(errors="replace")
        chunks: list[DocumentChunk] = []
        for i in range(0, len(content), chunk_size):
            chunk = content[i:i + chunk_size]
            if chunk.strip():
                chunks.append(DocumentChunk(
                    content=chunk,
                    metadata={"source": str(path), "type": "text"},
                ))
        return chunks
    except Exception as exc:
        logger.error("Text load failed: %s", exc)
        return []


# ─── Unified loader ───────────────────────────────────────────────────────────

async def load_document(source: str, **kwargs) -> list[DocumentChunk]:
    """
    Auto-detect source type and load document.
    source can be:
      - http(s):// URL
      - github://owner/repo[@branch][?file_pattern]
      - local file path (.pdf, .csv, or text)
    """
    if source.startswith("http://") or source.startswith("https://"):
        return await load_url(source, **kwargs)

    if source.startswith("github://"):
        # github://owner/repo@branch?pattern=*.py
        rest = source[len("github://"):]
        import urllib.parse
        parsed = urllib.parse.urlparse("http://" + rest)
        repo = parsed.netloc + parsed.path.split("?")[0]
        branch = "main"
        if "@" in repo:
            repo, branch = repo.rsplit("@", 1)
        file_pattern = urllib.parse.parse_qs(parsed.query).get("pattern", ["*.py"])[0]
        return await load_github_repo(repo, branch, file_pattern, **kwargs)

    path = Path(source)
    if not path.exists():
        logger.warning("File not found: %s", source)
        return []

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return await load_pdf(path, **kwargs)
    elif suffix == ".csv":
        return load_csv(path, **kwargs)
    else:
        return load_text(path, **kwargs)
