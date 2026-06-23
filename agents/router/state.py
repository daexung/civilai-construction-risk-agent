from typing import TypedDict, Annotated, Optional
from langgraph.graph.message import add_messages


class RiskState(TypedDict):
    messages: Annotated[list, add_messages]
    intent: Optional[str]              # OUT_OF_DOMAIN | CHAT | LOOKUP | CLARIFY | REPORT
    domains: Optional[list]            # 분류된 도메인 목록 (weather/equipment/material/labor_cost)
    answer_type: Optional[str]         # CHAT | RAG_QA | COST_REPORT | RISK_REPORT | MISSING_INFO — 하위호환 유지
    question_type: Optional[str]       # 'A' (기상 선행=needs_weather) | 'B' (그 외) — 하위호환/로깅용
    needs_weather: Optional[bool]      # 기상 분석 선행 필요 여부 (플래너 결정)
    target_agents: Optional[list]      # 실행할 비용 에이전트 목록 (플래너 결정)
    project_id: Optional[str]          # 프로젝트 ID (프론트에서 설정)
    labor_cost_response: Optional[str]
    labor_cost_result: Optional[dict]
    equipment_response: Optional[str]
    equipment_result: Optional[dict]
    weather_response: Optional[str]
    weather_result: Optional[dict]
    material_response: Optional[str]
    material_result: Optional[dict]
    rag_response: Optional[str]
    rag_result: Optional[dict]
    rag_query_type: Optional[str]      # item_search | list_items
    structured_response: Optional[dict]
    aggregated_result: Optional[dict]
    final_response: Optional[str]      # 합성 노드가 만든 최종 사용자용 답변
    missing_for_cost: Optional[list]   # 비용 산정에 필요하지만 누락된 입력 목록 (partial REPORT)
    inputs: Optional[dict]             # extractor_node가 채우는 구조화 입력값 (location/date_range/work_type/quantities 등)
    weather_skip: Optional[bool]       # 공종이 기상 분석 미지원 → weather_node 건너뜀
