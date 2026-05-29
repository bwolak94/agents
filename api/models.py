"""All Pydantic request/response models — no business logic."""
from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field, field_validator

from api.validators import SESSION_ID_RE

# #2 — Limit message length to prevent runaway context / cost
_Message = Annotated[str, Field(min_length=1, max_length=50_000)]

# #7 Reusable ValidatedSessionId — avoids repeating field_validator in every model
_ValidatedSessionId = Annotated[
    str,
    Field(
        default="default",
        pattern=r"^[a-zA-Z0-9_\-]{1,64}$",
        description="Session identifier (1-64 alphanumeric, hyphens, underscores)",
    ),
]


def _check_session_id(v: str) -> str:
    if not SESSION_ID_RE.match(v):
        raise ValueError("session_id must be 1-64 alphanumeric characters, hyphens, or underscores.")
    return v


# ── Chat ──────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    message: _Message
    session_id: _ValidatedSessionId = "default"
    stream: bool = False
    show_routing: bool = False
    request_id: str | None = Field(default=None, description="Idempotency key")
    preferred_model: str = ""
    enable_reflection: bool = False
    checkpoint_id: str = ""
    image_base64: str | None = None
    image_url: str | None = None
    persona: str = ""
    show_scratchpad: bool = False      # #3 chain-of-thought
    enable_self_eval: bool = False     # #2 self-evaluation loop

class ChatResponse(BaseModel):
    response: str
    model_used: str
    agent_used: str
    tools_used: list[str]
    reasoning: str
    duration_ms: int = 0
    scratchpad: str = ""               # #3 chain-of-thought
    confidence: float = -1.0          # #6 confidence score (-1 = not computed)
    self_eval_score: float = -1.0     # #2 self-eval score (-1 = not run)


class CompareRequest(BaseModel):
    message: _Message
    session_id: str = "default"
    models: list[str] = Field(default_factory=list)

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        return _check_session_id(v)


class StructuredChatRequest(BaseModel):
    message: _Message
    session_id: str = "default"
    response_schema: dict = Field(default_factory=dict)
    model: str = ""

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        return _check_session_id(v)


class HandoffPipelineRequest(BaseModel):
    message: _Message
    session_id: str = "default"
    pipeline: list[dict] = Field(..., description="List of {agent, model, task_template, tools} steps")

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        return _check_session_id(v)


class DebateRequest(BaseModel):
    topic: _Message
    session_id: str = "default"
    rounds: int = Field(default=2, ge=1, le=5)
    model_a: str = "claude"
    model_b: str = "gemini"

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        return _check_session_id(v)


class FanOutRequest(BaseModel):
    message: _Message
    session_id: str = "default"
    agents: list[str] = Field(default_factory=list)
    model: str = "claude"

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        return _check_session_id(v)


class VariantsRequest(BaseModel):
    message: _Message
    session_id: str = "default"
    count: int = Field(default=3, ge=2, le=5)
    temperature: float = Field(default=0.9, ge=0.0, le=2.0)
    model: str = ""

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        return _check_session_id(v)


class GitDiffRequest(BaseModel):
    diff: str
    session_id: str = "default"
    focus: str = ""

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        return _check_session_id(v)


class SupervisorRequest(BaseModel):
    message: _Message
    session_id: str = "default"
    model: str = ""

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        return _check_session_id(v)


# ── Sessions ──────────────────────────────────────────────────────────────────

class SessionFindRequest(BaseModel):
    query: str = Field(..., min_length=1)


class ImportContextRequest(BaseModel):
    summary_only: bool = True


class IncrementalContextRequest(BaseModel):
    context: str = Field(..., min_length=1)


class SessionTitleRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=80)


class BroadcastRequest(BaseModel):
    session_ids: list[str]
    message: str

    @field_validator("session_ids")
    @classmethod
    def validate_ids(cls, ids: list[str]) -> list[str]:
        for sid in ids:
            if not SESSION_ID_RE.match(sid):
                raise ValueError(f"Invalid session_id: {sid}")
        return ids


# ── Knowledge ─────────────────────────────────────────────────────────────────

class KnowledgeRequest(BaseModel):
    session_id: str
    title: str
    content: str


class DocumentLoadRequest(BaseModel):
    source: str = Field(..., description="URL, github://owner/repo, or local file path")
    session_id: str = "default"
    title: str = ""
    chunk_size: int = Field(default=2000, ge=500, le=10000)

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        return _check_session_id(v)


