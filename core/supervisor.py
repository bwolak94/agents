"""
Supervisor Agent — meta-agent that dynamically orchestrates sub-agents.

The supervisor:
1. Decomposes the user task into subtasks
2. Assigns each subtask to the best-capable sub-agent
3. Collects results and synthesizes a final response
4. Supports iterative refinement (sub-agent asks supervisor for clarification)
"""
import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Task decomposition prompt
_DECOMPOSE_PROMPT = """You are a supervisor orchestrating specialized AI agents.

Given the user request, decompose it into a list of subtasks and assign each
to the most appropriate agent. Available agents: {agents}

User request: {message}

Respond with ONLY valid JSON in this format:
{{
  "subtasks": [
    {{"task": "...", "agent": "agent_name", "depends_on": []}},
    {{"task": "...", "agent": "agent_name", "depends_on": ["subtask_0"]}},
    ...
  ],
  "synthesis_strategy": "merge" | "chain" | "vote"
}}

synthesis_strategy:
  merge  — combine all results into one coherent answer
  chain  — result of each task feeds into the next
  vote   — use majority/best answer from multiple attempts
"""

_SYNTHESIS_PROMPT = """You are synthesizing results from multiple specialized agents.

Strategy: {strategy}

User request: {original_message}

Agent results:
{results}

Write a single, coherent, comprehensive response that integrates all results.
"""


class SupervisorAgent:
    """
    Meta-agent that uses the LLM to decompose tasks and route to sub-agents.
    """

    def __init__(self, orchestrator, model: str = "") -> None:
        self._orch = orchestrator
        self._model = model or "claude"

    async def run(self, message: str, session_id: str = "supervisor") -> str:
        """Full supervisor run: decompose → delegate → synthesize."""
        agent_names = list(self._orch._agent_cache.keys()) or [
            "general_agent", "code_agent", "research_agent",
            "data_agent", "document_agent",
        ]

        plan = await self._decompose(message, agent_names)
        if not plan:
            # Fallback to direct processing
            return await self._orch.process(message=message, session_id=session_id)

        subtasks = plan.get("subtasks", [])
        strategy = plan.get("synthesis_strategy", "merge")

        results: dict[str, str] = {}
        completed: set[str] = set()

        # Topological execution (respect depends_on)
        max_rounds = len(subtasks) + 2
        for _ in range(max_rounds):
            ready = [
                (i, st) for i, st in enumerate(subtasks)
                if f"subtask_{i}" not in completed
                and all(dep in completed for dep in st.get("depends_on", []))
            ]
            if not ready:
                break

            async def _run_one(idx: int, subtask: dict) -> tuple[str, str]:
                agent = subtask.get("agent", "general_agent")
                task_msg = subtask["task"]
                # Inject prior results if chain strategy
                if strategy == "chain" and results:
                    last = list(results.values())[-1]
                    task_msg = f"{task_msg}\n\nContext from previous step:\n{last}"
                try:
                    resp = await self._orch.process(
                        message=task_msg,
                        session_id=f"{session_id}_sub{idx}",
                        agent_override=agent,
                    )
                except Exception as exc:
                    resp = f"[Error in {agent}: {exc}]"
                return f"subtask_{idx}", resp

            batch = await asyncio.gather(*[_run_one(i, st) for i, st in ready])
            for key, resp in batch:
                results[key] = resp
                completed.add(key)

        return await self._synthesize(message, results, strategy)

    async def _decompose(self, message: str, agent_names: list[str]) -> dict | None:
        prompt = _DECOMPOSE_PROMPT.format(
            agents=", ".join(agent_names),
            message=message,
        )
        try:
            raw = await self._orch.llm.call(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1024,
                temperature=0.2,
            )
            # Extract JSON from possible markdown fence
            import re
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                return json.loads(m.group())
        except Exception as exc:
            logger.warning("Task decomposition failed: %s", exc)
        return None

    async def _synthesize(self, original: str, results: dict[str, str],
                           strategy: str) -> str:
        results_text = "\n\n".join(
            f"[{k}]: {v}" for k, v in results.items()
        )
        prompt = _SYNTHESIS_PROMPT.format(
            strategy=strategy,
            original_message=original,
            results=results_text,
        )
        try:
            return await self._orch.llm.call(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2048,
            )
        except Exception as exc:
            logger.error("Synthesis failed: %s", exc)
            return results_text
