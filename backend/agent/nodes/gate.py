"""계산 전에 명세의 보류 조건에 걸리는지만 확인한다. 계산은 하지 않는다."""

from agent.rules.specs import load_specs
from agent.state import AgentState
from agent.tools.calc.daily_crew import check_blocked


def gate(state: AgentState) -> dict:
    spec = load_specs()[state["spec_id"]]
    blocked = check_blocked(spec, state.get("inputs", {}))
    if blocked:
        return {"status": "BLOCKED", "reason": blocked["reason"], "result": blocked}
    return {"review_status": spec.get("review", "")}
