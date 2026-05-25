"""
Unit tests for tools/tools.py.

All external HTTP calls are mocked with unittest.mock so no real network
requests are made during the test run.
"""
import asyncio
import os
import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

from tools.tools import (
    WebSearchTool,
    CodeExecutorTool,
    FileReaderTool,
    FileWriterTool,
    ShellTool,
    ToolsManager,
)


# ─────────────────────────────────────────
# WebSearchTool
# ─────────────────────────────────────────

class TestWebSearchTool:
    # --- Brave Search ---

    @pytest.mark.asyncio
    async def test_run_uses_brave_when_api_key_is_set(self):
        tool = WebSearchTool()
        tool.brave_api_key = "fake-brave-key"

        brave_response = MagicMock()
        brave_response.raise_for_status = MagicMock()
        brave_response.json = MagicMock(return_value={
            "web": {
                "results": [
                    {"title": "Python docs", "description": "Official Python documentation", "url": "https://python.org"},
                ]
            }
        })

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=brave_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("tools.tools.httpx.AsyncClient", return_value=mock_client):
            result = await tool.run("python tutorials")

        assert "Python docs" in result
        assert "https://python.org" in result

    @pytest.mark.asyncio
    async def test_brave_returns_multiple_results_formatted(self):
        tool = WebSearchTool()
        tool.brave_api_key = "test-key"

        brave_response = MagicMock()
        brave_response.raise_for_status = MagicMock()
        brave_response.json = MagicMock(return_value={
            "web": {
                "results": [
                    {"title": "A", "description": "desc A", "url": "http://a.com"},
                    {"title": "B", "description": "desc B", "url": "http://b.com"},
                ]
            }
        })

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=brave_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("tools.tools.httpx.AsyncClient", return_value=mock_client):
            result = await tool.run("query")

        assert "A" in result
        assert "B" in result

    @pytest.mark.asyncio
    async def test_brave_no_results_returns_no_results_string(self):
        tool = WebSearchTool()
        tool.brave_api_key = "test-key"

        brave_response = MagicMock()
        brave_response.raise_for_status = MagicMock()
        brave_response.json = MagicMock(return_value={"web": {"results": []}})

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=brave_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("tools.tools.httpx.AsyncClient", return_value=mock_client):
            result = await tool.run("obscure query with no results")

        assert "No results" in result

    # --- SearXNG ---

    @pytest.mark.asyncio
    async def test_searxng_search_parses_results_correctly(self):
        tool = WebSearchTool()

        searxng_response = MagicMock()
        searxng_response.raise_for_status = MagicMock()
        searxng_response.json = MagicMock(return_value={
            "results": [
                {"title": "SearX result", "content": "Some content from searxng", "url": "https://searx.example.com"},
            ]
        })

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=searxng_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("tools.tools.httpx.AsyncClient", return_value=mock_client):
            result = await tool._searxng_search("test query")

        assert "SearX result" in result
        assert "Some content from searxng" in result
        assert "https://searx.example.com" in result

    @pytest.mark.asyncio
    async def test_searxng_search_returns_error_string_on_exception(self):
        tool = WebSearchTool()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("tools.tools.httpx.AsyncClient", return_value=mock_client):
            result = await tool._searxng_search("anything")

        assert "SearXNG error" in result or "Error" in result

    @pytest.mark.asyncio
    async def test_searxng_empty_results_returns_no_results_string(self):
        tool = WebSearchTool()

        searxng_response = MagicMock()
        searxng_response.raise_for_status = MagicMock()
        searxng_response.json = MagicMock(return_value={"results": []})

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=searxng_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("tools.tools.httpx.AsyncClient", return_value=mock_client):
            result = await tool._searxng_search("empty query")

        assert "No results" in result

    # --- DuckDuckGo ---

    @pytest.mark.asyncio
    async def test_ddg_search_handles_import_error_gracefully(self):
        """When duckduckgo_search is not installed, return an informative error."""
        tool = WebSearchTool()
        with patch.dict(sys.modules, {"duckduckgo_search": None}):
            result = await tool._ddg_search("test query")
        assert "not installed" in result.lower() or "Error" in result

    @pytest.mark.asyncio
    async def test_run_falls_back_to_ddg_when_no_brave_key_and_searxng_fails(self):
        tool = WebSearchTool()
        tool.brave_api_key = ""  # no brave

        # SearXNG fails
        with patch.object(tool, "_searxng_search", return_value="SearXNG error: timeout"), \
             patch.object(tool, "_ddg_search", new_callable=AsyncMock) as mock_ddg:
            mock_ddg.return_value = "DDG result"
            result = await tool.run("anything")

        assert result == "DDG result"


