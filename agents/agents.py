"""
Specialist agents — each has a focused system prompt.
All agents share a ReAct loop: LLM decides which tool to call, sees result, repeats.

Round 4 improvements:
- Parallel tool execution (Imp 1)
- Tool result summarization >6KB (Imp 2)
- Tool call deduplication within session (Imp 3)
- Tool error auto-retry up to 2 times (Imp 4)
- ReAct step streaming via event_bus (Imp 10)
- Agent self-reflection loop (Feature 3)
- Agent memory consolidation >2000 chars (Feature 7)
- Per-agent RAG namespacing (Imp 16)
"""
import json
import re
import asyncio
import hashlib
import logging
from abc import ABC, abstractmethod

from core.events import event_bus

logger = logging.getLogger(__name__)

MAX_REACT_ITERATIONS = 6
REACT_ITERATION_TIMEOUT = 60
TOOL_RESULT_MAX_CHARS = 6_000   # summarize results larger than this (Imp 2)
TOOL_ERROR_MAX_RETRIES = 2      # auto-retry tool errors (Imp 4)
MEMORY_CONSOLIDATION_THRESHOLD = 2000  # chars before compressing memory (Feature 7)

TOOL_CALL_PATTERN = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)
MULTI_TOOL_PATTERN = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)

TOOL_DESCRIPTIONS = {
    "web_search":   "Search the internet. Args: your search query.",
    "code_exec":    "Execute Python code. Args: the code to run.",
    "file_read":    "Read a file. Args: file path or upload::id.",
    "file_write":   "Write a file. Args: JSON with 'path' and 'content'.",
    "shell":        "Run a shell command. Args: the command in backticks.",
    "memory_read":  "Read stored memory about this user. Args: (empty).",
    "memory_write": "Append a fact to memory. Args: text to remember.",
    "agent_call":   "Delegate to a specialist. Args: 'agent_name|task'.",
}


def _build_tool_instructions(tool_names: list[str]) -> str:
    if not tool_names:
        return ""
    available = [(n, TOOL_DESCRIPTIONS.get(n, n)) for n in tool_names]
    lines = [
        "\n\n<tools>",
        "When you need information or must perform an action, output a tool call:",
        "",
        "<tool_call>",
        '{"name": "tool_name", "args": "your input"}',
        "</tool_call>",
        "",
        "You may output MULTIPLE tool calls in a single response when the calls are independent.",
        "After receiving a <tool_result>, continue reasoning. When ready to answer, respond normally with no tool call block.",
        "",
        "Available tools:",
    ]
    for name, desc in available:
        lines.append(f"- {name}: {desc}")
    lines.append("</tools>")
    return "\n".join(lines)


def _parse_all_tool_calls(text: str) -> list[dict]:
    """Parse ALL tool calls from a response (supports parallel calls)."""
    matches = MULTI_TOOL_PATTERN.findall(text)
    calls = []
    for raw in matches:
        raw = raw.strip()
        try:
            calls.append(json.loads(raw))
        except json.JSONDecodeError:
            if "|" in raw:
                parts = raw.split("|", 1)
                calls.append({"name": parts[0].strip(), "args": parts[1].strip()})
    return calls


def _parse_tool_call(text: str) -> dict | None:
    """Parse single (first) tool call — used for backward compat."""
    calls = _parse_all_tool_calls(text)
    return calls[0] if calls else None


def _tool_dedup_key(tool_name: str, args) -> str:
    return hashlib.md5(f"{tool_name}|{args}".encode(), usedforsecurity=False).hexdigest()


