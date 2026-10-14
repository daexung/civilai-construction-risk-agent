"""route부터 fill까지의 계산 준비 흐름."""

from contextlib import contextmanager
from contextvars import ContextVar
from time import perf_counter
from typing import Iterator
import re

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from backend.agent.nodes.answer import answer
from backend.agent.nodes.ask import ask
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
from backend.shared import answer_trace

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
    bucket = _TIMING_BUCKETS.get(name)

    def summary(value):
        if not isinstance(value, dict):
            return {}
        keep = {key: value[key] for key in ("route", "status", "decision", "spec_id", "answer_source", "route_source") if key in value}
        selection = value.get("selection")
        if isinstance(selection, dict):
            keep["selection"] = {k: selection[k] for k in ("id", "internal_id", "table_id", "section", "section_no", "confirmed") if k in selection}
        hits = value.get("hits")
        if isinstance(hits, list):
            keep["hits"] = [{k: hit[k] for k in ("chunk_id", "score", "section_no", "page", "table_id") if k in hit}
                            for hit in hits[:30] if isinstance(hit, dict)]
        search = value.get("search_info")
        if isinstance(search, dict):
            keep["search"] = {k: search[k] for k in ("method", "api_calls", "fallback_reason") if k in search}
        candidates = value.get("candidates") or value.get("work_candidates")
        if isinstance(candidates, list):
            keep["candidates"] = [{"rank": rank, **{k: item[k] for k in ("id", "internal_id", "table_id", "section", "section_no", "score") if k in item}}
                                  for rank, item in enumerate(candidates[:30], 1) if isinstance(item, dict)]
        result = value.get("result")
        if isinstance(result, dict):
            keep["calculation"] = {k: result[k] for k in ("daily_volume", "work_days", "unit_basis", "per_unit_only", "review_status") if k in result}
            for key in ("lines", "unit_lines"):
                if key in result:
                    keep["calculation"][key] = [{k: line[k] for k in ("kind", "name", "value", "unit", "crew", "source") if k in line}
                                                for line in result[key][:100] if isinstance(line, dict)]
        evidence = value.get("evidence")
        if isinstance(evidence, list):
            keep["evidence"] = [{k: cite[k] for k in ("internal_id", "chunk_id", "division", "section_no", "pdf_page", "printed_page", "row", "column", "value") if k in cite}
                                 for cite in evidence[:100] if isinstance(cite, dict)]
        inputs = value.get("inputs")
        if isinstance(inputs, dict):
            from backend.agent.nodes.fill import _common_fields
            from backend.agent.rules.specs import load_specs
            spec = load_specs().get(value.get("spec_id"), {})
            fields = {field["name"]: field for field in [*spec.get("inputs", []), *_common_fields()]}
            number = re.compile(r"^[+-]?(?:\d+(?:[.,]\d+)?|\d+/\d+)$")
            selected = {}
            for name, item in inputs.items():
                field = fields.get(name, {})
                allowed = field.get("allowed_values") or []
                if item in allowed or isinstance(item, (int, float)) or isinstance(item, str) and number.fullmatch(item.strip()):
                    selected[name] = item
            if selected:
                keep["selected_conditions"] = selected
        return keep

    def run(state):
        started = perf_counter()
        try:
            before = summary(state)
            with answer_trace.step(name, "node", before) as trace_step:
                result = node(state)
                answer_trace.set_output(trace_step, summary(result))
                return result
        finally:
            timings = _NODE_TIMINGS.get()
            if timings is not None and bucket is not None:
                timings[bucket] += (perf_counter() - started) * 1000

    return run


def _after_route(state: AgentState) -> str:
    return "compose" if state.get("route") == "out_of_scope" else "retrieve"


def _after_retrieve(state: AgentState) -> str:
    return "answer" if state.get("route") == "qa" else "select"


def _after_select(state: AgentState) -> str:
    # 계산 명세가 없으면 근거만 남기고 마친다.
    return "compose" if state.get("status") == "EVIDENCE_ONLY" else "fill"


def _after_fill(state: AgentState) -> str:
    # 부족한 조건은 묻고, 명세가 없으면 근거만 남기고, 그 외에는 보류 조건을 확인한다.
    status = state.get("status")
    if status == "MISSING_INFO":
        return "ask"
    if status == "EVIDENCE_ONLY":
        return "compose"
    return "gate"


def _after_gate(state: AgentState) -> str:
    # 보류 조건에 걸리면 계산하지 않고 끝낸다.
    return "compose" if state.get("status") == "BLOCKED" else "compute"


def _after_compute(state: AgentState) -> str:
    if state.get("status") == "MISSING_INFO":
        return "ask"
    return "compose" if state.get("status") != "COMPUTED" else "price"


def build_graph(checkpointer=None):
    graph = StateGraph(AgentState)
    graph.add_node("route", _timed_node("route", route))
    graph.add_node("retrieve", _timed_node("retrieve", retrieve))
    graph.add_node("answer", _timed_node("answer", answer))
    graph.add_node("select", _timed_node("select", select))
    graph.add_node("fill", _timed_node("fill", fill))
    graph.add_node("ask", _timed_node("ask", ask))
    graph.add_node("gate", _timed_node("gate", gate))
    graph.add_node("compute", _timed_node("compute", compute))
    graph.add_node("price", _timed_node("price", price))
    graph.add_node("statement", _timed_node("statement", statement))
    graph.add_node("compose", _timed_node("compose", compose))
    graph.add_edge(START, "route")
    graph.add_conditional_edges("route", _after_route, {"compose": "compose", "retrieve": "retrieve"})
    graph.add_conditional_edges("retrieve", _after_retrieve, {"answer": "answer", "select": "select"})
    graph.add_edge("answer", END)
    graph.add_conditional_edges("select", _after_select, {"compose": "compose", "fill": "fill"})
    graph.add_conditional_edges("fill", _after_fill, {"ask": "ask", "compose": "compose", "gate": "gate"})
    graph.add_edge("ask", "fill")
    graph.add_conditional_edges("gate", _after_gate, {"compose": "compose", "compute": "compute"})
    graph.add_conditional_edges("compute", _after_compute, {"compose": "compose", "price": "price", "ask": "ask"})
    graph.add_edge("price", "statement")
    graph.add_edge("statement", "compose")
    graph.add_edge("compose", END)
    return graph.compile(checkpointer=checkpointer if checkpointer is not None else MemorySaver())
