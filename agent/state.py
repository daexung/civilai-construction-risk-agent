"""에이전트의 초기 상태."""

from typing import Literal, TypedDict


Status = Literal["RUNNING", "OUT_OF_SCOPE", "MISSING_INFO", "ERROR", "OK", "PARTIAL"]


class AgentState(TypedDict, total=False):
    query: str  # 사용자 질문
    status: Status  # 처리 상태
    reason: str  # 상태의 이유
    answer: str  # 최종 답변


def new_state(query: str) -> AgentState:
    return {"query": query, "status": "RUNNING", "reason": "", "answer": ""}
