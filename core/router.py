"""
Router Agent — analyses the task and decides: model, agent, tools.
Now context-aware (uses recent history) and returns a fallback model chain.
"""
import json
import re
from dataclasses import dataclass, field

ROUTER_SYSTEM_PROMPT = """You are the routing agent of a multi-LLM system. Analyse the request and return ONLY valid JSON.

Models (choose based on complexity and task):
- "claude-haiku" — low complexity: simple questions, short texts, quick answers
- "claude"       — medium/high complexity: code, analysis, long documents, deep reasoning
- "gemini"       — images, multimodal, vision tasks
- "ollama/llama3"  — offline, private data, no internet needed
- "ollama/mistral" — offline code tasks
- "ollama/phi3"    — very simple offline questions

Agents:
- "code_agent"     — code writing, debugging, refactoring
- "research_agent" — web search, source analysis, fact-checking
- "learn_agent"    — learning, explanations, quizzes, teaching
- "file_agent"     — files, documents, data extraction
- "general_agent"  — everything else

Tools (select only what's needed):
- "web_search"   — internet search
- "code_exec"    — Python sandbox execution
- "file_read"    — disk file access
- "file_write"   — write to disk
- "shell"        — shell commands (use with caution)
- "memory_read"  — read agent's stored memory
- "memory_write" — persist a fact to memory
- "agent_call"   — delegate sub-task to another agent

For complex tasks that should run in parallel, set "parallel_tasks" (max 3 subtasks).

Return ONLY JSON — no prose, no markdown fences:
{
  "model": "...",
  "fallback_models": ["..."],
  "agent": "...",
  "tools": [],
  "reasoning": "...",
  "task_type": "coding|research|learning|file|general",
  "complexity": "low|medium|high",
  "needs_internet": false,
  "parallel_tasks": null
}

parallel_tasks example (only when task has independent sub-parts):
"parallel_tasks": [
  {"agent": "research_agent", "task": "...", "model": "claude"},
  {"agent": "code_agent", "task": "...", "model": "claude"}
]"""

# Fallback chains per model
MODEL_FALLBACKS: dict[str, list[str]] = {
    "claude":           ["gemini", "ollama/llama3"],
    "claude-haiku":     ["claude", "gemini", "ollama/phi3"],
    "gemini":           ["claude", "ollama/llama3"],
    "ollama/llama3":    ["ollama/mistral", "claude-haiku"],
    "ollama/mistral":   ["ollama/llama3", "claude-haiku"],
    "ollama/phi3":      ["ollama/llama3", "claude-haiku"],
}

_SEARCH_RE = re.compile(
    r"\b(search|find|look up|google|news|latest|today|yesterday|twitter|instagram|current events)\b",
    re.IGNORECASE,
)
_CODE_RE = re.compile(
    r"\b(code|write|implement|debug|error|python|javascript|typescript|function|class|def |import|fix|refactor|bug)\b",
    re.IGNORECASE,
)
_LEARN_RE = re.compile(
    r"\b(explain|what is|how does|teach|learn|quiz|tutorial|example|understand|concept)\b",
    re.IGNORECASE,
)
_FILE_RE = re.compile(
    r"\b(file|read|open|csv|json|txt|pdf|yaml|yml|document|upload)\b",
    re.IGNORECASE,
)


@dataclass
class RouterDecision:
    model: str
    agent: str
    tools: list[str]
    reasoning: str
    task_type: str
    complexity: str
    needs_internet: bool
    fallback_models: list[str] = field(default_factory=list)
    parallel_tasks: list[dict] | None = None


class RouterAgent:
    def __init__(self, llm_manager):
        self.llm = llm_manager

    def _heuristic_route(self, message: str) -> RouterDecision:
        """Keyword-based fallback routing when LLM returns invalid JSON."""
        if _SEARCH_RE.search(message):
            return RouterDecision(
                model="claude", fallback_models=["gemini", "ollama/llama3"],
                agent="research_agent", tools=["web_search"],
                reasoning="heuristic: search/news query",
                task_type="research", complexity="medium", needs_internet=True,
            )
        if _CODE_RE.search(message):
            return RouterDecision(
                model="claude", fallback_models=["ollama/mistral"],
                agent="code_agent", tools=[],
                reasoning="heuristic: code-related query",
                task_type="coding", complexity="medium", needs_internet=False,
            )
        if _LEARN_RE.search(message):
            return RouterDecision(
                model="claude", fallback_models=["gemini", "ollama/llama3"],
                agent="learn_agent", tools=[],
                reasoning="heuristic: educational query",
                task_type="learning", complexity="medium", needs_internet=False,
            )
        if _FILE_RE.search(message):
            return RouterDecision(
                model="claude", fallback_models=["ollama/llama3"],
                agent="file_agent", tools=["file_read"],
                reasoning="heuristic: file operation query",
                task_type="file", complexity="low", needs_internet=False,
            )
        return RouterDecision(
            model="claude-haiku", fallback_models=["ollama/phi3"],
            agent="general_agent", tools=[],
            reasoning="heuristic: general query",
            task_type="general", complexity="low", needs_internet=False,
        )

    def _build_router_prompt(self, user_message: str, context: list | None) -> str:
        """Build the routing prompt, including last 4 turns of context (#29)."""
        parts = []
        if context:
            recent = context[-8:]  # last 4 turns (user+assistant pairs)
            if recent:
                parts.append("<recent_conversation>")
                for msg in recent:
                    role = msg.get("role", "user")
                    content = str(msg.get("content", ""))[:300]
                    parts.append(f"{role}: {content}")
                parts.append("</recent_conversation>\n")
        parts.append(f"<current_request>{user_message}</current_request>")
        return "\n".join(parts)

    async def route(self, user_message: str, context: list | None = None) -> RouterDecision:
        """Analyse the message and return a routing decision."""
        prompt = self._build_router_prompt(user_message, context)
        messages = [{"role": "user", "content": prompt}]

        try:
            response = await self.llm.call(
                model="claude-haiku",
                messages=messages,
                system_prompt=ROUTER_SYSTEM_PROMPT,
                max_tokens=512,
                temperature=0.1,
            )
        except Exception:
            return self._heuristic_route(user_message)

        try:
            text = response.strip()
            text = re.sub(r"```(?:json)?\s*", "", text).strip()
            json_match = re.search(r"\{.*\}", text, re.DOTALL)
            if json_match:
                text = json_match.group(0)
            data = json.loads(text)

            model = data.get("model", "claude")
            fallbacks = data.get("fallback_models") or MODEL_FALLBACKS.get(model, [])

            return RouterDecision(
                model=model,
                fallback_models=fallbacks,
                agent=data.get("agent", "general_agent"),
                tools=data.get("tools", []),
                reasoning=data.get("reasoning", ""),
                task_type=data.get("task_type", "general"),
                complexity=data.get("complexity", "medium"),
                needs_internet=data.get("needs_internet", False),
                parallel_tasks=data.get("parallel_tasks"),
            )
        except (json.JSONDecodeError, KeyError):
            return self._heuristic_route(user_message)
