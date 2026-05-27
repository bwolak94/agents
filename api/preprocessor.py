"""
Message preprocessor — runs before the message reaches the orchestrator.

Handles (in order):
1. Macro expansion  — /code, /explain, /debug, /review, etc.
2. @file injection  — @path/to/file → inline file content
3. Model prefix     — "haiku: <msg>" → model override + clean message
4. Format detection — detects "as table", "as JSON" etc. and appends format hint
"""
import re
import os
from pathlib import Path

# ─── Allowed base dirs for @file injection (security) ─────────────────────────
_ALLOWED_ROOTS = [
    Path.home(),
    Path("/tmp"),
    Path("/var/tmp"),
]
_MAX_FILE_SIZE = 100_000  # 100KB cap per injected file

# ─── Model prefix patterns ────────────────────────────────────────────────────
_MODEL_PREFIXES: dict[str, str] = {
    "haiku:":           "claude-haiku",
    "claude-haiku:":    "claude-haiku",
    "claude:":          "claude",
    "sonnet:":          "claude",
    "gemini:":          "gemini",
    "llama:":           "ollama/llama3",
    "mistral:":         "ollama/mistral",
    "phi:":             "ollama/phi3",
    "local:":           "ollama/llama3",
    "fast:":            "claude-haiku",
    "cheap:":           "claude-haiku",
}

# ─── Format detection ─────────────────────────────────────────────────────────
_FORMAT_HINTS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(as a table|in table format|tabular)\b", re.I),
     "\n\nPlease format your response as a markdown table."),
    (re.compile(r"\b(as json|in json|return json|output json)\b", re.I),
     "\n\nRespond with ONLY valid JSON, no prose."),
    (re.compile(r"\b(as (bullet[s]?|list)|bullet points|as points)\b", re.I),
     "\n\nFormat your response as a concise bullet-point list."),
    (re.compile(r"\b(step by step|step-by-step|numbered steps)\b", re.I),
     "\n\nFormat your response as numbered steps."),
    (re.compile(r"\b(as markdown|in markdown)\b", re.I),
     "\n\nUse rich markdown formatting with headers, code blocks, and emphasis."),
    (re.compile(r"\b(one[ -]liner|single line|terse|brief answer)\b", re.I),
     "\n\nRespond in ONE sentence only."),
]


def _is_path_allowed(path: Path) -> bool:
    resolved = path.resolve()
    return any(
        str(resolved).startswith(str(root.resolve()))
        for root in _ALLOWED_ROOTS
    )


def _inject_files(message: str) -> str:
    """Replace @path references with inline file content."""
    def replace_ref(match: re.Match) -> str:
        raw_path = match.group(1)
        path = Path(raw_path).expanduser()

        if not path.exists():
            return f"[File not found: {raw_path}]"
        if not _is_path_allowed(path):
            return f"[Access denied: {raw_path}]"

        if path.is_dir():
            # Directory: concatenate all text files (max 10 files)
            parts = []
            for f in sorted(path.iterdir()):
                if f.is_file() and f.suffix in {
                    ".py", ".ts", ".tsx", ".js", ".jsx", ".md", ".txt",
                    ".json", ".yaml", ".yml", ".toml", ".sh", ".env",
                    ".go", ".rs", ".java", ".c", ".cpp", ".h",
                }:
                    try:
                        content = f.read_text(errors="replace")[:_MAX_FILE_SIZE // 10]
                        parts.append(f"```{f.suffix.lstrip('.')}\n# {f.name}\n{content}\n```")
                    except Exception:
                        pass
                    if len(parts) >= 10:
                        break
            return f"\n\n[Directory: {raw_path}]\n" + "\n\n".join(parts)

        if path.stat().st_size > _MAX_FILE_SIZE:
            return f"[File too large (>{_MAX_FILE_SIZE // 1000}KB): {raw_path}]"

        try:
            content = path.read_text(errors="replace")
            ext = path.suffix.lstrip(".")
            return f"\n\n```{ext}\n# {path.name}\n{content}\n```"
        except Exception as e:
            return f"[Error reading {raw_path}: {e}]"

    # Match @/absolute/path or @relative/path or @~/home/path
    return re.sub(r"@([~/\w\.\-][^\s,;]*)", replace_ref, message)


def _extract_model_prefix(message: str) -> tuple[str, str]:
    """Return (model_override, clean_message). model_override is "" if none found."""
    stripped = message.strip()
    lower = stripped.lower()
    for prefix, model in sorted(_MODEL_PREFIXES.items(), key=lambda x: -len(x[0])):
        if lower.startswith(prefix):
            rest = stripped[len(prefix):].strip()
            return model, rest
    return "", message


def _detect_format(message: str) -> str:
    """Append format instruction if the message implies a format preference."""
    for pattern, hint in _FORMAT_HINTS:
        if pattern.search(message):
            return message + hint
    return message


async def preprocess(message: str) -> tuple[str, str]:
    """
    Full preprocessing pipeline.

    Returns:
        (processed_message, model_override)
        model_override is "" if not specified by prefix.
    """
    # Step 1: Macro expansion
    from db.macros import extract_macro_from_message, get_macro, expand_macro
    macro_name, rest = extract_macro_from_message(message)
    if macro_name:
        macro = await get_macro(macro_name)
        if macro:
            message = macro["template"] + rest
        # else: unknown macro, pass through as-is

    # Step 2: @file injection
    message = _inject_files(message)

    # Step 3: Model prefix extraction
    model_override, message = _extract_model_prefix(message)

    # Step 4: Format detection
    message = _detect_format(message)

    return message, model_override
