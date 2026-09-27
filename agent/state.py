"""에이전트의 초기 상태."""

from typing import Literal, TypedDict


Status = Literal["RUNNING", "OUT_OF_SCOPE", "MISSING_INFO", "ERROR", "OK", "PARTIAL"]


class AgentState(TypedDict, total=False):
    query: str  # 사용자 질문
    status: Status  # 처리 상태
    reason: str  # 상태의 이유
    answer: str  # 최종 답변
    hits: list[dict]  # 검색된 청크
    search_info: dict  # 검색 방식과 경고
    candidates: list[str]  # 여러 카드가 걸렸을 때 후보 id


def new_state(query: str) -> AgentState:
    return {"query": query, "status": "RUNNING", "reason": "", "answer": "", "hits": [], "search_info": {}, "candidates": []}
