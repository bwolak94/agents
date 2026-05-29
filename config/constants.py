"""
Centralised constants — all magic numbers in one place.
Import via: from config.constants import LLM_TIMEOUT_SECONDS, ...
"""
import os

# ── LLM ───────────────────────────────────────────────────────────────────────
DEFAULT_MAX_TOKENS: int     = 4096
HAIKU_MAX_TOKENS: int       = 2048
DEFAULT_TEMPERATURE: float  = 0.7
LOW_TEMPERATURE: float      = 0.2

CONTEXT_LIMITS: dict[str, int] = {
    "claude":       190_000,
    "claude-haiku": 190_000,
    "gemini":     1_000_000,
}

LLM_TIMEOUT_SECONDS: float  = float(os.getenv("LLM_TIMEOUT_SECONDS", "120"))
LLM_FALLBACK_CHAIN: list[str] = ["claude", "gemini", "ollama/llama3"]

# Retry & backoff
LLM_RETRY_ATTEMPTS: int     = int(os.getenv("LLM_RETRY_ATTEMPTS", "3"))
LLM_RETRY_BASE_DELAY: float = 1.0   # seconds
LLM_RETRY_MAX_DELAY: float  = 30.0  # seconds

# ── Agent ─────────────────────────────────────────────────────────────────────
MAX_REACT_ITERATIONS: int   = int(os.getenv("MAX_REACT_ITERATIONS", "6"))
MAX_TOOL_CALLS_PER_TURN: int = int(os.getenv("MAX_TOOL_CALLS_PER_TURN", "10"))
TOOL_ERROR_MAX_RETRIES: int = 2
SUMMARIZE_THRESHOLD: int    = int(os.getenv("SUMMARIZE_THRESHOLD", "20"))
MEMORY_DECAY_DAYS: int      = int(os.getenv("MEMORY_DECAY_DAYS", "30"))
SELF_EVAL_THRESHOLD: float  = float(os.getenv("SELF_EVAL_THRESHOLD", "0.6"))

# ── Rate limiting ─────────────────────────────────────────────────────────────
RATE_LIMIT_RPM: int              = int(os.getenv("RATE_LIMIT_RPM", "60"))
SESSION_RATE_LIMIT_RPM: int      = int(os.getenv("SESSION_RATE_LIMIT_RPM", "20"))
# plan / red-team / fan-out make 3-4× more LLM calls
EXPENSIVE_RATE_LIMIT_RPM: int    = int(os.getenv("EXPENSIVE_RATE_LIMIT_RPM", "10"))
RATE_WINDOW_MAX_IPS: int         = 10_000

# ── Request / session ─────────────────────────────────────────────────────────
MAX_REQUEST_BODY_BYTES: int = int(os.getenv("MAX_REQUEST_BODY_BYTES", str(2 * 1024 * 1024)))
MAX_SESSIONS: int           = int(os.getenv("MAX_SESSIONS", "200"))
SESSION_TTL_DAYS: int       = int(os.getenv("SESSION_TTL_DAYS", "90"))
SESSION_ROLE_TTL_DAYS: int  = int(os.getenv("SESSION_ROLE_TTL_DAYS", "30"))

# ── File injection ────────────────────────────────────────────────────────────
MAX_FILE_INJECT_BYTES: int  = int(os.getenv("MAX_FILE_INJECT_BYTES", str(100_000)))

# ── MongoDB ───────────────────────────────────────────────────────────────────
MONGO_MAX_POOL: int         = int(os.getenv("MONGO_MAX_POOL_SIZE", "20"))
MONGO_MIN_POOL: int         = int(os.getenv("MONGO_MIN_POOL_SIZE", "5"))
MONGO_CONNECT_TIMEOUT_MS: int  = 5_000
MONGO_SOCKET_TIMEOUT_MS: int   = 30_000

# ── Cost monitoring ───────────────────────────────────────────────────────────
COST_BUDGET_USD: float      = float(os.getenv("COST_BUDGET_USD", "0"))  # 0 = disabled

# ── Cache / analytics ─────────────────────────────────────────────────────────
ANALYTICS_STALE_SECONDS: int    = int(os.getenv("ANALYTICS_STALE_SECONDS", "60"))
REDIS_URL: str | None           = os.getenv("REDIS_URL")
REDIS_TTL_SECONDS: int          = int(os.getenv("REDIS_TTL_SECONDS", "30"))

# ── Scheduled reports ─────────────────────────────────────────────────────────
MAX_SCHEDULED_REPORTS: int  = 50
