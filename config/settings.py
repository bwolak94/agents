"""
System configuration — loads from .env or environment variables.
"""
import logging
import os
from pathlib import Path
from typing import TypedDict

logger = logging.getLogger(__name__)


# ── Env-var name constants (shared with core/rbac.py) ────────────────────────

ADMIN_API_KEY_ENV = "ADMIN_API_KEY"
USER_API_KEY_ENV  = "USER_API_KEY"
API_KEY_ENV       = "API_KEY"


class AppConfig(TypedDict):
    anthropic_api_key: str
    gemini_api_key: str
    brave_api_key: str
    mongo_url: str
    ollama_url: str
    stream: bool
    default_model: str
    api_host: str
    api_port: int
    web_port: int


def load_config() -> AppConfig:
    """Load configuration from .env and environment variables."""
    env_file = Path(__file__).parent.parent / ".env"
    if env_file.exists():
        _load_dotenv(env_file)

    config: AppConfig = {
        "anthropic_api_key": os.getenv("ANTHROPIC_API_KEY", ""),
        "gemini_api_key":    os.getenv("GEMINI_API_KEY", ""),
        "brave_api_key":     os.getenv("BRAVE_API_KEY", ""),
        "mongo_url":         os.getenv("MONGO_URL", "mongodb://mongo:27017"),
        "ollama_url":        os.getenv("OLLAMA_URL", "http://ollama:11434"),
        "stream":            os.getenv("STREAM", "true").lower() == "true",
        "default_model":     os.getenv("DEFAULT_MODEL", "claude"),
        "api_host":          os.getenv("API_HOST", "0.0.0.0"),
        "api_port":          int(os.getenv("API_PORT", "8000")),
        "web_port":          int(os.getenv("WEB_PORT", "3000")),
    }

    if not config["anthropic_api_key"]:
        logger.warning("Missing ANTHROPIC_API_KEY — Claude unavailable")
    if not config["gemini_api_key"]:
        logger.warning("Missing GEMINI_API_KEY — Gemini unavailable")

    return config


def _load_dotenv(env_file: Path) -> None:
    """Simple .env parser with no external dependencies."""
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key not in os.environ:
                    os.environ[key] = value
