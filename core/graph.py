"""
LangGraph-style DAG workflow engine.

Supports:
- Nodes (sync or async callables)
- Conditional edges (router functions)
- Human-in-the-loop (pause/resume via MongoDB)
- Persistent state snapshots
- WebSocket streaming of state transitions
- Special START and END node names
"""
import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)

START = "__start__"
END = "__end__"


@dataclass
class GraphState:
    """Mutable state object passed between graph nodes."""
    data: dict[str, Any] = field(default_factory=dict)

    def update(self, updates: dict) -> "GraphState":
        self.data.update(updates)
        return self

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.data[key] = value

    def to_dict(self) -> dict:
        return dict(self.data)


NodeFn = Callable[[GraphState], Awaitable[GraphState] | GraphState]
RouterFn = Callable[[GraphState], str]


@dataclass
class Node:
    name: str
    fn: NodeFn
    is_human_input: bool = False   # Pause execution for human input


@dataclass
class Edge:
    src: str
    dst: str
    condition: RouterFn | None = None   # None = unconditional


class StateGraph:
    """
    Directed acyclic graph workflow engine.

    Usage:
        graph = StateGraph()
        graph.add_node("fetch", fetch_fn)
        graph.add_node("summarize", summarize_fn)
        graph.add_edge(START, "fetch")
        graph.add_conditional_edge("fetch", router_fn, {"yes": "summarize", "no": END})
        graph.add_edge("summarize", END)

        result = await graph.run({"query": "hello"}, run_id="abc")
    """

    def __init__(self) -> None:
        self._nodes: dict[str, Node] = {}
        self._edges: dict[str, list[Edge]] = {}
        self._event_callback: Callable | None = None

    def set_event_callback(self, cb: Callable) -> None:
        """Callback receives (event_type, node_name, state_dict) for WebSocket streaming."""
        self._event_callback = cb

    def add_node(self, name: str, fn: NodeFn, is_human_input: bool = False) -> "StateGraph":
        self._nodes[name] = Node(name=name, fn=fn, is_human_input=is_human_input)
        return self

    def add_edge(self, src: str, dst: str) -> "StateGraph":
        self._edges.setdefault(src, []).append(Edge(src=src, dst=dst))
        return self

    def add_conditional_edge(self, src: str, router: RouterFn,
                              mapping: dict[str, str]) -> "StateGraph":
        """
        router(state) returns a key from mapping.
        mapping: {"key": "node_name", ...}
        """
        def _condition(state: GraphState) -> str:
            key = router(state)
            return mapping.get(key, END)

        self._edges.setdefault(src, []).append(
            Edge(src=src, dst="__conditional__", condition=_condition)
        )
        return self

    async def run(self, initial_data: dict, run_id: str | None = None,
                  session_id: str = "", persist: bool = False) -> GraphState:
        """Execute the graph from START to END, returning final state."""
        run_id = run_id or str(uuid.uuid4())
        state = GraphState(data=dict(initial_data))
        state["__run_id__"] = run_id
        state["__session_id__"] = session_id

        if persist:
            from db.workflows import create_run
            await create_run("dynamic", run_id, state.to_dict())

        current_node = START
        visited: set[str] = set()

        while current_node != END:
            if current_node in visited and current_node != START:
                logger.warning("Graph cycle detected at node %s — stopping", current_node)
                break
            visited.add(current_node)

            next_node = await self._step(current_node, state, run_id, persist, session_id)

            if next_node is None:
                logger.warning("No outgoing edge from %s", current_node)
                break

            # Human-in-loop: pause and wait
            if next_node != END and next_node in self._nodes:
                node = self._nodes[next_node]
                if node.is_human_input:
                    await self._emit("waiting_for_human", next_node, state)
                    if persist:
                        from db.workflows import update_run_state
                        await update_run_state(run_id, state.to_dict(),
                                               status="waiting_for_human",
                                               human_input_node=next_node)
                    # Block until human_response is injected (polling MongoDB)
                    state = await self._wait_for_human(run_id, state)

            current_node = next_node

        if persist:
            from db.workflows import update_run_state
            await update_run_state(run_id, state.to_dict(), status="completed")

        await self._emit("completed", END, state)
        return state

    async def _step(self, current_node: str, state: GraphState,
                    run_id: str, persist: bool, session_id: str) -> str | None:
        edges = self._edges.get(current_node, [])
        if not edges:
            return None

        # Determine next node
        next_node: str
        edge = edges[0]
        if edge.condition:
            next_node = edge.condition(state)
        else:
            next_node = edge.dst

        if next_node == END:
            await self._emit("node_complete", current_node, state)
            return END

        # Execute node function
        node = self._nodes.get(next_node)
        if not node:
            return next_node  # Pass through (handles START → first_node)

        if next_node == current_node:
            return None  # Safety against self-loops

        await self._emit("node_start", next_node, state)
        try:
            result = node.fn(state)
            if asyncio.iscoroutine(result):
                state = await result
            else:
                state = result
        except Exception as exc:
            logger.error("Node %s failed: %s", next_node, exc)
            state["__error__"] = str(exc)
            state["__failed_node__"] = next_node
            await self._emit("node_error", next_node, state)
            return END

        # Snapshot
        if persist:
            from db.workflows import append_snapshot
            await append_snapshot(run_id, next_node, state.to_dict())

        await self._emit("node_complete", next_node, state)
        return next_node

    async def _emit(self, event_type: str, node_name: str, state: GraphState) -> None:
        if self._event_callback:
            try:
                coro = self._event_callback(event_type, node_name, state.to_dict())
                if asyncio.iscoroutine(coro):
                    await coro
            except Exception as exc:
                logger.debug("Event callback error: %s", exc)

    async def _wait_for_human(self, run_id: str, state: GraphState,
                               timeout: float = 300.0) -> GraphState:
        """Poll MongoDB until human_response is available (max 5 min)."""
        elapsed = 0.0
        interval = 1.0
        while elapsed < timeout:
            await asyncio.sleep(interval)
            elapsed += interval
            try:
                from db.workflows import get_run
                run = await get_run(run_id)
                if run and not run.get("human_input_pending", True):
                    resp = run["state"].get("human_response", "")
                    state["human_response"] = resp
                    return state
            except Exception:
                pass
        logger.warning("Human-in-loop timed out for run %s", run_id)
        state["human_response"] = ""
        return state


# ─── Pre-built utility nodes ──────────────────────────────────────────────────

def make_llm_node(agent_orchestrator, prompt_key: str = "message",
                  output_key: str = "response", model: str = "") -> NodeFn:
    """Factory: returns a node function that calls the orchestrator."""
    async def _node(state: GraphState) -> GraphState:
        message = state.get(prompt_key, "")
        session_id = state.get("__session_id__", "default")
        kwargs = {"message": message, "session_id": session_id}
        if model:
            kwargs["preferred_model"] = model
        response = await agent_orchestrator.process(**kwargs)
        state[output_key] = response
        return state
    return _node


def make_transform_node(fn: Callable[[dict], dict]) -> NodeFn:
    """Wrap a plain dict→dict transform as a graph node."""
    async def _node(state: GraphState) -> GraphState:
        updates = fn(state.to_dict())
        state.update(updates)
        return state
    return _node


def make_human_node(prompt: str = "Please provide input:") -> NodeFn:
    """A human-in-loop node that records the prompt and waits."""
    async def _node(state: GraphState) -> GraphState:
        state["human_prompt"] = prompt
        return state
    return _node
