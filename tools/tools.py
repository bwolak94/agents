"""
Tools for agents:
- WebSearch  (SearXNG -> Brave -> DuckDuckGo fallback chain)
- CodeExecutor (Python subprocess sandbox with resource limits)
- FileReader / FileWriter
- Shell (allowlist-protected, exec not shell)
- MemoryRead / MemoryWrite (persistent agent memory)
- AgentCall (delegate to a specialist agent)
"""
import asyncio
import hashlib
import json
import shlex
import subprocess
import tempfile
import os
import sys
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING
import httpx

# ── Tool result cache ─────────────────────────────────────────────────────────
_TOOL_CACHE_TTL   = int(os.getenv("TOOL_CACHE_TTL", "300"))   # 5 minutes
_TOOL_CACHE_MAX   = int(os.getenv("TOOL_CACHE_MAX", "500"))
# Cacheable tool names (read-only / idempotent operations only)
_CACHEABLE_TOOLS  = {"web_search", "file_read"}
_tool_result_cache: dict[str, tuple[str, float]] = {}  # key -> (result, expires_at)


def _cache_key(tool_name: str, args: str) -> str:
    raw = f"{tool_name}:{args}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _cache_get(tool_name: str, args: str) -> str | None:
    if tool_name not in _CACHEABLE_TOOLS:
        return None
    key = _cache_key(tool_name, args)
    entry = _tool_result_cache.get(key)
    if entry and time.time() < entry[1]:
        return entry[0]
    _tool_result_cache.pop(key, None)
    return None


def _cache_put(tool_name: str, args: str, result: str) -> None:
    if tool_name not in _CACHEABLE_TOOLS:
        return
    # Evict oldest entries if at capacity
    if len(_tool_result_cache) >= _TOOL_CACHE_MAX:
        oldest = min(_tool_result_cache, key=lambda k: _tool_result_cache[k][1])
        _tool_result_cache.pop(oldest, None)
    key = _cache_key(tool_name, args)
    _tool_result_cache[key] = (result, time.time() + _TOOL_CACHE_TTL)

if TYPE_CHECKING:
    pass

UPLOADS_DIR = Path(os.getenv("UPLOADS_DIR", "/tmp/agent_uploads"))
WORKSPACE_DIR = Path(os.getenv("AGENT_WORKSPACE", "/tmp/agent_workspace"))
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

# Allowed base paths for file reads
_ALLOWED_READ_PREFIXES = [
    str(UPLOADS_DIR),
    str(WORKSPACE_DIR),
    "/tmp",
]


# ─────────────────────────────────────────
# WEB SEARCH
# ─────────────────────────────────────────
class WebSearchTool:
    BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
    SEARXNG_URL = os.getenv("SEARXNG_URL", "http://searxng:8080/search")
    MAX_RESULTS = 5
    SNIPPET_LEN = 300

    def __init__(self):
        self.brave_api_key = os.getenv("BRAVE_API_KEY", "")

    async def run(self, query: str) -> str:
        q = query[:200].strip()
        if self.brave_api_key:
            return await self._brave_search(q)
        result = await self._searxng_search(q)
        if result and "No results" not in result and "error" not in result.lower():
            return result
        return await self._ddg_search(q)

    async def _brave_search(self, query: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    self.BRAVE_URL,
                    params={"q": query, "count": self.MAX_RESULTS},
                    headers={"X-Subscription-Token": self.brave_api_key, "Accept": "application/json"},
                )
                resp.raise_for_status()
                data = resp.json()
            results = [
                f"[{r.get('title', '')}]\n{r.get('description', '')}\nURL: {r.get('url', '')}"
                for r in data.get("web", {}).get("results", [])[:self.MAX_RESULTS]
            ]
            return "\n\n".join(results) if results else "No results found."
        except Exception:
            return await self._ddg_search(query)

    async def _searxng_search(self, query: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    self.SEARXNG_URL,
                    params={"q": query, "format": "json", "language": "en-US"},
                )
                resp.raise_for_status()
                data = resp.json()
            results = [
                f"[{r.get('title', '')}]\n{r.get('content', '')[:self.SNIPPET_LEN]}\nURL: {r.get('url', '')}"
                for r in data.get("results", [])[:self.MAX_RESULTS]
            ]
            return "\n\n".join(results) if results else "No results from SearXNG."
        except Exception as e:
            return f"SearXNG error: {e}"

    async def _ddg_search(self, query: str) -> str:
        try:
            from duckduckgo_search import DDGS
            loop = asyncio.get_event_loop()

            def _search():
                with DDGS() as ddgs:
                    return list(ddgs.text(query, max_results=self.MAX_RESULTS))

            hits = await loop.run_in_executor(None, _search)
            results = [
                f"[{r.get('title', '')}]\n{r.get('body', '')[:self.SNIPPET_LEN]}\nURL: {r.get('href', '')}"
                for r in hits
            ]
            return "\n\n".join(results) if results else f"No results found for: '{query}'."
        except ImportError:
            return "Error: duckduckgo-search library is not installed."
        except Exception as e:
            return f"DDG search error: {e}"