# ─────────────────────────────────────────
# CodeExecutorTool
# ─────────────────────────────────────────

class TestCodeExecutorTool:
    @pytest.mark.asyncio
    async def test_run_extracts_code_from_python_block_and_executes(self):
        tool = CodeExecutorTool()
        message = "Please run this:\n```python\nprint('hello')\n```"
        with patch.object(tool, "_execute", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = "OUTPUT:\nhello\n"
            result = await tool.run(message)
        mock_exec.assert_awaited_once()
        # The code extracted should be just the inner content
        extracted_code = mock_exec.call_args.args[0]
        assert "print('hello')" in extracted_code

    @pytest.mark.asyncio
    async def test_run_returns_no_code_found_for_plain_text(self):
        tool = CodeExecutorTool()
        result = await tool.run("This is just a plain text question with no code.")
        assert "Nie znaleziono" in result or "no code" in result.lower()

    @pytest.mark.asyncio
    async def test_run_treats_code_like_message_as_code_if_contains_keyword(self):
        tool = CodeExecutorTool()
        code = "import os\nprint(os.getcwd())"
        with patch.object(tool, "_execute", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = "OUTPUT:\n/some/path\n"
            result = await tool.run(code)
        mock_exec.assert_awaited_once_with(code)

    @pytest.mark.asyncio
    async def test_execute_handles_timeout(self):
        """_execute() must return a TIMEOUT message if the subprocess takes too long."""
        tool = CodeExecutorTool()
        code = "import time; time.sleep(999)"

        mock_proc = AsyncMock()
        mock_proc.kill = MagicMock()
        mock_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError)

        with patch("tools.tools.asyncio.create_subprocess_exec", return_value=mock_proc), \
             patch("tools.tools.asyncio.wait_for", side_effect=asyncio.TimeoutError):
            result = await tool._execute(code)

        assert "TIMEOUT" in result

    @pytest.mark.asyncio
    async def test_execute_returns_stdout_output(self):
        tool = CodeExecutorTool()
        code = "print('hi')"

        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"hi\n", b""))

        with patch("tools.tools.asyncio.create_subprocess_exec", return_value=mock_proc), \
             patch("tools.tools.asyncio.wait_for", new_callable=AsyncMock, return_value=(b"hi\n", b"")), \
             patch("tools.tools.os.unlink"):
            result = await tool._execute(code)

        assert "hi" in result or "OUTPUT" in result

    @pytest.mark.asyncio
    async def test_run_extracts_code_from_plain_code_block(self):
        """A ``` block without the python tag should also be extracted."""
        tool = CodeExecutorTool()
        message = "run:\n```\ndef foo():\n    return 1\n```"
        with patch.object(tool, "_execute", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = "OUTPUT:\n1\n"
            result = await tool.run(message)
        mock_exec.assert_awaited_once()


# ─────────────────────────────────────────
# FileReaderTool
# ─────────────────────────────────────────

class TestFileReaderTool:
    @pytest.mark.asyncio
    async def test_run_returns_error_when_no_path_found(self):
        tool = FileReaderTool()
        result = await tool.run("Please analyse the data for me without any file mention.")
        assert "No file path found" in result

    @pytest.mark.asyncio
    async def test_run_returns_error_for_non_existent_file(self):
        tool = FileReaderTool()
        result = await tool.run("Read the file /nonexistent/path/to/missing_file.txt")
        assert "nie istnieje" in result or "does not exist" in result.lower() or "/nonexistent" in result

    @pytest.mark.asyncio
    async def test_run_returns_error_for_large_file(self, tmp_path):
        big_file = tmp_path / "big.txt"
        # Write more than MAX_SIZE bytes
        big_file.write_bytes(b"x" * (FileReaderTool.MAX_SIZE + 1))
        result = await FileReaderTool().run(f"read {big_file}")
        assert "too large" in result.lower() or "Max" in result

    @pytest.mark.asyncio
    async def test_run_reads_existing_file_correctly(self, tmp_path):
        test_file = tmp_path / "sample.txt"
        test_file.write_text("Hello, world!")
        tool = FileReaderTool()
        result = await tool.run(f"Please read the file {test_file}")
        assert "Hello, world!" in result

    @pytest.mark.asyncio
    async def test_run_includes_file_path_and_size_in_output(self, tmp_path):
        test_file = tmp_path / "data.txt"
        test_file.write_text("some content")
        tool = FileReaderTool()
        result = await tool.run(f"Read {test_file}")
        assert "FILE:" in result
        assert "SIZE:" in result

    @pytest.mark.asyncio
    async def test_run_extracts_path_from_quoted_string(self, tmp_path):
        test_file = tmp_path / "notes.txt"
        test_file.write_text("note content")
        tool = FileReaderTool()
        result = await tool.run(f'Read the file "{test_file}"')
        assert "note content" in result


# ─────────────────────────────────────────
# ShellTool
# ─────────────────────────────────────────

class TestShellTool:
    @pytest.mark.asyncio
    async def test_run_command_blocks_rm_rf(self):
        tool = ShellTool()
        result = await tool._run_command("rm -rf /important/dir")
        assert "BLOCKED" in result
        assert "rm -rf" in result

    @pytest.mark.asyncio
    async def test_run_command_blocks_mkfs(self):
        tool = ShellTool()
        result = await tool._run_command("mkfs.ext4 /dev/sda1")
        assert "BLOCKED" in result

    @pytest.mark.asyncio
    async def test_run_command_blocks_sudo_rm(self):
        tool = ShellTool()
        result = await tool._run_command("sudo rm -f /etc/passwd")
        assert "BLOCKED" in result

    @pytest.mark.asyncio
    async def test_run_command_blocks_fork_bomb(self):
        tool = ShellTool()
        result = await tool._run_command(":(){:|:&};:")
        assert "BLOCKED" in result

    @pytest.mark.asyncio
    async def test_run_extracts_command_from_backticks(self):
        tool = ShellTool()
        with patch.object(tool, "_run_command", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = "output"
            result = await tool.run("Please run `echo hello`")
        mock_run.assert_awaited_once_with("echo hello")

    @pytest.mark.asyncio
    async def test_run_extracts_command_from_bash_code_block(self):
        tool = ShellTool()
        message = "Execute this:\n```bash\nls -la\n```"
        with patch.object(tool, "_run_command", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = "file list"
            result = await tool.run(message)
        mock_run.assert_awaited_once_with("ls -la")

    @pytest.mark.asyncio
    async def test_run_returns_no_command_message_for_plain_text(self):
        tool = ShellTool()
        result = await tool.run("Just some plain text with no command indicators")
        assert "No command found" in result

    @pytest.mark.asyncio
    async def test_run_command_returns_blocked_message_not_exception(self):
        """Blocked commands should return a string, not raise an exception."""
        tool = ShellTool()
        result = await tool._run_command("dd if=/dev/random of=/dev/sda")
        assert isinstance(result, str)
        assert "BLOCKED" in result


# ─────────────────────────────────────────
# ToolsManager
# ─────────────────────────────────────────

class TestToolsManager:
    def test_get_returns_web_search_tool(self):
        manager = ToolsManager()
        tool = manager.get("web_search")
        assert isinstance(tool, WebSearchTool)

    def test_get_returns_code_exec_tool(self):
        manager = ToolsManager()
        tool = manager.get("code_exec")
        assert isinstance(tool, CodeExecutorTool)

    def test_get_returns_file_read_tool(self):
        manager = ToolsManager()
        tool = manager.get("file_read")
        assert isinstance(tool, FileReaderTool)

    def test_get_returns_file_write_tool(self):
        manager = ToolsManager()
        tool = manager.get("file_write")
        assert isinstance(tool, FileWriterTool)

    def test_get_returns_shell_tool(self):
        manager = ToolsManager()
        tool = manager.get("shell")
        assert isinstance(tool, ShellTool)

    def test_get_returns_none_for_unknown_tool(self):
        manager = ToolsManager()
        tool = manager.get("nonexistent_tool")
        assert tool is None

    def test_list_tools_returns_all_tool_names(self):
        manager = ToolsManager()
        names = manager.list_tools()
        expected = {"web_search", "code_exec", "file_read", "file_write", "shell"}
        assert set(names) == expected

    def test_list_tools_returns_list_type(self):
        manager = ToolsManager()
        names = manager.list_tools()
        assert isinstance(names, list)

    def test_list_tools_has_correct_count(self):
        manager = ToolsManager()
        assert len(manager.list_tools()) == 5
