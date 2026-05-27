"""
Orchestrator — Router -> Agent -> LLM -> Tools pipeline.
Supports: parallel agents, model fallback chain, history summarization, agent collaboration.
"""
import asyncio
import uuid
import time
import logging
from typing import Optional
from rich.console import Console
from rich.panel import Panel

from llm.manager import LLMManager
from core.router import RouterAgent, RouterDecision
from agents.agents import get_agent, BaseAgent
from tools.tools import ToolsManager
from core.events import event_bus
from db.history import append_message

console = Console()
logger = logging.getLogger(__name__)

MAX_TOKENS_BY_COMPLEXITY = {"low": 1024, "medium": 2048, "high": 4096}
MAX_RESPONSE_IN_HISTORY = 2000
HISTORY_WINDOW = 20          # messages kept in sliding window
SUMMARIZE_THRESHOLD = 16     # summarize when history exceeds this
MAX_PARALLEL_SUBTASKS = 3

SUMMARIZE_PROMPT = """Summarize the conversation so far in 3-5 concise bullet points.
Capture: the user's goals, key decisions made, important facts learned, and any ongoing context.
Output ONLY the bullet points — no preamble."""


class AgentOrchestrator:
    def __init__(self, config: dict):
        self.llm = LLMManager(config)
        self.router = RouterAgent(self.llm)
        self.tools = ToolsManager()
        self.conversation_history: list[dict] = []
        self.last_decision: Optional[RouterDecision] = None
        self._current_session_id: str = "default"

        # #15 — reuse stateless agent instances within this orchestrator
        self._agent_cache: dict[str, BaseAgent] = {}

        # Register agent_call tool with self as parent
        from tools.tools import AgentCallTool
        self.tools.register("agent_call", AgentCallTool(self))

    # ─────────────────────────────────────────
    # PUBLIC: main entry point
    # ─────────────────────────────────────────
    async def process(
        self,
        message: str,
        stream: bool = False,
        show_routing: bool = False,
        decision: Optional[RouterDecision] = None,
        session_id: str = "default",
    ) -> str:
        self._current_session_id = session_id
        agent_id = str(uuid.uuid4())[:8]
        task_preview = message[:80] + ("..." if len(message) > 80 else "")
        t_start = time.time()

        # STEP 1: Route (with conversation context)
        if decision is None:
            asyncio.create_task(event_bus.emit({
                "type": "routing",
                "agent_id": agent_id,
                "session_id": session_id,
                "task": task_preview,
            }))
            decision = await self.router.route(message, self.conversation_history)

        self.last_decision = decision
        if show_routing:
            self._display_routing_info(decision)

        # STEP 2: Parallel subtasks (if router decided to parallelize)
        if decision.parallel_tasks:
            return await self._process_parallel(
                decision.parallel_tasks, message, session_id, agent_id, t_start
            )

        # STEP 3: Single agent execution (with fallback)
        response = await self._run_with_fallback(
            message=message,
            decision=decision,
            agent_id=agent_id,
            session_id=session_id,
        )

        duration_ms = int((time.time() - t_start) * 1000)
        asyncio.create_task(event_bus.emit({
            "type": "agent_done",
            "agent_id": agent_id,
            "session_id": session_id,
            "duration_ms": duration_ms,
        }))

        await self._update_history(session_id, message, response)
        return response

    # ─────────────────────────────────────────
    # PRIVATE: single agent run with model fallback
    # ─────────────────────────────────────────
    async def _run_with_fallback(
        self,
        message: str,
        decision: RouterDecision,
        agent_id: str,
        session_id: str,
    ) -> str:
        models_to_try = [decision.model] + (decision.fallback_models or [])

        for model in models_to_try:
            try:
                return await self._run_agent_with_events(
                    agent_name=decision.agent,
                    model=model,
                    tools=decision.tools,
                    message=message,
                    agent_id=agent_id,
                    session_id=session_id,
                    complexity=decision.complexity,
                )
            except Exception as e:
                console.print(f"[yellow]Model {model} failed: {e} — trying fallback...[/yellow]")
                continue

        # All models failed — return graceful error
        return "I'm sorry, all available models are currently unavailable. Please try again later."

    async def _run_agent_with_events(
        self,
        agent_name: str,
        model: str,
        tools: list[str],
        message: str,
        agent_id: str,
        session_id: str,
        complexity: str = "medium",
    ) -> str:
        max_tokens = MAX_TOKENS_BY_COMPLEXITY.get(complexity, 2048)

        # Configure session-aware tools (memory, agent_call)
        self.tools.configure_session_tools(
            session_id=session_id,
            agent_type=agent_name,
            parent_orchestrator=self,
        )

        asyncio.create_task(event_bus.emit({
            "type": "agent_start",
            "agent_id": agent_id,
            "session_id": session_id,
            "agent_type": agent_name,
            "model": model,
            "task": message[:80],
            "tools": tools,
            "complexity": complexity,
        }))

        asyncio.create_task(event_bus.emit({
            "type": "agent_thinking",
            "agent_id": agent_id,
            "session_id": session_id,
        }))

        # #15 — reuse cached agent instances (agents are stateless)
        agent = self._agent_cache.get(agent_name)
        if agent is None:
            agent = get_agent(agent_name, self.llm, self.tools)
            self._agent_cache[agent_name] = agent

        response = await agent.run(
            message=message,
            model=model,
            tool_names=tools,
            conversation_history=self.conversation_history,
            stream=False,
            max_tokens=max_tokens,
            agent_id=agent_id,
        )
        return response

    # ─────────────────────────────────────────
    # PRIVATE: parallel subtasks
    # ─────────────────────────────────────────
    async def _process_parallel(
        self,
        subtasks: list[dict],
        original_message: str,
        session_id: str,
        parent_agent_id: str,
        t_start: float,
    ) -> str:
        if len(subtasks) > MAX_PARALLEL_SUBTASKS:
            logger.warning(
                "Router requested %d parallel subtasks; truncating to %d",
                len(subtasks), MAX_PARALLEL_SUBTASKS,
            )
        capped = subtasks[:MAX_PARALLEL_SUBTASKS]

        async def run_subtask(subtask: dict, idx: int) -> str:
            sub_id = f"{parent_agent_id}-p{idx}"
            model = subtask.get("model", "claude")
            agent_name = subtask.get("agent", "general_agent")
            task = subtask.get("task", original_message)
            tools = subtask.get("tools", [])

            try:
                return await self._run_agent_with_events(
                    agent_name=agent_name,
                    model=model,
                    tools=tools,
                    message=task,
                    agent_id=sub_id,
                    session_id=session_id,
                )
            except Exception as e:
                return f"[{agent_name} failed: {e}]"

        results = await asyncio.gather(*[
            run_subtask(st, i) for i, st in enumerate(capped)
        ])

        # Synthesize parallel results
        synthesis_context = "\n\n".join([
            f"--- Result from {capped[i].get('agent', 'agent')} ---\n{r}"
            for i, r in enumerate(results)
        ])
        synthesis_prompt = (
            f"Based on these parallel research results, provide a unified, comprehensive answer "
            f"to the original question: '{original_message}'\n\n{synthesis_context}"
        )

        synthesis_id = f"{parent_agent_id}-synth"
        final = await self._run_agent_with_events(
            agent_name="general_agent",
            model="claude",
            tools=[],
            message=synthesis_prompt,
            agent_id=synthesis_id,
            session_id=session_id,
        )

        duration_ms = int((time.time() - t_start) * 1000)
        asyncio.create_task(event_bus.emit({
            "type": "agent_done",
            "agent_id": parent_agent_id,
            "session_id": session_id,
            "duration_ms": duration_ms,
        }))

        await self._update_history(session_id, original_message, final)
        return final

    # ─────────────────────────────────────────
    # PRIVATE: called by AgentCallTool for agent collaboration
    # ─────────────────────────────────────────
    async def _run_agent(
        self,
        agent_name: str,
        message: str,
        session_id: str = "default",
    ) -> str:
        """Run a single agent directly — used by AgentCallTool."""
        sub_id = str(uuid.uuid4())[:8]
        return await self._run_agent_with_events(
            agent_name=agent_name,
            model="claude",
            tools=[],
            message=message,
            agent_id=sub_id,
            session_id=session_id,
        )

    # ─────────────────────────────────────────
    # PRIVATE: history management
    # ─────────────────────────────────────────
    async def _update_history(self, session_id: str, user_message: str, response: str) -> None:
        """Add messages to in-memory history and persist to MongoDB. Summarize when needed."""
        self.conversation_history.append({"role": "user", "content": user_message})

        # Truncate long responses for LLM context window
        history_response = (
            response[:MAX_RESPONSE_IN_HISTORY] + "\n... [truncated]"
            if len(response) > MAX_RESPONSE_IN_HISTORY
            else response
        )
        self.conversation_history.append({"role": "assistant", "content": history_response})

        # Sliding window with summarization
        if len(self.conversation_history) > SUMMARIZE_THRESHOLD:
            await self._summarize_history()

        # Persist to MongoDB
        try:
            await append_message(session_id, "user", user_message)
            cost_stats = self.llm.get_cost_stats()
            await append_message(
                session_id, "assistant", response,
                model=self.last_decision.model if self.last_decision else "unknown",
                agent=self.last_decision.agent if self.last_decision else "unknown",
                tools=self.last_decision.tools if self.last_decision else [],
                cost_usd=cost_stats.get("total_cost_usd", 0) if cost_stats else 0,
            )
        except Exception as exc:
            # #12 — log MongoDB failures instead of silently swallowing them
            logger.warning("Failed to persist message to MongoDB: %s", exc)

    async def _summarize_history(self) -> None:
        """Replace oldest messages with a compact summary, preserving recent context."""
        to_summarize = self.conversation_history[:-6]  # keep last 3 turns
        recent = self.conversation_history[-6:]

        if not to_summarize:
            return

        summary_input = "\n".join(
            f"{m['role'].upper()}: {m['content'][:300]}" for m in to_summarize
        )

        try:
            summary = await self.llm.call(
                model="claude-haiku",
                messages=[{"role": "user", "content": summary_input}],
                system_prompt=SUMMARIZE_PROMPT,
                max_tokens=256,
                temperature=0.3,
            )
            self.conversation_history = [
                {"role": "user", "content": f"<conversation_summary>\n{summary}\n</conversation_summary>"},
                {"role": "assistant", "content": "Understood. I'll keep this context in mind."},
            ] + recent
        except Exception as exc:
            # #13 — log summarization failures, then fall back to window truncation
            logger.warning("History summarization failed, truncating instead: %s", exc)
            self.conversation_history = self.conversation_history[-HISTORY_WINDOW:]

    # ─────────────────────────────────────────
    # PUBLIC: utilities
    # ─────────────────────────────────────────
    def clear_history(self) -> None:
        self.conversation_history = []
        console.print("[green]History cleared[/green]")

    def get_stats(self) -> dict:
        stats = {
            "messages_in_history": len(self.conversation_history),
            "last_model": self.last_decision.model if self.last_decision else None,
            "last_agent": self.last_decision.agent if self.last_decision else None,
        }
        cost_stats = self.llm.get_cost_stats()
        if cost_stats:
            stats["costs"] = cost_stats
        return stats

    def _display_routing_info(self, decision: RouterDecision) -> None:
        tools_str = ", ".join(decision.tools) if decision.tools else "none"
        fallback_str = " -> ".join(decision.fallback_models) if decision.fallback_models else "none"
        info = (
            f"[magenta]Model:[/magenta] {decision.model}  "
            f"[dim]fallback:[/dim] {fallback_str}\n"
            f"[cyan]Agent:[/cyan] {decision.agent}  "
            f"[yellow]Tools:[/yellow] {tools_str}  "
            f"[green]Complexity:[/green] {decision.complexity}\n"
            f"[dim]Reasoning: {decision.reasoning}[/dim]"
        )
        console.print(Panel(info, title="[bold]Routing Decision[/bold]", border_style="dim"))