# ── Agents / Personas / Macros ────────────────────────────────────────────────

class AgentSystemPromptRequest(BaseModel):
    system_prompt: str


class PersonaRequest(BaseModel):
    name: str = Field(pattern=r"^[a-zA-Z0-9_\-]{1,64}$")
    system_prompt: str
    description: str = ""


class MacroRequest(BaseModel):
    name: str = Field(pattern=r"^/?[a-zA-Z_\-]{1,32}$")
    template: str
    description: str = ""


class WebhookToolRequest(BaseModel):
    name: str = Field(pattern=r"^[a-zA-Z0-9_\-]{1,32}$")
    url: str
    method: str = "POST"


# ── Ops / Scheduling / Admin ──────────────────────────────────────────────────

class PromptSaveRequest(BaseModel):
    session_id: str
    title: str
    content: str
    tags: list[str] = []


class ScheduleRequest(BaseModel):
    session_id: str
    prompt: str
    delay_seconds: float = Field(default=0, ge=0, le=86400)
    interval_seconds: float | None = Field(default=None, ge=10, le=86400)


class FeedbackRequest(BaseModel):
    session_id: str
    message_idx: int = Field(ge=0)
    rating: int = Field(ge=-1, le=1)
    comment: str = ""


class TagRequest(BaseModel):
    session_id: str
    tag: str = Field(min_length=1, max_length=32)


class AdminKeyRequest(BaseModel):
    anthropic_api_key: str | None = None
    gemini_api_key: str | None = None


class BatchRequest(BaseModel):
    tasks: list[dict] = Field(..., description="List of {message, session_id} objects")


# ── Workflows / Experiments / Tenants ─────────────────────────────────────────

class WorkflowRequest(BaseModel):
    workflow_id: str = Field(pattern=r"^[a-zA-Z0-9_\-]{1,64}$")
    name: str
    definition: dict = Field(..., description="DAG definition: {nodes: [...], edges: [...]}")


class WorkflowRunRequest(BaseModel):
    initial_data: dict = Field(default_factory=dict)
    session_id: str = "default"
    persist: bool = True

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        return _check_session_id(v)


class HumanResumeRequest(BaseModel):
    human_response: str


class ExperimentRequest(BaseModel):
    experiment_id: str = Field(pattern=r"^[a-zA-Z0-9_\-]{1,64}$")
    name: str
    variants: list[dict]
    traffic_split: list[float]


class TenantRequest(BaseModel):
    tenant_id: str = Field(pattern=r"^[a-zA-Z0-9_\-]{1,64}$")
    name: str
    plan: str = "free"
    api_key: str | None = None


class PromptVersionRequest(BaseModel):
    system_prompt: str
    bump: str = Field(default="patch", pattern="^(major|minor|patch)$")
    author: str = "api"
    changelog: str = ""


# ── New feature models ────────────────────────────────────────────────────────

class MemoryFactRequest(BaseModel):
    """#1 — Memory graph fact upsert."""
    entity: str = Field(..., min_length=1, max_length=200)
    relation: str = Field(..., min_length=1, max_length=100)
    value: str = Field(..., min_length=1, max_length=2000)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class AsyncChatRequest(BaseModel):
    """#27 — Async chat queue."""
    message: _Message
    session_id: str = "default"
    preferred_model: str = ""

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        return _check_session_id(v)


class WebhookRegisterRequest(BaseModel):
    """#29 — Outbound webhook registration."""
    session_id: str = Field(..., min_length=1, max_length=64)
    url: str = Field(..., min_length=8, max_length=500)
    events: list[str] = Field(default_factory=lambda: ["agent_done"])
    secret: str = ""


class CanaryRequest(BaseModel):
    """#30 — Canary deployment config."""
    stable_prompt: str
    canary_prompt: str
    canary_pct: float = Field(default=10.0, ge=1.0, le=50.0)


class DynamicToolRequest(BaseModel):
    """#4 — Dynamic tool generation."""
    name: str = Field(pattern=r"^[a-zA-Z0-9_]{1,32}$")
    description: str = Field(..., min_length=10, max_length=500)


class DelegateRequest(BaseModel):
    """#5 — Agent delegation chain."""
    message: _Message
    from_agent: str
    to_agent: str
    session_id: str = "default"
    model: str = ""

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        return _check_session_id(v)


class PlaygroundRequest(BaseModel):
    """#12 — Prompt playground: run across multiple agents/models."""
    prompt: _Message
    session_id: str = "default"
    agents: list[str] = Field(default_factory=list)
    models: list[str] = Field(default_factory=list)

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        return _check_session_id(v)