# ─────────────────────────────────────────
# CODE EXECUTOR (sandboxed subprocess with resource limits)
# ─────────────────────────────────────────
class CodeExecutorTool:
    TIMEOUT = int(os.getenv("CODE_EXEC_TIMEOUT", "30"))

    async def run(self, code_or_message: str) -> str:
        code_match = re.search(r"```(?:python)?\n(.*?)```", code_or_message, re.DOTALL)
        if code_match:
            code = code_match.group(1)
        elif any(kw in code_or_message for kw in ["def ", "import ", "print(", "for ", "class "]):
            code = code_or_message
        else:
            return "No code found to execute."
        return await self._execute(code)

    async def _execute(self, code: str) -> str:
        # Use an isolated temp directory per execution
        with tempfile.TemporaryDirectory(prefix="agent_exec_", dir=str(WORKSPACE_DIR), ignore_cleanup_errors=True) as exec_dir:
            tmp_path = Path(exec_dir) / "script.py"
            tmp_path.write_text(code)

            # Sanitized environment — strip credentials, keep only essentials
            safe_env = {
                "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
                "PYTHONPATH": "",
                "HOME": exec_dir,
                "TMPDIR": exec_dir,
            }

            # #19 — wrap execution with ulimit to cap CPU time and address space
            # ulimit -t (CPU seconds), ulimit -v (virtual memory KB), ulimit -f (file size KB)
            ulimit_prefix = []
            if sys.platform != "win32":
                ulimit_prefix = [
                    "bash", "-c",
                    f"ulimit -t {self.TIMEOUT} -v 524288 -f 102400 2>/dev/null; "
                    f"exec {shlex.quote(sys.executable)} {shlex.quote(str(tmp_path))}",
                ]

            try:
                if ulimit_prefix:
                    proc = await asyncio.create_subprocess_exec(
                        *ulimit_prefix,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        cwd=exec_dir,
                        env=safe_env,
                    )
                else:
                    proc = await asyncio.create_subprocess_exec(
                        sys.executable, str(tmp_path),
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        cwd=exec_dir,
                        env=safe_env,
                    )
                try:
                    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.TIMEOUT)
                except asyncio.TimeoutError:
                    proc.kill()
                    return f"TIMEOUT: Code ran for longer than {self.TIMEOUT}s"

                output = []
                if stdout:
                    output.append(f"OUTPUT:\n{stdout.decode()[:5000]}")
                if stderr:
                    output.append(f"STDERR:\n{stderr.decode()[:2000]}")
                if proc.returncode != 0:
                    output.append(f"Exit code: {proc.returncode}")
                return "\n".join(output) if output else "Code executed with no output."
            except Exception as e:
                return f"Execution error: {e}"


