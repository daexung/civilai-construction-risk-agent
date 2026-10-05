"""Build the deterministic tender cost statement after unit pricing."""

from datetime import date

from backend.agent.state import AgentState
from backend.agent.tools.calc.cost_statement import calculate_cost_statement


def statement(state: AgentState) -> dict:
    result = calculate_cost_statement(state.get("priced", {}), state.get("inputs", {}),
                                      state.get("basis_date") or date.today().isoformat())
    status = "PARTIAL" if result["status"] in ("PARTIAL", "UNCALCULATED") else "OK"
    reasons = [state.get("reason", ""), result.get("reason", "")]
    return {"statement": result, "status": status,
            "reason": "; ".join(reason for reason in reasons if reason)}
