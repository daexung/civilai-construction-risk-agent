"""필요한 조건을 사용자에게 한 번에 확인한다."""

from langgraph.types import interrupt

from backend.agent.state import AgentState


def ask(state: AgentState) -> dict:
    reply = interrupt({"questions": state["questions"], "reason": state["reason"]})
    return {"reply": reply, "status": "RUNNING", "questions": []}