class SessionForkRequest(BaseModel):
    """#13 — Session forking."""
    new_session_id: str = Field(pattern=r"^[a-zA-Z0-9_\-]{1,64}$")
    at_message_index: int = Field(default=-1, description="Fork at this message index; -1 = full history")


class DigestScheduleRequest(BaseModel):
    """#11 — Scheduled digest."""
    session_id: str = "default"
    frequency: str = Field(default="daily", pattern="^(daily|weekly)$")
    hour_utc: int = Field(default=9, ge=0, le=23)
    email: str = ""  # optional delivery address (display only; email sending not implemented)

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        return _check_session_id(v)


class SessionMergeRequest(BaseModel):
    """Merge source session history into target session."""
    source_session_id: str = Field(pattern=r"^[a-zA-Z0-9_\-]{1,64}$")
    target_session_id: str = Field(pattern=r"^[a-zA-Z0-9_\-]{1,64}$")
    deduplicate: bool = Field(default=True, description="Skip messages already in target")


class SimulateRequest(BaseModel):
    """Sandboxed agent simulation — no history saved."""
    message: _Message
    system_prompt: str = Field(default="", max_length=10_000)
    model: str = "claude"
    agent: str = ""
    session_id: str = "default"
    turns: int = Field(default=1, ge=1, le=10)

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        return _check_session_id(v)


# ── Round 7 feature models ────────────────────────────────────────────────────

class PlanRequest(BaseModel):
    """Multi-step planning mode: produce plan, optionally execute."""
    message: _Message
    session_id: str = "default"
    model: str = "claude"
    execute: bool = Field(default=True, description="If true, execute plan steps after approval")

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        return _check_session_id(v)


class RedTeamRequest(BaseModel):
    """Adversarial red-team: answer vs critic, confidence-adjusted result."""
    message: _Message
    session_id: str = "default"
    model_answerer: str = "claude"
    model_critic: str = "gemini"

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        return _check_session_id(v)


class HandoffRequest(BaseModel):
    """Structured agent handoff with briefing document."""
    message: _Message
    session_id: str = "default"
    from_agent: str
    to_agent: str
    model: str = "claude"

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        return _check_session_id(v)


class TestGenRequest(BaseModel):
    """Auto-generate pytest tests from session history / code snippet."""
    session_id: str = "default"
    code: str = Field(default="", max_length=20_000)
    framework: str = Field(default="pytest", pattern="^(pytest|unittest)$")

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        return _check_session_id(v)


class MockGenRequest(BaseModel):
    """Generate a FastAPI mock router from an OpenAPI spec."""
    spec: str = Field(..., min_length=10, max_length=50_000, description="OpenAPI JSON or YAML spec")
    session_id: str = "default"

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        return _check_session_id(v)


class DepScanRequest(BaseModel):
    """Scan requirements.txt or package.json for known vulnerabilities."""
    content: str = Field(..., min_length=1, max_length=50_000)
    file_type: str = Field(default="requirements.txt", pattern="^(requirements\\.txt|package\\.json)$")


class CommentRequest(BaseModel):
    author: str = Field(default="user", max_length=64)
    text: str = Field(..., min_length=1, max_length=2000)


class RoleGrantRequest(BaseModel):
    session_id: str = Field(pattern=r"^[a-zA-Z0-9_\-]{1,64}$")
    role: str = Field(default="read", pattern="^(read|write|admin)$")
    ttl_hours: int = Field(default=0, ge=0, le=8760, description="Hours until token expires (0 = never)")


class PluginInstallRequest(BaseModel):
    name: str = Field(pattern=r"^[a-zA-Z0-9_\-]{1,64}$")
    description: str = Field(..., min_length=10, max_length=500)
    tool_definition: dict = Field(default_factory=dict)
    author: str = Field(default="community", max_length=64)


class InsightExtractRequest(BaseModel):
    """Extract cross-session insights from recent sessions."""
    session_ids: list[str] = Field(default_factory=list, description="Empty = all recent sessions")
    max_sessions: int = Field(default=20, ge=1, le=100)

    @field_validator("session_ids")
    @classmethod
    def validate_ids(cls, ids: list[str]) -> list[str]:
        for sid in ids:
            if not SESSION_ID_RE.match(sid):
                raise ValueError(f"Invalid session_id: {sid}")
        return ids
