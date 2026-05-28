"""#20 — Plugin registry: auto-load tools from plugins/ directory.

Each plugin file must expose a top-level function:
    def register(tools_manager) -> None

Example plugin (plugins/my_tool.py):
    from tools.tools import BaseTool

    class MyTool:
        async def run(self, message: str) -> str:
            return f"Hello from MyTool: {message}"

    def register(tools_manager):
        tools_manager.register("my_tool", MyTool())

Usage (called once at startup):
    from core.plugins import load_plugins
    load_plugins(tools_manager)
"""
import importlib.util
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_PLUGINS_DIR = Path(os.getenv("PLUGINS_DIR", "plugins"))


def load_plugins(tools_manager, plugins_dir: Path | None = None) -> list[str]:
    """Scan plugins_dir and call register(tools_manager) for each plugin.

    Returns list of loaded plugin names.
    """
    directory = plugins_dir or _PLUGINS_DIR
    if not directory.exists():
        return []

    loaded: list[str] = []
    for path in sorted(directory.glob("*.py")):
        if path.stem.startswith("_"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(f"plugin_{path.stem}", path)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)  # type: ignore[arg-type]
            if hasattr(module, "register"):
                module.register(tools_manager)
                loaded.append(path.stem)
                logger.info("Plugin loaded: %s", path.stem)
            else:
                logger.warning("Plugin %s has no register() function — skipped", path.stem)
        except Exception as exc:
            logger.error("Failed to load plugin %s: %s", path.stem, exc)

    return loaded


def list_plugins(plugins_dir: Path | None = None) -> list[dict]:
    """Return metadata about available plugins without loading them."""
    directory = plugins_dir or _PLUGINS_DIR
    if not directory.exists():
        return []
    result = []
    for path in sorted(directory.glob("*.py")):
        if path.stem.startswith("_"):
            continue
        doc = ""
        try:
            spec = importlib.util.spec_from_file_location(f"_meta_{path.stem}", path)
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)  # type: ignore[arg-type]
                doc = (mod.__doc__ or "").strip().split("\n")[0]
        except Exception:
            pass
        result.append({
            "name": path.stem,
            "path": str(path),
            "description": doc,
        })
    return result
