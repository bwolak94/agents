# 🤖 Agent System

Multi-LLM agentic system with intelligent routing.
**Claude** (Anthropic) · **Gemini** (Google) · **Ollama** (local models)

## Architecture

```
Your request
      │
      ▼
┌─────────────────────────────────┐
│    ROUTER AGENT (Claude Haiku)  │  ← analyses the task
│    Decides: model + agent       │
└──────────────┬──────────────────┘
               │
       ┌───────┴────────┐
       ▼                ▼
  Selected LLM      Tools
  claude/gemini     web_search
  ollama/llama3     code_exec
  ollama/mistral    file_read
                    shell
       │
       ▼
┌─────────────────────┐
│  Selected Agent     │
│  code / research    │
│  learn / file /     │
│  general            │
└─────────────────────┘
```

## Quick Start

### 1. Clone and configure

```bash
git clone <repo>
cd agent-system
cp .env.example .env
# Fill in your API keys in .env
```

### 2. Start Docker

```bash
docker compose up -d
```

This starts:
- **API** on port `8000` (FastAPI)
- **Web UI** on port `3000` (Next.js)
- **SearXNG** on port `8888` (self-hosted search)
- **MongoDB** on port `27017` (chat history)
- **Ollama** on port `11434` (local models)

### 3. CLI (terminal)

```bash
# Run inside the container
docker exec -it agent-api python cli/main.py

# Or locally (without Docker):
pip install -r requirements.txt
python cli/main.py
```

### 4. Pull Ollama models

```bash
# Via Docker
docker exec agent-ollama ollama pull llama3
docker exec agent-ollama ollama pull mistral
docker exec agent-ollama ollama pull phi3

# Or locally
ollama pull llama3
```

## CLI Usage

```
You [1]> Write a Python function to sort a dictionary by values
🔍 Analysing task...
╭─ Routing Decision ──────────────────────────╮
│ Model: claude  Agent: 💻 code_agent         │
│ Tools: none    Complexity: medium           │
│ Reasoning: Code generation task            │
╰─────────────────────────────────────────────╯

You [2]> Find the latest news about GPT-5
→ Model: claude, Agent: research_agent, Tools: web_search

You [3]> /clear     # clear history
You [4]> /models    # list available models
You [5]> /stats     # session statistics
You [6]> /exit
```

## REST API

```bash
# Chat
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Write quicksort in Python"}'

# Response:
{
  "response": "...",
  "model_used": "claude",
  "agent_used": "code_agent",
  "tools_used": [],
  "reasoning": "Code generation task"
}

# Clear history
curl -X DELETE http://localhost:8000/history/default

# List models
curl http://localhost:8000/models

# List sessions
curl http://localhost:8000/sessions
```

## Models and when they are used

| Model | Use case |
|-------|----------|
| `claude` | Complex code, analysis, long documents |
| `claude-haiku` | Simple questions, routing decisions |
| `gemini` | Research, multimodal, fast answers |
| `ollama/llama3` | General offline tasks |
| `ollama/mistral` | Offline code, technical tasks |
| `ollama/phi3` | Fast, lightweight offline tasks |

## Extending the system

### Add a new LLM

In `llm/manager.py` add a new client class and handle it in `call()`.

### Add a new agent

In `agents/agents.py` add a class inheriting from `BaseAgent`,
implement `system_prompt`, and register it in `get_agent()`.

### Add a new tool

In `tools/tools.py` add a class with method `async def run(self, message: str) -> str`
and register it in `ToolsManager._tools`.

## Project structure

```
agent-system/
├── core/
│   ├── router.py        # Router — decides which model/agent to use
│   ├── orchestrator.py  # Main engine
│   └── events.py        # WebSocket event bus
├── agents/
│   └── agents.py        # Specialist agents
├── llm/
│   └── manager.py       # Clients: Claude, Gemini, Ollama
├── tools/
│   └── tools.py         # Tools: WebSearch, CodeExec, File, Shell
├── api/
│   └── server.py        # FastAPI REST API + WebSocket
├── cli/
│   └── main.py          # CLI terminal UI
├── web/
│   └── app/page.js      # Next.js Web UI (pixel-art game world)
├── db/
│   └── history.py       # MongoDB chat history
├── config/
│   └── settings.py      # Configuration loader
├── searxng/
│   └── settings.yml     # SearXNG self-hosted search config
├── docker/
│   ├── Dockerfile.api
│   └── Dockerfile.web
├── docker-compose.yml
├── requirements.txt
└── .env.example
```
