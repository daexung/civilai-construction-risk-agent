"""route부터 fill까지의 계산 준비 흐름."""

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from agent.nodes.ask import ask
from agent.nodes.fill import fill
from agent.nodes.retrieve import retrieve
from agent.nodes.route import route
from agent.nodes.select import select
from agent.state import AgentState


def _after_route(state: AgentState) -> str:
    # 공사비 범위 밖의 질문은 검색하지 않는다.
    return "end" if state.get("status") == "OUT_OF_SCOPE" else "retrieve"


def _after_select(state: AgentState) -> str:
    # 계산 명세가 없으면 근거만 남기고 마친다.
    return "end" if state.get("status") == "EVIDENCE_ONLY" else "fill"


def _after_fill(state: AgentState) -> str:
    # 부족한 조건은 묻고, 그 외에는 다음 단계에 필요한 state를 남긴다.
    return "ask" if state.get("status") == "MISSING_INFO" else "end"


def build_graph(checkpointer=None):
    graph = StateGraph(AgentState)
    graph.add_node("route", route)
    graph.add_node("retrieve", retrieve)
    graph.add_node("select", select)
    graph.add_node("fill", fill)
    graph.add_node("ask", ask)
    graph.add_edge(START, "route")
    graph.add_conditional_edges("route", _after_route, {"end": END, "retrieve": "retrieve"})
    graph.add_edge("retrieve", "select")
    graph.add_conditional_edges("select", _after_select, {"end": END, "fill": "fill"})
    graph.add_conditional_edges("fill", _after_fill, {"ask": "ask", "end": END})
    graph.add_edge("ask", "fill")
    return graph.compile(checkpointer=checkpointer if checkpointer is not None else MemorySaver())
