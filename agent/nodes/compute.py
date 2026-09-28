"""명세의 계산 방식 이름으로 계산 함수를 찾아 정확한 품량을 구한다."""

from agent.rules.specs import load_specs
from agent.state import AgentState
from agent.tools.calc.daily_crew import adjusted_daily_crew

CALCULATORS = {"adjusted_daily_crew": adjusted_daily_crew}


def compute(state: AgentState) -> dict:
    spec = load_specs()[state["spec_id"]]
    name = spec["quantity_model"]["name"]
    calculate = CALCULATORS.get(name)
    if calculate is None:
        return {"status": "ERROR", "reason": f"등록되지 않은 계산 방식입니다: {name}"}
    spec_inputs = {field["name"] for field in spec["inputs"]}
    result = calculate(spec, {name: value for name, value in state.get("inputs", {}).items()
                              if name in spec_inputs})
    if result.get("status") != "computed":
        return {"status": "ERROR",
                "reason": f"fill·gate가 막았어야 할 계산 결과입니다({result.get('status')}): {result}"}
    return {"status": "COMPUTED", "result": result}
