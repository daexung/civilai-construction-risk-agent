"""Response state defaults and supported scope."""

SCOPE = "6-1-1 레디믹스트콘크리트 타설 중 '철근구조물 · 인력운반 타설'의 노무량·노무비"

def base_response(status: str, summary: str) -> dict:
    """v1.0-team 비용 노드의 결과 형식을 따른다."""
    return {"agent_name": "labor_unit_price", "domain": "노무비(일위대가)", "status": status, "summary": summary,
            "scope": SCOPE, "inputs": {}, "missing_fields": [], "ambiguities": [], "cost_items": [],
            "total_cost": None, "warnings": [], "assumptions": [], "excluded_items": [], "evidence": [],
            "search": None, "final_response": ""}


