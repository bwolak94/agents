"""
System configuration - loads from .env or environment variables.
"""
import os
from pathlib import Path


def load_config() -> dict:
    """Load configuration from .env and environment variables."""
    # Try to load .env if it exists
    env_file = Path(__file__).parent.parent / ".env"
    if env_file.exists():
        _load_dotenv(env_file)

    config = {
        # API Keys
        "anthropic_api_key": os.getenv("ANTHROPIC_API_KEY", ""),
        "gemini_api_key": os.getenv("GEMINI_API_KEY", ""),
        "brave_api_key": os.getenv("BRAVE_API_KEY", ""),
        "mongo_url": os.getenv("MONGO_URL", "mongodb://mongo:27017"),

        # Ollama
        "ollama_url": os.getenv("OLLAMA_URL", "http://ollama:11434"),

        # Options
        "stream": os.getenv("STREAM", "true").lower() == "true",
        "default_model": os.getenv("DEFAULT_MODEL", "claude"),

        # Server
        "api_host": os.getenv("API_HOST", "0.0.0.0"),
        "api_port": int(os.getenv("API_PORT", "8000")),
        "web_port": int(os.getenv("WEB_PORT", "3000")),
    }

    # Validation - warn if keys are missing
    if not config["anthropic_api_key"]:
        print("⚠️  WARNING: Missing ANTHROPIC_API_KEY — Claude unavailable")
    if not config["gemini_api_key"]:
        print("⚠️  WARNING: Missing GEMINI_API_KEY — Gemini unavailable")

    return config


def _load_dotenv(env_file: Path):
    """Simple .env parser with no external dependencies."""
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key not in os.environ:  # Don't overwrite existing values
                    os.environ[key] = value