# ─────────────────────────────────────────
# FILE READER  (path traversal protection)
# ─────────────────────────────────────────
class FileReaderTool:
    MAX_SIZE = 100_000  # ~100KB

    def _is_allowed(self, path: Path) -> bool:
        resolved = str(path.resolve())
        return any(resolved.startswith(prefix) for prefix in _ALLOWED_READ_PREFIXES)

    async def run(self, message: str) -> str:
        # Support upload IDs (upload::<id>)
        upload_match = re.search(r"upload::([a-f0-9\-]+)", message)
        if upload_match:
            upload_id = upload_match.group(1)
            candidates = list(UPLOADS_DIR.glob(f"**/{upload_id}*"))
            if candidates:
                file_path = candidates[0]
                return await self._read_file(file_path)
            return f"Upload not found: {upload_id}"

        path_match = re.search(r'["\']?(/[\w/.\-_]+\.\w+)["\']?', message)
        if not path_match:
            path_match = re.search(r'["\']?([\w/.\-_]+\.\w+)["\']?', message)
        if not path_match:
            return "No file path found in the message."

        return await self._read_file(Path(path_match.group(1)))

    async def _read_file(self, file_path: Path) -> str:
        if not self._is_allowed(file_path):
            return f"Access denied: {file_path} is outside allowed directories."
        if not file_path.exists():
            return f"File not found: {file_path}"
        size = file_path.stat().st_size
        if size > self.MAX_SIZE:
            return f"File too large ({size} bytes). Max: {self.MAX_SIZE} bytes."
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            return f"FILE: {file_path}\nSIZE: {size} bytes\n\nCONTENT:\n{content}"
        except Exception as e:
            return f"File read error: {e}"


# ─────────────────────────────────────────
# FILE WRITER  (restricted to workspace)
# ─────────────────────────────────────────
class FileWriterTool:
    async def run(self, message: str) -> str:
        try:
            data = json.loads(message)
            return await self.write(data["path"], data["content"])
        except (json.JSONDecodeError, KeyError):
            return "FileWriter: Provide JSON with 'path' and 'content' keys."

    async def write(self, path: str, content: str) -> str:
        try:
            p = (WORKSPACE_DIR / path).resolve()
            # Ensure write stays inside workspace
            if not str(p).startswith(str(WORKSPACE_DIR.resolve())):
                return "Access denied: writes are restricted to the workspace directory."
            # Save previous version and compute diff
            diff_output = ""
            try:
                from db.file_versions import save_version, compute_diff, get_previous
                prev = await get_previous(str(p))
                if prev is not None:
                    diff_output = "\n\nDIFF:\n" + compute_diff(prev, content, path)
                await save_version(str(p), content if p.exists() else "")
            except Exception:
                pass
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return f"Saved: {p} ({len(content)} characters){diff_output}"
        except Exception as e:
            return f"Write error: {e}"


# ─────────────────────────────────────────
# SHELL TOOL  (allowlist-protected, exec not shell)
# ─────────────────────────────────────────
class ShellTool:
    TIMEOUT = int(os.getenv("SHELL_TIMEOUT", "30"))
    # Allowlist: only commands starting with these prefixes are permitted
    ALLOWED_PREFIXES = (
        "ls", "cat", "echo", "grep", "find", "pwd", "wc", "head", "tail",
        "date", "env", "which", "python", "pip", "git",
        "sort", "uniq", "cut", "awk", "sed", "tr", "xargs", "curl", "wget", "jq",
    )

    async def run(self, message: str) -> str:
        match = re.search(r"```(?:bash|sh|shell)?\n?(.*?)```", message, re.DOTALL)
        if match:
            command = match.group(1).strip()
        else:
            inline = re.search(r"`([^`\n]+)`", message)
            if inline:
                command = inline.group(1).strip()
            else:
                return "ShellTool: No command found. Use backticks: `ls -la`"
        return await self._run_command(command)

    async def _run_command(self, command: str) -> str:
        cmd_lower = command.strip().lower()
        if not any(cmd_lower.startswith(prefix) for prefix in self.ALLOWED_PREFIXES):
            return f"BLOCKED: '{command}' is not in the allowed command list."

        # #18 — use shlex.split + create_subprocess_exec to prevent shell injection
        try:
            args = shlex.split(command)
        except ValueError as e:
            return f"ShellTool: Invalid command syntax: {e}"

        if not args:
            return "ShellTool: Empty command."

        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(WORKSPACE_DIR),
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.TIMEOUT)
            result = ""
            if stdout:
                result += stdout.decode()[:5000]
            if stderr:
                result += f"\nSTDERR: {stderr.decode()[:2000]}"
            return result or f"Command executed (exit code: {proc.returncode})"
        except asyncio.TimeoutError:
            return f"TIMEOUT after {self.TIMEOUT}s"
        except FileNotFoundError:
            return f"Command not found: {args[0]}"
        except Exception as e:
            return f"Error: {e}"


