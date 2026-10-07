"""route부터 fill까지의 계산 준비 흐름."""

from contextlib import contextmanager
from contextvars import ContextVar
from time import perf_counter
from typing import Iterator

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from backend.agent.nodes.answer import answer
from backend.agent.nodes.ask import ask
from backend.agent.nodes.bundle import bundle, collect, item_label, split
from backend.agent.nodes.compose import compose
from backend.agent.nodes.compute import compute
from backend.agent.nodes.price import price
from backend.agent.nodes.statement import statement
from backend.agent.nodes.fill import fill
from backend.agent.nodes.gate import gate
from backend.agent.nodes.retrieve import retrieve
from backend.agent.nodes.route import route
from backend.agent.nodes.select import select
from backend.agent.state import AgentState

_NODE_TIMINGS: ContextVar[dict[str, float] | None] = ContextVar("civilai_node_timings", default=None)
_TIMING_BUCKETS = {
    "route": "route_ms",
    "retrieve": "retrieve_ms",
    "select": "compute_ms",
    "fill": "compute_ms",
    "gate": "compute_ms",
    "compute": "compute_ms",
    "price": "compute_ms",
    "statement": "compute_ms",
    "split": "compute_ms",
    "collect": "compute_ms",
    "bundle": "compute_ms",
    "answer": "llm_ms",
    "compose": "llm_ms",
}


@contextmanager
def capture_node_timings() -> Iterator[dict[str, float]]:
    """Collect node wall times for the current request without storing them in graph state."""
    timings: dict[str, float] = {key: 0.0 for key in ("route_ms", "retrieve_ms", "compute_ms", "llm_ms")}
    token = _NODE_TIMINGS.set(timings)
    try:
        yield timings
    finally:
        _NODE_TIMINGS.reset(token)


def _timed_node(name: str, node):
    bucket = _TIMING_BUCKETS[name]

    def run(state):
        started = perf_counter()
        try:
            return node(state)
        finally:
            timings = _NODE_TIMINGS.get()
            if timings is not None:
                timings[bucket] += (perf_counter() - started) * 1000

    return run


def _after_route(state: AgentState) -> str:
    return "compose" if state.get("route") == "out_of_scope" else "split"


def _after_split(state: AgentState) -> str:
    status = state.get("status")
    return "compose" if status == "BLOCKED" else "ask" if status == "MISSING_INFO" else "retrieve"


def _after_ask(state: AgentState) -> str:
    # 공종 나누기 확인에 답했으면 split으로, 그 외 조건 답변은 fill로 돌아간다.
    return "split" if state.get("split_pending") else "fill"


def _end(state: AgentState) -> str:
    """여러 공종이면 항목을 끝내고 다음 항목으로, 아니면 설명 문장으로 간다."""
    return "collect" if state.get("items") else "compose"


def _after_retrieve(state: AgentState) -> str:
    return "answer" if state.get("route") == "qa" else "select"


def _after_select(state: AgentState) -> str:
    # 계산 명세가 없으면 근거만 남기고 마친다.
    return _end(state) if state.get("status") == "EVIDENCE_ONLY" else "fill"


def _after_fill(state: AgentState) -> str:
    # 부족한 조건은 묻고, 명세가 없으면 근거만 남기고, 그 외에는 보류 조건을 확인한다.
    status = state.get("status")
    if status == "MISSING_INFO":
        return "ask"
    if status == "EVIDENCE_ONLY":
        return _end(state)
    return "gate"


def _after_gate(state: AgentState) -> str:
    # 보류 조건에 걸리면 계산하지 않고 끝낸다.
    return _end(state) if state.get("status") == "BLOCKED" else "compute"


def _after_compute(state: AgentState) -> str:
    if state.get("status") == "MISSING_INFO":
        return "ask"
    return _end(state) if state.get("status") != "COMPUTED" else "price"


def _after_price(state: AgentState) -> str:
    return "collect" if state.get("items") else "statement"


def _after_collect(state: AgentState) -> str:
    return "retrieve" if state["item_index"] < len(state["items"]) else "bundle"


def _fill_item(state: AgentState) -> dict:
    update = fill(state)
    if state.get("items") and update.get("status") == "MISSING_INFO":
        update["reason"] = f"{item_label(state)} 견적을 계산하려면 아래 조건을 확인해 주세요."
    return update


def build_graph(checkpointer=None):
    graph = StateGraph(AgentState)
    graph.add_node("route", _timed_node("route", route))
    graph.add_node("retrieve", _timed_node("retrieve", retrieve))
    graph.add_node("answer", _timed_node("answer", answer))
    graph.add_node("select", _timed_node("select", select))
    graph.add_node("fill", _timed_node("fill", _fill_item))
    graph.add_node("ask", ask)
    graph.add_node("gate", _timed_node("gate", gate))
    graph.add_node("compute", _timed_node("compute", compute))
    graph.add_node("price", _timed_node("price", price))
    graph.add_node("statement", _timed_node("statement", statement))
    graph.add_node("compose", _timed_node("compose", compose))
    graph.add_node("split", _timed_node("split", split))
    graph.add_node("collect", _timed_node("collect", collect))
    graph.add_node("bundle", _timed_node("bundle", bundle))
    graph.add_edge(START, "route")
    graph.add_conditional_edges("route", _after_route, {"compose": "compose", "split": "split"})
    graph.add_conditional_edges("split", _after_split, {"compose": "compose", "ask": "ask", "retrieve": "retrieve"})
    graph.add_conditional_edges("retrieve", _after_retrieve, {"answer": "answer", "select": "select"})
    graph.add_edge("answer", END)
    graph.add_conditional_edges("select", _after_select, {"compose": "compose", "collect": "collect", "fill": "fill"})
    graph.add_conditional_edges("fill", _after_fill, {"ask": "ask", "compose": "compose", "collect": "collect", "gate": "gate"})
    graph.add_conditional_edges("ask", _after_ask, {"split": "split", "fill": "fill"})
    graph.add_conditional_edges("gate", _after_gate, {"compose": "compose", "collect": "collect", "compute": "compute"})
    graph.add_conditional_edges("compute", _after_compute, {"compose": "compose", "collect": "collect", "price": "price", "ask": "ask"})
    graph.add_conditional_edges("price", _after_price, {"collect": "collect", "statement": "statement"})
    graph.add_conditional_edges("collect", _after_collect, {"retrieve": "retrieve", "bundle": "bundle"})
    graph.add_edge("bundle", "compose")
    graph.add_edge("statement", "compose")
    graph.add_edge("compose", END)
    return graph.compile(checkpointer=checkpointer if checkpointer is not None else MemorySaver())
