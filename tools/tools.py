"""
Tools for agents:
- WebSearch (SearXNG/Brave/DuckDuckGo)
- CodeExecutor (Python sandbox)
- FileReader / FileWriter
- Shell (use with caution!)
"""
import asyncio
import subprocess
import tempfile
import os
import sys
from pathlib import Path
from typing import Optional
import httpx


# ─────────────────────────────────────────
# WEB SEARCH
# Brave Search API (if BRAVE_API_KEY is set) → SearXNG fallback → DuckDuckGo fallback
# ─────────────────────────────────────────
class WebSearchTool:
    BRAVE_URL   = "https://api.search.brave.com/res/v1/web/search"
    SEARXNG_URL = os.getenv("SEARXNG_URL", "http://searxng:8080/search")

    def __init__(self):
        self.brave_api_key = os.getenv("BRAVE_API_KEY", "")

    async def run(self, query: str) -> str:
        search_query = query[:200].strip()
        if self.brave_api_key:
            return await self._brave_search(search_query)
        # Try SearXNG (self-hosted), fall back to DDG
        result = await self._searxng_search(search_query)
        if result and "No results" not in result and "Error" not in result:
            return result
        return await self._ddg_search(search_query)

    async def _brave_search(self, query: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    self.BRAVE_URL,
                    params={"q": query, "count": 5},
                    headers={
                        "X-Subscription-Token": self.brave_api_key,
                        "Accept": "application/json",
                    },
                )
                resp.raise_for_status()
                data = resp.json()

            results = []
            for r in data.get("web", {}).get("results", [])[:5]:
                results.append(
                    f"[{r.get('title', '')}]\n{r.get('description', '')}\nURL: {r.get('url', '')}"
                )
            return "\n\n".join(results) if results else "No results found."
        except Exception:
            return await self._ddg_search(query)

    async def _searxng_search(self, query: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    self.SEARXNG_URL,
                    params={"q": query, "format": "json", "language": "pl-PL"},
                )
                resp.raise_for_status()
                data = resp.json()

            results = []
            for r in data.get("results", [])[:5]:
                title = r.get("title", "")
                content = r.get("content", "")[:300]
                url = r.get("url", "")
                results.append(f"[{title}]\n{content}\nURL: {url}")

            return "\n\n".join(results) if results else "No results from SearXNG."
        except Exception as e:
            return f"SearXNG error: {e}"

    async def _ddg_search(self, query: str) -> str:
        try:
            from duckduckgo_search import DDGS
            results = []
            # Run synchronous DDG in an executor to avoid blocking the event loop
            loop = asyncio.get_event_loop()

            def _search():
                with DDGS() as ddgs:
                    return list(ddgs.text(query, max_results=5))

            hits = await loop.run_in_executor(None, _search)
            for r in hits:
                title = r.get("title", "")
                body = r.get("body", "")[:300]
                href = r.get("href", "")
                results.append(f"[{title}]\n{body}\nURL: {href}")

            return "\n\n".join(results) if results else f"No results found for: '{query}'."
        except ImportError:
            return "Error: duckduckgo-search library is not installed."
        except Exception as e:
            return f"DDG search error: {e}"