# ─────────────────────────────────────────
# MEMORY READ TOOL
# ─────────────────────────────────────────
class MemoryReadTool:
    """Read the agent's persistent memory about this user/session."""

    def __init__(self, session_id: str = "", agent_type: str = ""):
        self.session_id = session_id
        self.agent_type = agent_type

    async def run(self, _: str = "") -> str:
        from db.memory import memory_read
        memory = await memory_read(self.session_id, self.agent_type)
        return memory if memory else "No memory stored yet."


# ─────────────────────────────────────────
# MEMORY WRITE TOOL
# ─────────────────────────────────────────
class MemoryWriteTool:
    """Append a fact to the agent's persistent memory."""

    def __init__(self, session_id: str = "", agent_type: str = ""):
        self.session_id = session_id
        self.agent_type = agent_type

    async def run(self, fact: str) -> str:
        from db.memory import memory_append
        updated = await memory_append(self.session_id, self.agent_type, fact.strip())
        return f"Memory updated. Total: {len(updated)} chars."


# ─────────────────────────────────────────
# AGENT CALL TOOL
# ─────────────────────────────────────────
class AgentCallTool:
    """Delegate a sub-task to a specialist agent. Format: 'agent_name|task description'"""

    def __init__(self, parent_orchestrator=None):
        self._parent = parent_orchestrator

    async def run(self, message: str) -> str:
        if self._parent is None:
            return "AgentCallTool: No parent orchestrator available."
        parts = message.split("|", 1)
        if len(parts) != 2:
            return "AgentCallTool: Use format 'agent_name|task description'"
        agent_name, task = parts[0].strip(), parts[1].strip()
        try:
            result = await self._parent._run_agent(
                agent_name=agent_name,
                message=task,
                session_id=self._parent._current_session_id,
            )
            return f"[{agent_name} result]\n{result}"
        except Exception as e:
            return f"AgentCallTool error: {e}"


# ─────────────────────────────────────────
# TOOLS MANAGER
# ─────────────────────────────────────────
class ToolsManager:
    def __init__(self):
        self._tools: dict = {
            "web_search": WebSearchTool(),
            "code_exec": CodeExecutorTool(),
            "file_read": FileReaderTool(),
            "file_write": FileWriterTool(),
            "shell": ShellTool(),
            # memory and agent_call are registered per-request (they need session context)
        }

    def get(self, name: str):
        return self._tools.get(name)

    async def run_cached(self, name: str, args: str) -> str | None:
        """Run a tool with cross-request result caching for idempotent tools.

        Returns cached result string if available; None if cache miss (caller should invoke tool).
        """
        cached = _cache_get(name, args)
        if cached is not None:
            return cached
        tool = self._tools.get(name)
        if tool is None:
            return None
        result = await tool.run(args)
        _cache_put(name, args, str(result))
        return str(result)

    def register(self, name: str, tool) -> None:
        self._tools[name] = tool

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())

    def configure_session_tools(
        self,
        session_id: str,
        agent_type: str,
        parent_orchestrator=None,
    ) -> None:
        """Set up tools that need session context (memory, agent_call)."""
        self._tools["memory_read"] = MemoryReadTool(session_id, agent_type)
        self._tools["memory_write"] = MemoryWriteTool(session_id, agent_type)
        if parent_orchestrator is not None:
            self._tools["agent_call"] = AgentCallTool(parent_orchestrator)

    def register_webhook(self, name: str, url: str, method: str = "POST") -> None:
        """Dynamically register a webhook tool."""
        self._tools[name] = WebhookTool(url, method)


# ─────────────────────────────────────────
# WEBHOOK TOOL
# ─────────────────────────────────────────
class WebhookTool:
    """Call an HTTP webhook with the provided JSON payload."""

    def __init__(self, url: str, method: str = "POST"):
        self.url = url
        self.method = method.upper()

    async def run(self, message: str) -> str:
        try:
            payload = json.loads(message) if message.strip().startswith("{") else {"input": message}
        except json.JSONDecodeError:
            payload = {"input": message}
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                if self.method == "GET":
                    resp = await client.get(self.url, params=payload)
                else:
                    resp = await client.post(self.url, json=payload)
                resp.raise_for_status()
                try:
                    return json.dumps(resp.json(), indent=2)
                except Exception:
                    return resp.text[:2000]
        except Exception as e:
            return f"Webhook error: {e}"
