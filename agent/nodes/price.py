"""Apply prices and map source checks and results into response state."""

from decimal import Decimal

from agent.state import base_response
from agent.tools.calc.unit_price import apply_prices
from agent.tools.calc.format import UNCALCULATED
from agent.nodes.retrieve import _Fallback

def plain(value: Decimal | None) -> str | None:
    """Decimal → 지수·끝자리 0 없는 문자열 (22500.0 → '22500'). 값은 바꾸지 않는다."""
    return None if value is None else format(value.normalize(), "f")


def price_step(labor, rates, search, query, index, method, warning, inputs):
    result = apply_prices(labor, rates, search_index=search, query=query)   # 단가 단계
    used = search.used if isinstance(search, _Fallback) else method
    api_calls = getattr(index, "api_calls", 0)
    resp = base_response("OK", "")
    resp["inputs"] = {k: str(v) for k, v in inputs.items()}
    resp["search"] = {"method": used, "top3": result["search"]["top3"], "api_calls": api_calls}
    if warning:
        resp["warnings"].append(warning)
    if isinstance(search, _Fallback) and search.error:
        resp["warnings"].append(f"하이브리드 검색 실패로 BM25로 대신했습니다: {search.error}")

    if not all(c["in_search_evidence"] and c["page_matches_case"] for c in result["source_checks"]):
        resp["status"] = "ERROR"
        resp["summary"] = ("검색 근거에서 계산에 쓸 원문 표(6-1-1, PDF 185쪽 p185-t0)를 확인하지 못해 답하지 않았습니다. "
                           f"검색 상위 3: {result['search']['top3']}")
        return resp, result

    for i in result["items"]:
        resp["cost_items"].append({"trade": i["trade"], "person_days": plain(i["person_days"]),
                                   "unit_price": plain(i["unit_price"]), "amount": plain(i["amount"]),
                                   "status": i["status"], "basis_date": i["basis_date"],
                                   "price_source": i["price_source"], "labor_source": i["labor_source"],
                                   "person_days_exact": i["exact"]["person_days"]["exact"],
                                   "amount_exact": i["exact"]["amount"]["exact"] if i["exact"]["amount"] else None,
                                   "applied_amount": i["applied_amount"]})
        if i["status"] == UNCALCULATED:
            resp["missing_fields"].append(f"노임단가({i['trade']}): 단가·기준일(YYYY-MM-DD)·출처 ({i['reason']})")
    resp["evidence"] = [{"chunk_id": c["table_chunk"], "citation": result["items"][0]["labor_source"],
                         "basis": c["basis"]} for c in result["source_checks"][:1]]
    resp["assumptions"] = result["assumptions"]
    resp["excluded_items"] = result["not_calculated"] + [u["text"] for u in result["unapplied_conditions"]]
    resp["total_cost"] = plain(result["labor_total"])
    resp["total_cost_exact"] = result["exact"]["labor_total"]["exact"] if result["exact"]["labor_total"] else None
    resp["amount_policy"] = result["amount_policy"]
    resp["status"] = "OK" if result["labor_total_status"] == "완료" else "PARTIAL"
    resp["summary"] = {"완료": "노무량과 노무비를 산출했습니다.",
                       "부분": "노무량은 산출했고, 노임단가가 없는 직종의 노무비는 미산정입니다.",
                       UNCALCULATED: "노무량은 산출했고, 노임단가가 없어 노무비는 미산정입니다."}[result["labor_total_status"]]
    return resp, result
