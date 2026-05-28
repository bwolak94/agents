"""All Pydantic request/response models — no business logic."""
from pydantic import BaseModel, Field, field_validator

from api.validators import SESSION_ID_RE


def _check_session_id(v: str) -> str:
    if not SESSION_ID_RE.match(v):
        raise ValueError("session_id must be 1-64 alphanumeric characters, hyphens, or underscores.")
    return v


# ── Chat ──────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"
    stream: bool = False
    show_routing: bool = False
    request_id: str | None = Field(default=None, description="Idempotency key")
    preferred_model: str = ""
    enable_reflection: bool = False
    checkpoint_id: str = ""
    image_base64: str | None = None
    image_url: str | None = None
    persona: str = ""

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        return _check_session_id(v)


class ChatResponse(BaseModel):
    response: str
    model_used: str
    agent_used: str
    tools_used: list[str]
    reasoning: str
    duration_ms: int = 0


class CompareRequest(BaseModel):
    message: str
    session_id: str = "default"
    models: list[str] = Field(default_factory=list)

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        return _check_session_id(v)


class StructuredChatRequest(BaseModel):
    message: str
    session_id: str = "default"
    response_schema: dict = Field(default_factory=dict)
    model: str = ""

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        return _check_session_id(v)


class HandoffPipelineRequest(BaseModel):
    message: str
    session_id: str = "default"
    pipeline: list[dict] = Field(..., description="List of {agent, model, task_template, tools} steps")

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        return _check_session_id(v)


class DebateRequest(BaseModel):
    topic: str
    session_id: str = "default"
    rounds: int = Field(default=2, ge=1, le=5)
    model_a: str = "claude"
    model_b: str = "gemini"

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        return _check_session_id(v)


class FanOutRequest(BaseModel):
    message: str
    session_id: str = "default"
    agents: list[str] = Field(default_factory=list)
    model: str = "claude"

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        return _check_session_id(v)


class VariantsRequest(BaseModel):
    message: str
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
    message: str
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