# ─────────────────────────────────────────
# CODE EXECUTOR (Python sandbox)
# ─────────────────────────────────────────
class CodeExecutorTool:
    """Safe Python code execution in an isolated subprocess."""

    TIMEOUT = 30  # sekund

    async def run(self, code_or_message: str) -> str:
        """
        Extract code from a message and execute it.
        Looks for ```python ... ``` blocks or treats the whole message as code.
        """
        import re
        # Szukaj bloku kodu
        code_match = re.search(r"```(?:python)?\n(.*?)```", code_or_message, re.DOTALL)
        if code_match:
            code = code_match.group(1)
        else:
            # Treat whole message as code if it looks like code
            if any(kw in code_or_message for kw in ["def ", "import ", "print(", "for ", "class "]):
                code = code_or_message
            else:
                return "Nie znaleziono kodu do wykonania."

        return await self._execute(code)

    async def _execute(self, code: str) -> str:
        """Execute code in a separate subprocess."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            tmp_path = f.name

        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, tmp_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=self.TIMEOUT
                )
            except asyncio.TimeoutError:
                proc.kill()
                return f"TIMEOUT: Code ran for longer than {self.TIMEOUT}s"

            output = []
            if stdout:
                output.append(f"OUTPUT:\n{stdout.decode()}")
            if stderr:
                output.append(f"STDERR:\n{stderr.decode()}")
            if proc.returncode != 0:
                output.append(f"Exit code: {proc.returncode}")

            return "\n".join(output) if output else "Code executed with no output."

        finally:
            os.unlink(tmp_path)


# ─────────────────────────────────────────
# FILE READER
# ─────────────────────────────────────────
class FileReaderTool:
    MAX_SIZE = 100_000  # ~100KB

    async def run(self, message: str) -> str:
        """Extract file path from message and read the file."""
        import re
        # Extract file path from message
        path_match = re.search(r'["\']?(/[\w/.\-_]+\.\w+)["\']?', message)
        if not path_match:
            path_match = re.search(r'["\']?([\w/.\-_]+\.\w+)["\']?', message)

        if not path_match:
            return "No file path found in the message."

        file_path = Path(path_match.group(1))

        if not file_path.exists():
            return f"Plik nie istnieje: {file_path}"

        size = file_path.stat().st_size
        if size > self.MAX_SIZE:
            return f"File too large ({size} bytes). Max: {self.MAX_SIZE} bytes."

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            return f"FILE: {file_path}\nSIZE: {size} bytes\n\nCONTENT:\n{content}"
        except Exception as e:
            return f"File read error: {e}"


# ─────────────────────────────────────────
# FILE WRITER
# ─────────────────────────────────────────
class FileWriterTool:
    async def run(self, message: str) -> str:
        """Write a file - requires explicit path and content."""
        return "FileWriter: Requires a direct call with path and content."

    async def write(self, path: str, content: str) -> str:
        try:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return f"Saved: {path} ({len(content)} characters)"
        except Exception as e:
            return f"Write error: {e}"


# ─────────────────────────────────────────
# SHELL TOOL
# ─────────────────────────────────────────
class ShellTool:
    """Executes shell commands. WARNING: use with caution!"""
    TIMEOUT = 30
    BLOCKED = ["rm -rf", "mkfs", "dd if=", ":(){", "sudo rm"]

    async def run(self, message: str) -> str:
        """Extract command from backtick or code block; refuse to execute raw text."""
        import re
        # Szukaj ```bash ... ``` lub ``` ... ```
        match = re.search(r"```(?:bash|sh|shell)?\n?(.*?)```", message, re.DOTALL)
        if match:
            command = match.group(1).strip()
        else:
            # Szukaj `komenda`
            inline = re.search(r"`([^`\n]+)`", message)
            if inline:
                command = inline.group(1).strip()
            else:
                return (
                    "ShellTool: No command found to execute.\n"
                    "Provide a command in backticks: `ls -la`\n"
                    "lub bloku kodu:\n```bash\necho hello\n```"
                )

        return await self._run_command(command)

    async def _run_command(self, command: str) -> str:
        for blocked in self.BLOCKED:
            if blocked in command:
                return f"BLOCKED: Command contains '{blocked}'"

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.TIMEOUT
            )
            result = ""
            if stdout:
                result += stdout.decode()
            if stderr:
                result += f"\nSTDERR: {stderr.decode()}"
            return result or f"Komenda wykonana (exit code: {proc.returncode})"
        except asyncio.TimeoutError:
            return f"TIMEOUT po {self.TIMEOUT}s"
        except Exception as e:
            return f"Error: {e}"


# ─────────────────────────────────────────
# TOOLS MANAGER
# ─────────────────────────────────────────
class ToolsManager:
    def __init__(self):
        self._tools = {
            "web_search": WebSearchTool(),
            "code_exec": CodeExecutorTool(),
            "file_read": FileReaderTool(),
            "file_write": FileWriterTool(),
            "shell": ShellTool(),
        }

    def get(self, name: str):
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())
