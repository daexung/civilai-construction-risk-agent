"""계산된 단위당 품에 기준일의 공표 노임단가를 적용한다."""

from backend.agent.rules.specs import load_specs
from backend.agent.state import AgentState
from backend.agent.tools.calc.price import price_unit, select_rate_version


def price(state: AgentState) -> dict:
    spec = load_specs()[state["spec_id"]]
    version = select_rate_version(state.get("basis_date"))
    priced = price_unit(spec, state["result"]["unit_lines"], version,
                        state.get("inputs", {}), state.get("basis_date"))
    update = {"status": priced["status"], "priced": priced,
              "rate_version": priced["rate_version"]}
    if version is None:
        update["reason"] = "적용 가능한 노임단가 없음"
    return update
