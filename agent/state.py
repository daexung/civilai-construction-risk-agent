"""에이전트의 초기 상태."""

from typing import Literal, TypedDict


Status = Literal["RUNNING", "OUT_OF_SCOPE", "MISSING_INFO", "EVIDENCE_ONLY", "ERROR", "OK", "PARTIAL"]


class AgentState(TypedDict, total=False):
    query: str  # 사용자 질문
    status: Status  # 처리 상태
    reason: str  # 상태의 이유
    answer: str  # 최종 답변
    hits: list[dict]  # 검색된 청크
    search_info: dict  # 검색 방식과 경고
    candidates: list[dict]  # 후보 절과 제목·점수·명세 여부
    spec_id: str  # 선택된 계산 명세 id
    selection: dict  # 공종 선택 결정과 이유
    inputs: dict  # 입력 이름에서 값으로의 매핑
    input_sources: dict  # 입력 이름에서 질문 또는 답변 출처로의 매핑
    questions: list[dict]  # 한 번에 확인할 질문 목록


def new_state(query: str) -> AgentState:
    return {"query": query, "status": "RUNNING", "reason": "", "answer": "", "hits": [], "search_info": {},
            "candidates": [], "spec_id": "", "selection": {}}
