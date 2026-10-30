"""명세의 계산 방식 이름으로 계산 함수를 찾아 정확한 품량을 구한다."""

from backend.agent.rules.specs import load_specs
from backend.agent.state import AgentState
from backend.agent.tools.calc.daily_crew import adjusted_daily_crew
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.tools.calc.adapters import formula_adapter, lookup_adapter
from backend.agent.tools.calc.generated import (generated_daily_crew, generated_python_daily_crew,
                                                registered_module_for, registered_python_module_for)

CALCULATORS = {"adjusted_daily_crew": adjusted_daily_crew, "per_unit": per_unit,
               "lookup_only": lookup_adapter, "formula": formula_adapter}
def calculator_for(spec: dict):
    """Reviewed modules override the legacy model only for explicitly registered sections."""
    if registered_python_module_for(spec):
        return generated_python_daily_crew
    if registered_module_for(spec):
        return generated_daily_crew
    return CALCULATORS.get(spec["quantity_model"]["name"])


def compute(state: AgentState) -> dict:
    spec = load_specs()[state["spec_id"]]
    name = spec["quantity_model"]["name"]
    calculate = calculator_for(spec)
    if calculate is None:
        return {"status": "ERROR", "reason": f"등록되지 않은 계산 방식입니다: {name}"}
    spec_inputs = {field["name"] for field in spec["inputs"]}
    result = calculate(spec, {name: value for name, value in state.get("inputs", {}).items()
                              if name in spec_inputs or name.startswith("apply_adj_")})
    if result.get("status") == "ask":
        return {"status": "MISSING_INFO", "reason": "할증 적용 여부를 확인해 주세요",
                "questions": result.get("questions", []), "result": result}
    if result.get("status") == "blocked":
        return {"status": "BLOCKED", "reason": result["reason"], "result": result}
    if result.get("status") != "computed":
        return {"status": "ERROR",
                "reason": f"fill·gate가 막았어야 할 계산 결과입니다({result.get('status')}): {result}"}
    return {"status": "COMPUTED", "result": result}
