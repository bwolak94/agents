"""
Router Agent - the brain of the system.
Analyses the task and decides: which LLM, which agent, which tools.
"""
import json
import re
from typing import Optional
from dataclasses import dataclass

ROUTER_SYSTEM_PROMPT = """You are the routing agent of a multi-LLM system. Analyse the request and return ONLY JSON.

Models (choose based on complexity):
- "claude-haiku" - low complexity: simple questions, short texts, quick answers
- "claude" - medium/high complexity: code, analysis, long documents, reasoning
- "gemini" - images, multimodal, research
- "ollama/llama3" - offline, private data
- "ollama/mistral" - offline code tasks
- "ollama/phi3" - very simple offline questions

Agents:
- "code_agent" - code, debugging, refactoring
- "research_agent" - web search, source analysis
- "learn_agent" - learning, explanations, quizzes
- "file_agent" - files, documents
- "general_agent" - everything else

Tools:
- "web_search" - internet search
- "code_exec" - Python/JS sandbox
- "file_read" / "file_write" - disk access
- "shell" - shell commands (use with caution)

Format (ONLY JSON, no extra text):
{"model":"...","agent":"...","tools":[],"reasoning":"...","task_type":"coding|research|learning|file|general","complexity":"low|medium|high","needs_internet":true}"""


@dataclass
class RouterDecision:
    model: str
    agent: str
    tools: list[str]
    reasoning: str
    task_type: str
    complexity: str
    needs_internet: bool


class RouterAgent:
    def __init__(self, llm_manager):
        self.llm = llm_manager

    def _heuristic_route(self, message: str) -> RouterDecision:
        """Fallback routing based on keywords when the LLM returns invalid JSON."""
        msg = message.lower()

        search_keywords = ["wyszukaj", "znajdź", "szukaj", "search", "google", "twitter", "x.com",
                           "truth social", "instagram", "facebook", "news", "wiadomości", "aktualności",
                           "najnowsze", "dzisiaj", "wczoraj", "wpisy", "posty", "tweety"]
        code_keywords = ["kod", "napisz", "zaimplementuj", "debug", "błąd", "python", "javascript",
                         "function", "class", "import", "def ", "napraw", "refactor"]
        learn_keywords = ["wyjaśnij", "wytłumacz", "czym jest", "jak działa", "naucz", "quizz",
                          "co to", "przykład", "tutorial"]
        file_keywords = ["plik", "file", "odczytaj", "zapisz", "csv", "json", "txt", "pdf"]

        if any(k in msg for k in search_keywords):
            return RouterDecision(model="claude", agent="research_agent", tools=["web_search"],
                                  reasoning="heuristic: search or social media query",
                                  task_type="research", complexity="medium", needs_internet=True)
        if any(k in msg for k in code_keywords):
            return RouterDecision(model="claude", agent="code_agent", tools=[],
                                  reasoning="heuristic: code-related query",
                                  task_type="coding", complexity="medium", needs_internet=False)
        if any(k in msg for k in learn_keywords):
            return RouterDecision(model="claude", agent="learn_agent", tools=[],
                                  reasoning="heuristic: educational query",
                                  task_type="learning", complexity="medium", needs_internet=False)
        if any(k in msg for k in file_keywords):
            return RouterDecision(model="claude", agent="file_agent", tools=["file_read"],
                                  reasoning="heuristic: file operation query",
                                  task_type="file", complexity="low", needs_internet=False)
        return RouterDecision(model="claude-haiku", agent="general_agent", tools=[],
                              reasoning="heuristic: general query",
                              task_type="general", complexity="low", needs_internet=False)

    async def route(self, user_message: str, context: Optional[list] = None) -> RouterDecision:
        """Analyse the message and return a routing decision."""
        messages = [{"role": "user", "content": user_message}]

        # Haiku for routing: cheap, fast, sufficient for returning JSON
        response = await self.llm.call(
            model="claude-haiku",
            messages=messages,
            system_prompt=ROUTER_SYSTEM_PROMPT,
            max_tokens=256,
            temperature=0.1,
        )

        try:
            # Extract JSON from response — find the first {...} block
            text = response.strip()
            # Strip markdown backticks
            text = re.sub(r"```(?:json)?\s*", "", text).strip()
            # Find JSON object even if the model added extra text before/after
            json_match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
            if json_match:
                text = json_match.group(0)
            data = json.loads(text)

            return RouterDecision(
                model=data.get("model", "claude"),
                agent=data.get("agent", "general_agent"),
                tools=data.get("tools", []),
                reasoning=data.get("reasoning", ""),
                task_type=data.get("task_type", "general"),
                complexity=data.get("complexity", "medium"),
                needs_internet=data.get("needs_internet", False),
            )
        except (json.JSONDecodeError, KeyError):
            # Keyword-based heuristic fallback
            return self._heuristic_route(user_message)
