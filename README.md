# Multi-LLM Agent System

A production-grade multi-agent AI platform supporting Claude, Gemini, and Ollama models. Features a FastAPI backend with streaming, a Next.js frontend, MongoDB persistence, and a LangGraph-style DAG workflow engine.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Technology Stack](#technology-stack)
- [Project Structure](#project-structure)
- [Key Patterns](#key-patterns)
- [Agent Types](#agent-types)
- [API Overview](#api-overview)
- [Getting Started](#getting-started)
- [Configuration Reference](#configuration-reference)
- [Testing](#testing)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Next.js Frontend (3000)                      │
│  ChatView  |  AgentPanel  |  CostTrackerHUD  |  CommandPalette      │
│  AnalyticsDashboard  |  WorkflowBuilder  |  ArtifactPanel           │
└────────────────────────────┬────────────────────────────────────────┘
                             │ HTTP / WebSocket / SSE
┌────────────────────────────▼────────────────────────────────────────┐
│                     FastAPI Backend (8000)                           │
│                                                                      │
│  Middleware Stack (in order):                                        │
│  Body Size → Request-ID → Auth → RBAC → Security Headers →          │
│  Server-Timing → Content-Type → Heavy Concurrency →                 │
│  Rate Limit (per-IP / API-key) → Cost Budget → PII Redaction        │
│                                                                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │
│  │  /chat   │ │/sessions │ │/knowledge│ │/workflows│ │ /agents  │  │
│  └────┬─────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘  │
│       │                                                              │
│  ┌────▼──────────────────────────────────────────────────────────┐  │
│  │                    AgentOrchestrator                          │  │
│  │                                                               │  │
│  │  RouterAgent ──► decides: model + agent + tools + fallbacks   │  │
│  │       │                                                       │  │
│  │       ├──► Single Agent (with ReAct loop + tool calls)        │  │
│  │       ├──► Fan-Out  (parallel agents, asyncio.gather)         │  │
│  │       ├──► Pipeline (sequential handoffs, DAG)                │  │
│  │       └──► Debate   (agent-A vs agent-B + judge synthesis)    │  │
│  └────────────────────────┬──────────────────────────────────────┘  │
│                           │                                          │
│  ┌────────────────────────▼──────────────────────────────────────┐  │
│  │                      LLMManager                               │  │
│  │  Claude (Anthropic) │ Gemini (Google) │ Ollama (local)        │  │
│  │  Circuit Breaker │ Fallback Chain │ Cost Tracking │ RPM Limit │  │
│  └────────────────────────┬──────────────────────────────────────┘  │
└───────────────────────────┼─────────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────────┐
│                         MongoDB (Motor async)                        │
│  conversations │ memory │ analytics │ rag │ workflows │ tenants      │
│  personas │ webhooks │ experiments │ prompt_versions │ ...           │
└─────────────────────────────────────────────────────────────────────┘
```

### Request Flow — Chat

```
Client
  │
  ▼
POST /chat/stream
  │
  ├── [middleware] rate limit check
  ├── [middleware] cost budget check
  ├── [middleware] PII redaction (opt-in)
  │
  ▼
chat.py router
  ├── request coalescing (deduplicate identical concurrent calls)
  ├── preprocess  (macro expansion, @file injection, model prefix)
  │
  ▼
AgentOrchestrator.process()
  ├── RouterAgent  → JSON routing decision (model/agent/tools/complexity)
  ├── Auto-RAG     → inject relevant knowledge-base chunks
  ├── _run_with_fallback()
  │     ├── check circuit breaker (skip unhealthy models)
  │     ├── agent.run()  — ReAct loop (up to 6 iterations)
  │     │     ├── LLM call
  │     │     ├── parse tool calls
  │     │     ├── execute tools in parallel
  │     │     └── feed results back to LLM
  │     └── fallback to next model on failure
  │
  ├── history summarization (auto-compress when > threshold)
  ├── persist to MongoDB
  └── SSE stream back to client (token by token)
```

### Supervisor / DAG Workflow Flow

```
POST /chat/supervisor
  │
  ▼
SupervisorAgent
  ├── LLM: decompose task into subtasks JSON
  ├── asyncio.gather() — run subtasks in parallel per dependencies
  │     ├── subtask_0 → agent_A (research_agent)
  │     ├── subtask_1 → agent_B (code_agent)
  │     └── subtask_2 → agent_C (general_agent)
  └── LLM: synthesize all results (merge | chain | vote strategy)

POST /workflows/{id}/run
  │
  ▼
StateGraph (core/graph.py)
  ├── nodes: async callables
  ├── conditional edges: router functions
  ├── human-in-the-loop: asyncio.Event pause/resume
  └── persistent snapshots to MongoDB
```

---

## Technology Stack

### Backend

| Layer | Technology | Version |
|---|---|---|
| API Framework | FastAPI | 0.115.0 |
| ASGI Server | Uvicorn | 0.30.6 |
| Async HTTP | httpx | 0.27.2 |
| Data Validation | Pydantic v2 | 2.9.2 |
| Database | MongoDB via Motor | 3.6.0 |
| LLM: Claude | Anthropic SDK (via LangChain) | — |
| LLM: Gemini | Google Generative AI | — |
| LLM: Local | Ollama (HTTP API) | — |
| Workflow Engine | LangChain + LangGraph | 0.3.14 / 0.2.60 |
| Document Loaders | pypdf, beautifulsoup4 | — |
| Observability | OpenTelemetry + OTLP | 1.29.0 |
| Terminal UI | Rich | 13.9.2 |
| Web Scraping | DuckDuckGo Search | 6.3.7 |
| Language | Python | 3.12 |

### Frontend

| Layer | Technology |
|---|---|
| Framework | Next.js 14 (App Router) |
| Language | TypeScript |
| Styling | Tailwind CSS |
| Real-time | WebSocket (native), SSE |
| State | React hooks (useState, useRef, useEffect) |
| Edge Middleware | Next.js Edge Runtime (CSP nonce) |

### Infrastructure

| Component | Technology |
|---|---|
| Database | MongoDB |
| Local LLMs | Ollama |
| Search (optional) | Brave Search API / DuckDuckGo fallback |
| Tracing (optional) | OpenTelemetry → any OTLP collector |
| CI | GitHub Actions |

---

## Project Structure

```
agents/
├── api/                        # FastAPI application
│   ├── server.py               # App factory: lifespan, middleware, router registration
│   ├── db.py                   # Central DB module registry (all db.* refs)
│   ├── state.py                # SessionManager — per-session orchestrators
│   ├── models.py               # Pydantic request/response models
│   ├── preprocessor.py         # Macro expansion, @file injection, model prefix
│   ├── pii.py                  # PII redaction patterns (email, phone, SSN, card)
│   ├── validators.py           # Session ID validation
│   └── routers/
│       ├── chat.py             # /chat, /chat/stream, /chat/fan-out, /chat/simulate
│       ├── sessions.py         # /sessions, /history, /search, session lifecycle
│       ├── knowledge.py        # /knowledge, /upload — RAG document management
│       ├── agents.py           # /agents, /personas, /macros, /tools/custom
│       ├── ops.py              # /health, /metrics, /analytics, /memory, /prompts
│       ├── workflows.py        # /workflows, /experiments, /tenants, /marketplace
│       ├── advanced.py         # /chat/plan, /chat/red-team, /search/semantic, ...
│       ├── multimodal.py       # Image analysis endpoints
│       ├── intelligence.py     # Sentiment, summarization, card endpoints
│       ├── platform.py         # Batch processing, scheduling
│       ├── comments.py         # Message comment threads
│       ├── webhook_triggers.py # Webhooks with HMAC-SHA256 validation
│       └── ws.py               # WebSocket /ws
│
├── core/                       # Cross-cutting concerns
│   ├── orchestrator.py         # AgentOrchestrator — fan-out, pipeline, debate
│   ├── router.py               # RouterAgent — LLM-based routing decisions
│   ├── graph.py                # LangGraph-style DAG engine with human-in-loop
│   ├── supervisor.py           # Supervisor meta-agent (decompose + synthesize)
│   ├── events.py               # AsyncEventBus — real-time agent event streaming
│   ├── scheduler.py            # Cron-style task scheduler
│   ├── tracing.py              # OpenTelemetry setup (opt-in via OTEL_ENABLED)
│   ├── rbac.py                 # Role-based access control middleware
│   ├── sse.py                  # SSE router for agent event streaming
│   ├── plugins.py              # Plugin loader
│   ├── queue.py                # Async work queue
│   └── timer.py                # Context manager for timing code blocks
│
├── agents/
│   └── agents.py               # BaseAgent + specialist agents (ReAct loop)
│
├── llm/
│   └── manager.py              # LLMManager: Claude / Gemini / Ollama unified API
│                               # Circuit breaker, fallback chain, cost tracking
│
├── db/                         # MongoDB data access modules
│   ├── history.py              # Conversation persistence + cursor pagination
│   ├── memory.py               # Agent long-term memory
│   ├── analytics.py            # Request analytics + TTL index
│   ├── rag.py                  # Vector search / RAG chunks
│   ├── cache.py                # In-memory LRU + MongoDB cache
│   ├── workflows.py            # Workflow DAG storage + run state
│   ├── experiments.py          # A/B testing with deterministic variant assignment
│   ├── tenants.py              # Multi-tenant plan-based limits
│   ├── webhooks.py             # Webhook registry
│   ├── memory_graph.py         # Graph-structured agent memory
│   └── ...                     # personas, tags, macros, batch, prompts, feedback, ...
│
├── tools/                      # Tool implementations (ReAct tool calls)
│   └── tools.py                # ToolsManager: web_search, code_exec, file_read/write, shell, memory
│
├── config/
│   ├── settings.py             # Config loader (env vars → dict)
│   ├── constants.py            # Magic numbers: timeouts, limits, budgets
│   └── logging.py              # Structured logging setup
│
├── web/                        # Next.js frontend
│   └── src/
│       ├── app/                # Next.js App Router pages
│       ├── components/         # React components
│       │   ├── AgentApp/       # Root application shell
│       │   ├── ChatView/       # Message thread + streaming
│       │   ├── ChatHistorySidebar/  # Session list with virtual scroll
│       │   ├── AgentPanel/     # Live agent status monitor
│       │   ├── CostTrackerHUD/ # Real-time cost display (WS push)
│       │   ├── CommandPalette/ # Keyboard-driven command palette (Cmd+K)
│       │   ├── AnalyticsDashboard/  # Usage heatmap + cost forecast
│       │   ├── ArtifactPanel/  # Code/JSON artifact extraction
│       │   ├── WorkflowBuilder/ # Drag-and-drop DAG editor
│       │   ├── VoiceConversation/ # SpeechRecognition + TTS
│       │   ├── ABTestView/     # Side-by-side A/B system prompt testing
│       │   └── ...
│       ├── hooks/              # useChat, useWebSocket, useChatHistory, ...
│       └── middleware.ts       # CSP nonce injection (Edge Runtime)
│
├── tests/
│   ├── unit/                   # 196 unit tests
│   └── integration/            # 54 integration tests
│
├── .github/workflows/          # GitHub Actions CI pipelines
├── pyproject.toml              # Pytest, Ruff, mypy, mutmut config
├── requirements.txt
└── locustfile.py               # Load testing scenarios
```

---

## Key Patterns

### 1. Router → Agent → LLM Pipeline

Every chat request goes through a `RouterAgent` that makes an LLM call to classify the task and return a structured JSON routing decision:

```
{
  "model": "claude",
  "fallback_models": ["claude-haiku", "ollama/llama3"],
  "agent": "code_agent",
  "tools": ["code_exec", "web_search"],
  "complexity": "high",
  "parallel_tasks": null
}
```

The orchestrator then runs the chosen agent with the circuit breaker walking the fallback chain on failure.

### 2. ReAct Loop (Reason + Act)

Each agent runs a ReAct loop (up to 6 iterations):

```
LLM generates response
  └─► contains <tool_call>?
        YES → execute tool(s) in parallel → feed <tool_result> back to LLM → repeat
        NO  → return final response
```

Features: parallel tool calls, tool result summarization (>6KB), deduplication within session, auto-retry on tool error (2x), per-turn tool budget (`MAX_TOOL_CALLS_PER_TURN`).

### 3. Circuit Breaker (LLM Health)

`LLMManager` tracks health per model. After consecutive failures, the model is marked unhealthy (circuit open). The orchestrator skips it in the fallback chain. State is optionally persisted to a JSON file (`CB_STATE_FILE`) to survive restarts.

### 4. Event-Driven Agent Monitoring

An `AsyncEventBus` (`core/events.py`) emits typed events (`routing`, `agent_start`, `agent_thinking`, `agent_done`, `pipeline_step`, `debate_start`, ...) that are fanned out over WebSocket and SSE to the frontend for live agent monitoring.

### 5. Sliding Window Rate Limiter

Two independent rate limiters:
- **Global**: per-IP or per-API-key hash, configurable RPM (`RATE_LIMIT_RPM`)
- **Expensive endpoints** (`/chat/plan`, `/chat/red-team`, `/chat/fan-out`): separate lower limit + concurrency semaphore

Both use `collections.deque` for O(1) window eviction. Memory is bounded by periodic cleanup (every 5 min) and an IP cap (10,000 entries).

### 6. Cost Budget Guard

Middleware aggregates daily LLM spend from MongoDB analytics. If the daily total exceeds `COST_BUDGET_USD`, chat endpoints return `429 BUDGET_EXCEEDED`. The aggregation result is cached in memory with a 60-second TTL to avoid hammering the DB on every request.

### 7. Auto-RAG Injection

Before any agent runs, the orchestrator queries the RAG collection for the top-3 most relevant knowledge-base chunks for the current message. Matching chunks are prepended inside `<context>` tags. This is best-effort and never blocks the main flow.

### 8. History Summarization

When conversation history exceeds `SUMMARIZE_THRESHOLD` messages (default 16), the orchestrator asks Claude Haiku to produce a 3–5 bullet-point summary of the older messages. The summary replaces the old turns, keeping the context window bounded without losing key information.

### 9. Multi-Agent Execution Modes

| Mode | Description |
|---|---|
| **Single** | One agent, one model, with ReAct tool loop |
| **Fan-Out** | Same message sent to N agents in parallel (`asyncio.gather`) |
| **Pipeline** | Sequential DAG — output of each step feeds the next |
| **Debate** | Agent A vs Agent B for N rounds, then a judge synthesises |
| **Supervisor** | LLM decomposes task → parallel subtasks → synthesis |
| **DAG Workflow** | Custom node graph with conditional edges + human-in-the-loop |

### 10. PII Redaction (opt-in)

When `PII_REDACTION=true`, a middleware intercepts POST bodies on chat endpoints and replaces email addresses, phone numbers, SSNs, and card numbers with `[REDACTED_*]` patterns before the text reaches the LLM.

### 11. Structured Error Envelope

All error responses use a consistent schema:

```json
{
  "code": "RATE_LIMITED",
  "message": "Rate limit exceeded. Please slow down.",
  "request_id": "abc-123"
}
```

Validation errors include a `fields` array with per-field messages.

---

## Agent Types

| Agent | Best For | Default Tools |
|---|---|---|
| `code_agent` | Code writing, debugging, refactoring | `code_exec`, `file_read`, `file_write` |
| `research_agent` | Web search, fact-checking, source analysis | `web_search`, `memory_read` |
| `learn_agent` | Explanations, quizzes, teaching | — |
| `file_agent` | Documents, data extraction, file processing | `file_read`, `file_write` |
| `general_agent` | Everything else | `memory_read`, `memory_write` |

All agents share the same `BaseAgent.run()` implementation with the ReAct loop. The difference is the system prompt and default tool set.

---

## API Overview

All routes are available at both `/` and `/api/v1/` (versioned alias).

### Chat

| Method | Path | Description |
|---|---|---|
| `POST` | `/chat` | Single-turn, returns full response |
| `POST` | `/chat/stream` | SSE token stream |
| `POST` | `/chat/fan-out/stream` | SSE per-agent stream (all agents in parallel) |
| `POST` | `/chat/simulate` | Sandboxed chat without history persistence |
| `POST` | `/chat/plan` | Agentic planning mode |
| `POST` | `/chat/red-team` | Red-team adversarial probing |
| `POST` | `/chat/supervisor` | Supervisor decompose-and-synthesize |
| `POST` | `/chat/negotiate` | Multi-model negotiation |
| `POST` | `/chat/analyze-image` | Multimodal image analysis |

### Sessions

| Method | Path | Description |
|---|---|---|
| `GET` | `/sessions` | List sessions (cursor pagination) |
| `POST` | `/sessions` | Create session |
| `GET` | `/sessions/{id}` | Get session metadata |
| `PATCH` | `/sessions/{id}` | Update title / tags |
| `DELETE` | `/sessions/{id}` | Soft-delete (or hard with `?hard=true`) |
| `POST` | `/sessions/{id}/unarchive` | Restore archived session |
| `GET` | `/sessions/{id}/replay` | Unified diff between two message versions |
| `GET` | `/sessions/{id}/cost` | Aggregated cost for session |
| `POST` | `/sessions/{id}/summarize` | Generate session summary |
| `GET` | `/sessions/{id}/sentiment` | Sentiment analysis of session |
| `GET` | `/history/{session_id}` | Full message history (ETag cached) |
| `POST` | `/sessions/merge` | Merge two sessions |
| `GET` | `/search` | Full-text search across sessions |

### Knowledge / RAG

| Method | Path | Description |
|---|---|---|
| `POST` | `/upload` | Upload file to RAG index |
| `GET` | `/knowledge` | List knowledge entries |
| `POST` | `/knowledge` | Add knowledge entry |
| `DELETE` | `/knowledge/{id}` | Remove entry |
| `POST` | `/knowledge/load` | Bulk load via LangChain loaders (PDF, web, CSV, GitHub) |

### Ops / Platform

| Method | Path | Description |
|---|---|---|
| `GET` | `/health/live` | Liveness probe |
| `GET` | `/health/ready` | Readiness probe (checks Motor pool) |
| `GET` | `/health` | Full health with model status |
| `GET` | `/metrics` | Prometheus-format metrics |
| `GET` | `/models` | Available models (ETag cached) |
| `GET/PATCH` | `/memory/{session_id}` | Read / merge agent memory |
| `GET` | `/analytics/summary` | Usage summary (secondaryPreferred) |
| `GET` | `/analytics/heatmap` | Day × hour usage heatmap |

### WebSocket

```
ws://localhost:8000/ws?session_id=<id>
```

Receives JSON events: `agent_start`, `agent_thinking`, `agent_done`, `pipeline_step`, `cost`, `routing`, ...

---

## Getting Started

### Prerequisites

- Python 3.12+
- Node.js 20+
- MongoDB (local or Docker)
- Ollama (optional, for local models)

### 1. Clone and configure

```bash
git clone <repo-url>
cd agents
cp .env .env.local   # edit with your keys
```

Minimum required variables:

```bash
MONGO_URL=mongodb://localhost:27017
ANTHROPIC_API_KEY=sk-ant-...        # for Claude
GEMINI_API_KEY=AIza...              # for Gemini (optional)
```

### 2. Backend

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start the API server
uvicorn api.server:app --reload --port 8000
```

The API is now available at `http://localhost:8000`.
Interactive docs: `http://localhost:8000/docs`

### 3. Frontend

```bash
cd web
npm install
npm run dev
```

The frontend is now available at `http://localhost:3000`.

### 4. Ollama (optional — local models)

```bash
# Install Ollama: https://ollama.com
ollama pull llama3
ollama pull mistral
ollama pull phi3

# Set the URL in .env
OLLAMA_URL=http://localhost:11434
```

### Docker (alternative)

```bash
# Start MongoDB + Ollama via Docker Compose (if docker-compose.yml present)
docker compose up mongo ollama -d

# Then run backend and frontend as above, or:
docker compose up
```

---

## Configuration Reference

All configuration is via environment variables. Copy `.env` and fill in values.

### Required

| Variable | Description |
|---|---|
| `MONGO_URL` | MongoDB connection string (`mongodb://localhost:27017`) |

### LLM Keys

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic API key (Claude) |
| `GEMINI_API_KEY` | Google AI Studio key (Gemini) |
| `BRAVE_API_KEY` | Brave Search API key (optional, falls back to DuckDuckGo) |
| `OLLAMA_URL` | Ollama base URL (default: `http://localhost:11434`) |

### API & Security

| Variable | Default | Description |
|---|---|---|
| `API_KEY` | `""` | Bearer token for API auth (disabled if empty) |
| `RATE_LIMIT_RPM` | `60` | Requests per minute per client |
| `MAX_REQUEST_BODY_BYTES` | `2097152` | 2 MB request body limit |
| `MAX_CONCURRENT_HEAVY` | `5` | Semaphore cap for expensive endpoints |
| `ALLOWED_ORIGINS` | `localhost:3000,...` | CORS allowed origins (comma-separated) |
| `PII_REDACTION` | `false` | Enable PII redaction middleware |
| `OTEL_ENABLED` | `false` | Enable OpenTelemetry tracing |

### Behaviour

| Variable | Default | Description |
|---|---|---|
| `DEFAULT_MODEL` | `claude` | Default LLM when not specified |
| `COST_BUDGET_USD` | `0` | Daily USD spend cap (0 = disabled) |
| `MAX_TOOL_CALLS_PER_TURN` | `10` | Tool call budget per agent turn |
| `SUMMARIZE_THRESHOLD` | `16` | Message count before auto-summarization |
| `SLOW_REQUEST_MS` | `1000` | Log warning for requests slower than this |
| `SESSION_ARCHIVE_DAYS` | `30` | Auto-archive sessions older than N days |
| `SESSION_TTL_DAYS` | — | Hard-delete sessions after N days (MongoDB TTL) |
| `ANALYTICS_TTL_DAYS` | `90` | Analytics data retention |
| `CB_STATE_FILE` | — | Path to persist circuit breaker state across restarts |
| `MODEL_RPM_LIMITS` | `{}` | JSON map of per-model RPM limits |
| `STREAM` | `true` | Enable streaming responses |
| `MAX_SESSIONS` | `200` | Maximum concurrent sessions in memory |

### Server

| Variable | Default | Description |
|---|---|---|
| `API_HOST` | `0.0.0.0` | API bind host |
| `API_PORT` | `8000` | API bind port |

---

## Testing

```bash
# All tests
python3 -m pytest

# Unit tests only
python3 -m pytest tests/unit/ -v

# Integration tests only
python3 -m pytest tests/integration/test_api.py -v

# With coverage report
python3 -m pytest --cov=. --cov-report=term-missing

# Watch mode (re-run on file change)
python3 -m pytest-watch

# Mutation testing
mutmut run
mutmut results
```

Test suite: **250 passing** (196 unit + 54 integration). Uses `pytest-asyncio` in strict mode.

### Load Testing

```bash
# Install Locust
pip install locust

# Run load test (requires running server)
locust -f locustfile.py --host=http://localhost:8000
```

Scenarios: `ChatUser`, `StreamUser`, `FanOutUser`, `WsUser`.

### Linting & Type Checking

```bash
# Ruff (fast linter + formatter)
ruff check .
ruff format .

# Mypy
mypy .

# Pre-commit (runs ruff + mypy on staged files)
pre-commit run --all-files
```
