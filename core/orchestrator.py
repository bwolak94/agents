"""
Orchestrator - main system engine.
Connects Router → Agent → LLM → Tools into a single pipeline.
"""
import asyncio
import uuid
import time
from typing import Optional, AsyncGenerator
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from llm.manager import LLMManager
from core.router import RouterAgent, RouterDecision
from agents.agents import get_agent
from tools.tools import ToolsManager
from core.events import event_bus
from db.history import append_message

console = Console()

MAX_TOKENS_BY_COMPLEXITY = {"low": 1024, "medium": 2048, "high": 4096}
MAX_RESPONSE_IN_HISTORY = 2000  # chars — long responses won't bloat the history


class AgentOrchestrator:
    def __init__(self, config: dict):
        self.llm = LLMManager(config)
        self.router = RouterAgent(self.llm)
        self.tools = ToolsManager()
        self.conversation_history = []
        self.last_decision: Optional[RouterDecision] = None

    async def process(
        self,
        message: str,
        stream: bool = True,
        show_routing: bool = True,
        decision: Optional[RouterDecision] = None,
        session_id: str = "default",
    ) -> str:
        """
        Main method - processes a user message.

        1. Router analyses → decides which model/agent/tools to use
        2. Agent executes the task with selected tools
        3. Returns the response
        """
        agent_id = str(uuid.uuid4())[:8]
        task_preview = message[:80] + ("..." if len(message) > 80 else "")
        t_start = time.time()

        # STEP 1: Routing
        if decision is None:
            if show_routing:
                console.print("\n[dim]🔍 Analysing task...[/dim]")
            await event_bus.emit({
                "type": "routing",
                "agent_id": agent_id,
                "session_id": session_id,
                "task": task_preview,
            })
            decision = await self.router.route(message, self.conversation_history)

        self.last_decision = decision

        if show_routing:
            self._display_routing_info(decision)

        await event_bus.emit({
            "type": "agent_start",
            "agent_id": agent_id,
            "session_id": session_id,
            "agent_type": decision.agent,
            "model": decision.model,
            "task": task_preview,
            "tools": decision.tools,
            "complexity": decision.complexity,
        })

        # STEP 2: Get the appropriate agent
        agent = get_agent(decision.agent, self.llm, self.tools)

        # STEP 3: Dynamic max_tokens based on complexity
        max_tokens = MAX_TOKENS_BY_COMPLEXITY.get(decision.complexity, 2048)

        if show_routing:
            model_display = decision.model.replace("ollama/", "🦙 ")
            console.print(f"\n[cyan]💬 Response ({model_display}, max {max_tokens} tokens):[/cyan]\n")

        if decision.tools:
            await event_bus.emit({
                "type": "agent_tools",
                "agent_id": agent_id,
                "tools": decision.tools,
            })

        await event_bus.emit({"type": "agent_thinking", "agent_id": agent_id})

        response = await agent.run(
            message=message,
            model=decision.model,
            tool_names=decision.tools,
            conversation_history=self.conversation_history,
            stream=stream,
            max_tokens=max_tokens,
        )

        duration_ms = int((time.time() - t_start) * 1000)
        await event_bus.emit({
            "type": "agent_done",
            "agent_id": agent_id,
            "duration_ms": duration_ms,
        })

        # STEP 4: Save to in-memory history (truncate for LLM context window)
        self.conversation_history.append({"role": "user", "content": message})
        history_response = (
            response[:MAX_RESPONSE_IN_HISTORY] + "\n... [truncated in history]"
            if len(response) > MAX_RESPONSE_IN_HISTORY
            else response
        )
        self.conversation_history.append({"role": "assistant", "content": history_response})

        if len(self.conversation_history) > 20:
            self.conversation_history = self.conversation_history[-20:]

        # STEP 5: Save full messages to MongoDB
        try:
            await append_message(session_id, "user", message)
            await append_message(
                session_id, "assistant", response,
                model=decision.model,
                agent=decision.agent,
                tools=decision.tools,
            )
        except Exception:
            pass  # MongoDB unavailable — don't interrupt execution

        return response

    def _display_routing_info(self, decision: RouterDecision):
        """Display the router decision in a formatted panel."""
        model_colors = {
            "claude": "magenta",
            "claude-haiku": "magenta",
            "gemini": "blue",
            "ollama/llama3": "green",
            "ollama/mistral": "green",
            "ollama/phi3": "green",
        }
        color = model_colors.get(decision.model, "white")

        agent_icons = {
            "code_agent": "💻",
            "research_agent": "🔬",
            "learn_agent": "📚",
            "file_agent": "📁",
            "general_agent": "🤖",
        }
        icon = agent_icons.get(decision.agent, "🤖")

        tools_str = ", ".join(decision.tools) if decision.tools else "none"
        complexity_colors = {"low": "green", "medium": "yellow", "high": "red"}
        comp_color = complexity_colors.get(decision.complexity, "white")

        info = (
            f"[{color}]Model:[/{color}] {decision.model}  "
            f"[cyan]Agent:[/cyan] {icon} {decision.agent}  "
            f"[yellow]Tools:[/yellow] {tools_str}  "
            f"[{comp_color}]Complexity:[/{comp_color}] {decision.complexity}\n"
            f"[dim]Reasoning: {decision.reasoning}[/dim]"
        )
        console.print(Panel(info, title="[bold]🧭 Routing Decision[/bold]", border_style="dim"))

    def clear_history(self):
        """Clear the conversation history."""
        self.conversation_history = []
        console.print("[green]✓ History cleared[/green]")

    def get_stats(self) -> dict:
        """Return statistics for the current session."""
        stats = {
            "messages_in_history": len(self.conversation_history),
            "last_model": self.last_decision.model if self.last_decision else None,
            "last_agent": self.last_decision.agent if self.last_decision else None,
        }
        cost_stats = self.llm.get_cost_stats()
        if cost_stats:
            stats["costs"] = cost_stats
        return stats
