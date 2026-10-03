"""에이전트의 초기 상태."""

from typing import Literal, TypedDict


Status = Literal["RUNNING", "OUT_OF_SCOPE", "MISSING_INFO", "EVIDENCE_ONLY", "BLOCKED", "COMPUTED",
                 "ERROR", "OK", "PARTIAL", "ANSWERED"]


class AgentState(TypedDict, total=False):
    query: str  # 사용자 질문
    route: Literal["estimate", "qa", "out_of_scope"]
    route_confidence: float | None
    route_reason: str
    route_source: Literal["llm", "llm_low_confidence", "rule"]
    previous_context: dict  # 같은 thread의 직전 route/work/result
    status: Status  # 처리 상태
    reason: str  # 상태의 이유
    answer: str  # 최종 답변
    answer_source: str  # "llm" | "template"
    llm_info: dict  # LLM 모델, 걸린 시간, 실패·거부 사유, 거부된 숫자
    qa: dict | None  # 구조화 상담 답변
    hits: list[dict]  # 검색된 청크
    search_info: dict  # 검색 방식과 경고
    candidates: list[dict]  # 후보 절과 제목·점수·명세 여부
    spec_id: str  # 선택된 계산 명세 id
    selection: dict  # 공종 선택 결정과 이유
    inputs: dict  # 입력 이름에서 값으로의 매핑
    input_sources: dict  # 입력 이름에서 질문 또는 답변 출처로의 매핑
    questions: list[dict]  # 한 번에 확인할 질문 목록
    reply: str  # 마지막 사용자 답
    review_status: str  # 명세의 검토 상태(예: "미완료")
    result: dict  # gate·compute의 계산 결과
    basis_date: str  # 노임단가 적용 기준일(YYYY-MM-DD); 없으면 현재일
    priced: dict  # 일위대가 노무비·요율 비용
    statement: dict  # 물량 기준 원가계산서 최종 견적
    rate_version: dict | None  # 적용한 공표 버전 메타데이터


def new_state(query: str, basis_date: str | None = None) -> AgentState:
    state: AgentState = {"query": query, "status": "RUNNING", "reason": "", "answer": "", "hits": [],
                         "qa": None, "search_info": {}, "candidates": [], "spec_id": "", "selection": {}}
    if basis_date is not None:
        state["basis_date"] = basis_date
    return state
