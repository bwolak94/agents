"""
Specialist agents — each has a focused system prompt.
All agents share a ReAct loop: LLM decides which tool to call, sees result, repeats.
"""
import json
import re
import asyncio
import logging
from abc import ABC, abstractmethod

from core.events import event_bus

logger = logging.getLogger(__name__)

MAX_REACT_ITERATIONS = 6
# #14 — maximum seconds per LLM call inside the ReAct loop
REACT_ITERATION_TIMEOUT = 60
TOOL_CALL_PATTERN = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)

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
        "After receiving a <tool_result>, continue reasoning. When ready to answer, respond normally with no tool call block.",
        "",
        "Available tools:",
    ]
    for name, desc in available:
        lines.append(f"- {name}: {desc}")
    lines.append("</tools>")
    return "\n".join(lines)


def _parse_tool_call(text: str) -> dict | None:
    match = TOOL_CALL_PATTERN.search(text)
    if not match:
        return None
    raw = match.group(1).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Fallback: try name|args style
        if "|" in raw:
            parts = raw.split("|", 1)
            return {"name": parts[0].strip(), "args": parts[1].strip()}
        return None


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

    async def run(
        self,
        message: str,
        model: str,
        tool_names: list[str],
        conversation_history: list,
        stream: bool = False,
        max_tokens: int = 4096,
        agent_id: str = "",
    ) -> str:
        """
        ReAct loop:
          1. Call LLM with message + tool instructions
          2. Parse response for <tool_call>
          3. Execute tool, inject <tool_result>
          4. Repeat up to MAX_REACT_ITERATIONS
          5. Return final response (no tool call in output)
        """
        system = self.system_prompt + _build_tool_instructions(tool_names)
        messages = list(conversation_history) + [{"role": "user", "content": message}]

        # RAG auto-context: prepend top matching knowledge chunks to system prompt
        if agent_id:
            try:
                from db.rag import search as rag_search
                # Extract session_id from agent_id prefix (format: "session_id-uuid")
                session_id = agent_id.split("-")[0] if "-" in agent_id else ""
                if session_id:
                    chunks = await rag_search(session_id, message, limit=3)
                    if chunks:
                        ctx = "\n\n".join(f"[{c['title']}]\n{c['content']}" for c in chunks)
                        system = f"<context>\n{ctx}\n</context>\n\n" + system
            except Exception:
                pass

        for iteration in range(MAX_REACT_ITERATIONS):
            # #14 — per-iteration timeout so a hung LLM call doesn't block forever
            try:
                response = await asyncio.wait_for(
                    self.llm.call(
                        model=model,
                        messages=messages,
                        system_prompt=system,
                        stream=False,  # streaming handled at API/CLI level
                        max_tokens=max_tokens,
                    ),
                    timeout=REACT_ITERATION_TIMEOUT,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "Agent %s iteration %d timed out after %ds",
                    agent_id, iteration, REACT_ITERATION_TIMEOUT,
                )
                return "I'm sorry, the response timed out. Please try again."

            tool_call = _parse_tool_call(response)
            if tool_call is None:
                # No tool call — this is the final answer
                return response

            tool_name = tool_call.get("name", "")
            tool_args = tool_call.get("args", "")

            tool = self.tools.get(tool_name)
            if tool is None:
                tool_result = f"Unknown tool: {tool_name}"
            else:
                # Emit tool event
                if agent_id:
                    await event_bus.emit({
                        "type": "agent_tools",
                        "agent_id": agent_id,
                        "tools": [tool_name],
                    })
                try:
                    tool_result = await tool.run(tool_args)
                except Exception as e:
                    tool_result = f"Tool error [{tool_name}]: {e}"

            # Append assistant's tool call and the result to message history
            messages.append({"role": "assistant", "content": response})
            messages.append({
                "role": "user",
                "content": f"<tool_result>\n{tool_result}\n</tool_result>",
            })

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
    ) -> str:
        # Emit a plan_start event before delegating to the base ReAct loop
        if agent_id:
            await event_bus.emit({
                "type": "plan_start",
                "agent_id": agent_id,
                "message": message[:200],
            })
        result = await super().run(message, model, tool_names, conversation_history, stream, max_tokens, agent_id)
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
}


def get_agent(agent_name: str, llm_manager, tools_manager) -> BaseAgent:
    cls = AGENT_REGISTRY.get(agent_name, GeneralAgent)
    return cls(llm_manager, tools_manager)