# ─────────────────────────────────────────
# BASE AGENT
# ─────────────────────────────────────────
class BaseAgent(ABC):
    def __init__(self, llm_manager, tools_manager):
        self.llm = llm_manager
        self.tools = tools_manager

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        pass

    async def _summarize_tool_result(self, result: str, model: str) -> str:
        """Compress a large tool result using the LLM (Imp 2)."""
        try:
            summary = await asyncio.wait_for(
                self.llm.call(
                    model="claude-haiku",
                    messages=[{"role": "user", "content": f"Summarize this tool output concisely (max 500 words):\n\n{result[:8000]}"}],
                    max_tokens=700,
                    temperature=0.2,
                ),
                timeout=30,
            )
            return f"[Tool output summarized due to size]\n{summary}"
        except Exception:
            return result[:TOOL_RESULT_MAX_CHARS] + "\n... [truncated]"

    async def _consolidate_memory(self, session_id: str, agent_type: str, memory: str, model: str) -> str:
        """Compress oversized agent memory (Feature 7)."""
        try:
            compressed = await asyncio.wait_for(
                self.llm.call(
                    model="claude-haiku",
                    messages=[{"role": "user", "content": f"Compress this agent memory into the most important facts (max 300 words):\n\n{memory}"}],
                    max_tokens=400,
                    temperature=0.2,
                ),
                timeout=30,
            )
            # Persist compressed memory
            try:
                await self.tools.get("memory_write") and None  # just check it exists
                from db import memory as memory_db
                await memory_db.memory_write(session_id, agent_type, f"[consolidated]\n{compressed}")
            except Exception:
                pass
            return f"[consolidated]\n{compressed}"
        except Exception:
            return memory[:MEMORY_CONSOLIDATION_THRESHOLD]

    async def run(
        self,
        message: str,
        model: str,
        tool_names: list[str],
        conversation_history: list,
        stream: bool = False,
        max_tokens: int = 4096,
        agent_id: str = "",
        session_id: str = "",
        enable_reflection: bool = False,
        checkpoint_id: str = "",
        active_persona: str = "",
    ) -> str:
        """
        ReAct loop with round-4 improvements:
        - Parallel tool execution
        - Tool result summarization
        - Tool call deduplication
        - Tool error auto-retry
        - ReAct step streaming
        - Checkpoint save/resume
        """
        agent_type = self.__class__.__name__.lower().replace("agent", "_agent")
        system = self.system_prompt + _build_tool_instructions(tool_names)

        # Active persona injection (Imp 8) — if passed from orchestrator
        if active_persona:
            system = f"<persona>\n{active_persona}\n</persona>\n\n" + system

        messages = list(conversation_history) + [{"role": "user", "content": message}]

        # RAG auto-context with per-agent namespacing (Imp 16)
        rag_session = session_id or (agent_id.split("-")[0] if "-" in agent_id else "")
        if rag_session:
            try:
                from db.rag import search as rag_search
                chunks = await rag_search(rag_session, message, limit=3, agent_type=agent_type)
                if chunks:
                    ctx = "\n\n".join(f"[{c['title']}]\n{c['content']}" for c in chunks)
                    system = f"<context>\n{ctx}\n</context>\n\n" + system
            except Exception:
                pass

        # Checkpoint resume (Feature 6)
        tool_dedup_cache: dict[str, str] = {}
        start_iteration = 0
        if checkpoint_id and rag_session:
            try:
                from db.agent_checkpoints import load_checkpoint
                cp = await load_checkpoint(rag_session, checkpoint_id)
                if cp:
                    messages = cp["messages"]
                    tool_dedup_cache = cp.get("tool_call_cache", {})
                    start_iteration = cp.get("iteration", 0)
                    logger.info("Resumed checkpoint %s at iteration %d", checkpoint_id, start_iteration)
            except Exception:
                pass

        for iteration in range(start_iteration, MAX_REACT_ITERATIONS):
            # Emit react_step event (Imp 10)
            if agent_id:
                asyncio.create_task(event_bus.emit({
                    "type": "react_step",
                    "agent_id": agent_id,
                    "iteration": iteration,
                    "session_id": session_id,
                }))

            try:
                response = await asyncio.wait_for(
                    self.llm.call(
                        model=model,
                        messages=messages,
                        system_prompt=system,
                        stream=False,
                        max_tokens=max_tokens,
                    ),
                    timeout=REACT_ITERATION_TIMEOUT,
                )
            except asyncio.TimeoutError:
                logger.warning("Agent %s iteration %d timed out", agent_id, iteration)
                return "I'm sorry, the response timed out. Please try again."

            # Parse ALL tool calls for parallel execution (Imp 1)
            tool_calls = _parse_all_tool_calls(response)

            if not tool_calls:
                # No tool call — final answer; optionally self-reflect (Feature 3)
                if enable_reflection:
                    response = await self._self_reflect(response, message, model, max_tokens)
                return response

            # Memory consolidation check (Feature 7)
            for tc in tool_calls:
                if tc.get("name") == "memory_read" and rag_session:
                    try:
                        from db import memory as memory_db
                        mem = await memory_db.memory_read(rag_session, agent_type)
                        if mem and len(mem) > MEMORY_CONSOLIDATION_THRESHOLD:
                            mem = await self._consolidate_memory(rag_session, agent_type, mem, model)
                    except Exception:
                        pass

            # Execute tool calls — parallel for multiple (Imp 1)
            async def _execute_single(tc: dict) -> tuple[str, str]:
                tool_name = tc.get("name", "")
                tool_args = tc.get("args", "")

                # Deduplication (Imp 3)
                dedup_key = _tool_dedup_key(tool_name, tool_args)
                if dedup_key in tool_dedup_cache:
                    return tool_name, f"[cached]\n{tool_dedup_cache[dedup_key]}"

                tool = self.tools.get(tool_name)
                if tool is None:
                    return tool_name, f"Unknown tool: {tool_name}"

                if agent_id:
                    asyncio.create_task(event_bus.emit({
                        "type": "agent_tools",
                        "agent_id": agent_id,
                        "tools": [tool_name],
                    }))

                # Cross-request cache for idempotent tools (web_search, file_read)
                from tools.tools import _cache_get, _cache_put
                cached_result = _cache_get(tool_name, tool_args)
                if cached_result is not None:
                    tool_dedup_cache[dedup_key] = cached_result
                    return tool_name, cached_result

                # Error auto-retry (Imp 4)
                last_error = None
                for attempt in range(TOOL_ERROR_MAX_RETRIES + 1):
                    try:
                        result = await tool.run(tool_args)
                        # Summarize if too large (Imp 2)
                        if len(str(result)) > TOOL_RESULT_MAX_CHARS:
                            result = await self._summarize_tool_result(str(result), model)
                        _cache_put(tool_name, tool_args, str(result))
                        tool_dedup_cache[dedup_key] = str(result)
                        return tool_name, result
                    except Exception as e:
                        last_error = e
                        if attempt < TOOL_ERROR_MAX_RETRIES:
                            logger.warning("Tool %s attempt %d failed: %s — retrying", tool_name, attempt + 1, e)
                            await asyncio.sleep(0.5 * (attempt + 1))

                return tool_name, f"Tool error [{tool_name}] after {TOOL_ERROR_MAX_RETRIES} retries: {last_error}"

            if len(tool_calls) == 1:
                tool_name, tool_result = await _execute_single(tool_calls[0])
                tool_results = [(tool_name, tool_result)]
            else:
                # Parallel execution (Imp 1)
                tool_results = await asyncio.gather(*[_execute_single(tc) for tc in tool_calls])

            # Checkpoint save (Feature 6)
            if checkpoint_id and rag_session:
                try:
                    from db.agent_checkpoints import save_checkpoint
                    await save_checkpoint(
                        session_id=rag_session,
                        checkpoint_id=checkpoint_id,
                        messages=messages,
                        tool_call_cache=tool_dedup_cache,
                        iteration=iteration + 1,
                        agent_name=self.__class__.__name__,
                        model=model,
                    )
                except Exception:
                    pass

            # Append response + all tool results to message history
            messages.append({"role": "assistant", "content": response})
            combined_results = "\n\n".join(
                f"<tool_result name='{name}'>\n{result}\n</tool_result>"
                for name, result in tool_results
            )
            messages.append({"role": "user", "content": combined_results})

        # Max iterations reached — ask for final answer
        messages.append({
            "role": "user",
            "content": "Please provide your final answer now based on everything above.",
        })
        try:
            return await asyncio.wait_for(
                self.llm.call(
                    model=model,
                    messages=messages,
                    system_prompt=system,
                    stream=False,
                    max_tokens=max_tokens,
                ),
                timeout=REACT_ITERATION_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning("Agent %s final synthesis timed out", agent_id)
            return "I'm sorry, the response timed out. Please try again."

    async def _self_reflect(self, response: str, original_message: str, model: str, max_tokens: int) -> str:
        """Self-reflection: agent critiques its response and optionally revises (Feature 3)."""
        try:
            reflection_prompt = (
                f"You just produced this response:\n\n{response}\n\n"
                f"Original question: {original_message}\n\n"
                "Critically evaluate: Is the response accurate, complete, and well-structured? "
                "If it is good enough, reply 'APPROVED'. "
                "If it needs improvement, reply with a revised, improved version only (no preamble)."
            )
            reflection = await asyncio.wait_for(
                self.llm.call(
                    model=model,
                    messages=[{"role": "user", "content": reflection_prompt}],
                    max_tokens=max_tokens,
                    temperature=0.3,
                ),
                timeout=REACT_ITERATION_TIMEOUT,
            )
            if reflection.strip().upper().startswith("APPROVED"):
                return response
            return reflection
        except Exception:
            return response


# ─────────────────────────────────────────
# SPECIALIST AGENTS
# ─────────────────────────────────────────
class CodeAgent(BaseAgent):
    @property
    def system_prompt(self) -> str:
        return """<role>
You are a senior software engineer with 15+ years of experience across multiple languages and paradigms.
You write production-ready code that is correct, efficient, secure, and maintainable.
</role>

<capabilities>
- Design and implement algorithms, data structures, APIs, and full systems
- Debug complex issues by reasoning through stack traces and execution flow step-by-step
- Refactor legacy code while preserving behaviour and improving readability
- Identify security vulnerabilities (OWASP Top 10, injection, auth flaws, data exposure)
- Optimise for performance, memory, and scalability
- Write and review tests (unit, integration, e2e)
- Execute code and analyse the output provided in <tool_result>
</capabilities>

<instructions>
1. THINK BEFORE YOU CODE: Briefly state your approach before writing any code.
2. Always provide complete, runnable code — never truncate with "..." or "rest of the code".
3. Use the language the user specifies or infer it from context. Default to Python if ambiguous.
4. Add type annotations, meaningful variable names, and inline comments for non-obvious logic.
5. After writing code, explain: what it does, edge cases handled, and potential failure modes.
6. When debugging: pinpoint the exact file, line number, and root cause. Propose a minimal fix first.
7. If <tool_result> contains code execution output, analyse it carefully.
8. Warn explicitly about: security risks, race conditions, resource leaks, or breaking changes.
</instructions>

<constraints>
- Never fabricate library APIs or function signatures.
- Do not write code that is intentionally harmful, insecure, or unethical.
- Do not ignore error handling.
- Never suggest "just disable the linter" as a solution.
</constraints>"""


class ResearchAgent(BaseAgent):
    @property
    def system_prompt(self) -> str:
        return """<role>
You are an expert research analyst with deep experience in information synthesis,
source evaluation, and fact-checking.
</role>

<capabilities>
- Synthesise information from multiple sources into coherent, well-structured reports
- Critically evaluate source credibility, recency, and potential bias
- Distinguish between verified facts, expert consensus, contested claims, and speculation
- Identify gaps, contradictions, and areas of uncertainty
- Present complex topics accessibly without sacrificing accuracy
</capabilities>

<instructions>
1. PRIORITISE <tool_result>: When search results are provided, use them as your primary evidence.
2. Always state the DATE of information when known.
3. Cite sources inline using [Source: URL or title] notation.
4. Label each claim: VERIFIED / CONTESTED / REPORTED / OPINION.
5. When results are insufficient, say what is missing and why.
6. Do not fill gaps with hallucinated details.
</instructions>

<constraints>
- Never fabricate quotes, statistics, or source URLs.
- Never present opinion as fact.
- Do not omit contradictory evidence.
</constraints>"""


class LearnAgent(BaseAgent):
    @property
    def system_prompt(self) -> str:
        return """<role>
You are a world-class educator and learning coach — patient, encouraging, and deeply knowledgeable.
You use the Socratic method, spaced repetition principles, and the Feynman technique to make any concept stick.
</role>

<capabilities>
- Explain any concept from first principles, building from the simple to the complex
- Detect the learner's level from their vocabulary and calibrate accordingly
- Create analogies, metaphors, and real-world examples to make abstract ideas tangible
- Generate flashcards, quizzes, mind maps, and step-by-step learning plans
</capabilities>

<instructions>
1. LEVEL DETECTION: Adjust vocabulary — simpler for beginners, technical for experts.
2. EXPLAIN, DON'T JUST DEFINE: Always follow definitions with a concrete analogy and example.
3. USE THE FEYNMAN TECHNIQUE: Explain as if teaching a smart 12-year-old, then build up.
4. CHECK UNDERSTANDING: End explanations with 1-2 comprehension questions.
5. CORRECT MISCONCEPTIONS: Address misunderstandings before answering.
6. ENCOURAGE: Acknowledge effort, normalise confusion, celebrate progress.
</instructions>

<constraints>
- Never skip steps assuming "the user will figure it out".
- Do not use jargon without immediately defining it.
- Do not just give the answer to exercises — guide the user to discover it.
</constraints>"""


class FileAgent(BaseAgent):
    @property
    def system_prompt(self) -> str:
        return """<role>
You are an expert document analyst and data extraction specialist.
You process files of any type with precision and produce clear, actionable summaries.
</role>

<capabilities>
- Analyse and summarise documents: PDF, Markdown, JSON, CSV, XML, YAML, plain text, logs, configs
- Extract structured data: tables, key-value pairs, named entities, dates, figures
- Compare multiple documents and highlight differences, conflicts, or overlaps
- Detect file issues: encoding errors, malformed structures, missing fields, truncation
- Identify sensitive data exposure (PII, API keys, passwords)
</capabilities>

<instructions>
1. ALWAYS READ FILE CONTENT from <tool_result> before responding.
2. START WITH A FILE PROFILE: state format, encoding, size, and structure.
3. FLAG IMMEDIATELY: encoding issues, truncation, sensitive data, schema violations.
4. For configuration files: explain what each section does in plain language.
</instructions>

<constraints>
- Never fabricate or infer file content not in <tool_result>.
- Do not expose sensitive data verbatim.
- If format is unclear, say so — do not guess.
</constraints>"""


class GeneralAgent(BaseAgent):
    @property
    def system_prompt(self) -> str:
        return """<role>
You are a highly capable, versatile AI assistant. You are direct, honest, and intellectually curious.
</role>

<capabilities>
- Answer questions across all domains: science, history, culture, technology, philosophy, daily life
- Reason through complex problems step-by-step
- Help plan, brainstorm, draft, and revise any type of content
- Perform calculations, logical deductions, and structured analysis
- Adapt tone from casual chat to formal professional communication
</capabilities>

<instructions>
1. LANGUAGE: Respond in the same language the user writes in.
2. CALIBRATE LENGTH: Match response length to complexity.
3. BE DIRECT: Lead with the answer, then provide supporting context.
4. ADMIT UNCERTAINTY: Use "I believe..." or "You should verify..." when unsure.
5. THINK STEP BY STEP for multi-part or complex questions.
6. AVOID: Unnecessary disclaimers, excessive hedging, repetitive affirmations.
</instructions>

<constraints>
- Never fabricate facts, statistics, names, or citations.
- Do not repeat the user's question back before answering.
- Do not refuse reasonable requests due to overcaution.
</constraints>"""


class DocumentAgent(BaseAgent):
    """Dedicated RAG/Document Q&A agent (Feature 10)."""
    @property
    def system_prompt(self) -> str:
        return """<role>
You are a precise document Q&A specialist. You answer questions exclusively from the provided context.
</role>

<instructions>
1. ONLY use information from the <context> section provided in the system prompt.
2. If the answer is not in the context, say "This information is not in the provided documents."
3. Cite the document title for every claim: [Source: title].
4. Be concise — answer the question directly, then quote the supporting passage.
5. Never hallucinate content beyond what is in the context.
</instructions>"""


# ─────────────────────────────────────────
# PLANNER AGENT
# ─────────────────────────────────────────
class PlannerAgent(BaseAgent):
    @property
    def system_prompt(self) -> str:
        return """<role>
You are an expert project planner and task decomposer.
</role>

<capabilities>
- Break complex goals into clear, ordered steps
- Identify dependencies and parallelisable work
- Estimate effort and flag risks for each step
- Delegate steps to the right specialist agents
</capabilities>

<instructions>
1. DECOMPOSE: Split the user's goal into numbered steps.
2. LABEL: Mark each step with [code], [research], [file], or [general].
3. DEPENDENCIES: Note which steps must complete before others.
4. EXECUTE: For each step, delegate via agent_call or perform it directly.
5. SUMMARISE: End with a concise summary of what was accomplished.
</instructions>

<constraints>
- Do not skip steps.
- Always confirm your plan before executing when the task is complex.
</constraints>"""

    async def run(
        self,
        message: str,
        model: str,
        tool_names: list[str],
        conversation_history: list,
        stream: bool = False,
        max_tokens: int = 4096,
        agent_id: str = "",
        session_id: str = "",
        enable_reflection: bool = False,
        checkpoint_id: str = "",
        active_persona: str = "",
    ) -> str:
        if agent_id:
            await event_bus.emit({
                "type": "plan_start",
                "agent_id": agent_id,
                "message": message[:200],
            })
        result = await super().run(
            message, model, tool_names, conversation_history, stream, max_tokens,
            agent_id, session_id, enable_reflection, checkpoint_id, active_persona,
        )
        if agent_id:
            await event_bus.emit({
                "type": "plan_done",
                "agent_id": agent_id,
            })
        return result


# ─────────────────────────────────────────
# AGENT REGISTRY
# ─────────────────────────────────────────
AGENT_REGISTRY: dict[str, type[BaseAgent]] = {
    "code_agent":     CodeAgent,
    "research_agent": ResearchAgent,
    "learn_agent":    LearnAgent,
    "file_agent":     FileAgent,
    "general_agent":  GeneralAgent,
    "planner_agent":  PlannerAgent,
    "document_agent": DocumentAgent,
}

# In-memory overrides for system prompts (Imp 18)
_system_prompt_overrides: dict[str, str] = {}


def set_agent_system_prompt(agent_name: str, system_prompt: str) -> None:
    _system_prompt_overrides[agent_name] = system_prompt


def get_agent_system_prompt_override(agent_name: str) -> str | None:
    return _system_prompt_overrides.get(agent_name)


def get_agent(agent_name: str, llm_manager, tools_manager) -> "BaseAgent":
    cls = AGENT_REGISTRY.get(agent_name, GeneralAgent)

    # Apply system prompt override if present (Imp 18)
    override = _system_prompt_overrides.get(agent_name)
    if override:
        # Dynamically subclass to inject the override
        class _OverriddenAgent(cls):  # type: ignore[valid-type]
            @property
            def system_prompt(self) -> str:
                return override
        return _OverriddenAgent(llm_manager, tools_manager)

    return cls(llm_manager, tools_manager)
