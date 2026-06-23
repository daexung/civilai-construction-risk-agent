"""
건설 리스크 통합 LangGraph (플래너 기반 동적 라우팅)
START → router → extractor (REPORT만) → weather → (비용 에이전트 병렬) ┐
                                      ↘ 비용 에이전트 직행              ├→ synthesize → END
              ↘ synthesize (CHAT/LOOKUP/CLARIFY)                       ┘

- router_node: intent/domains 분류 후 REPORT → extractor, 나머지 → synthesize
- extractor_node: 질문에서 입력값 추출(LLM) + 공종 매핑(결정론적) → weather/cost 라우팅
- weather_node: Command로 직접 라우팅 (정적 outgoing edge 없음)
- 비용 에이전트(equipment/material/labor_cost): 실행되면 synthesize로 수렴
"""
from langgraph.graph import StateGraph, START, END

from state import RiskState
from nodes.router_node import router_node
from nodes.extractor_node import extractor_node
from nodes.equipment_node import equipment_node
from nodes.weather_node import weather_node
from nodes.material_node import material_node
from nodes.labor_cost_node import labor_cost_node
from nodes.aggregator_node import aggregator_node
from nodes.synthesize_node import synthesize_node


def build_graph():
    wf = StateGraph(RiskState)

    wf.add_node('router', router_node)
    wf.add_node('extractor', extractor_node)
    wf.add_node('equipment', equipment_node)
    wf.add_node('material', material_node)
    wf.add_node('labor_cost', labor_cost_node)
    wf.add_node('weather', weather_node)
    wf.add_node('aggregator', aggregator_node)
    wf.add_node('synthesize', synthesize_node)

    wf.add_edge(START, 'router')
    # router_node가 Command로 직접 라우팅 — conditional_edges 불필요

    wf.add_edge('equipment', 'aggregator')
    wf.add_edge('material', 'aggregator')
    wf.add_edge('labor_cost', 'aggregator')
    # weather_node는 Command(goto=...)로 직접 라우팅하므로 정적 edge 불필요
    wf.add_edge('aggregator', 'synthesize')
    wf.add_edge('synthesize', END)

    return wf.compile()


graph = build_graph()
