"""Call agent nodes in sequence; keep calculations and response text in nodes and tools."""

from agent.nodes.route import route
from agent.nodes.extract import extract
from agent.nodes.retrieve import make_search_index, _Fallback
from agent.nodes.quantity import quantity_step
from agent.nodes.price import price_step
from agent.nodes.respond import finalize, out_of_scope, missing_info, quantity_refused

def answer(query: str, rates: dict | None = None, offline: bool = False, hybrid_factory=None) -> dict:
    rates = rates or {}
    intent, reason = route(query)
    if intent == "OUT_OF_SCOPE":
        return out_of_scope(reason)

    ext = extract(query)
    if ext["unsupported"]:
        return out_of_scope(ext["unsupported"], ext["inputs"])
    if ext["missing"] or ext["ambiguous"]:
        return missing_info(ext)

    index, method, warning = make_search_index(offline, hybrid_factory)
    search = _Fallback(index, index.bm25) if method == "hybrid" else index
    labor = quantity_step(ext["inputs"])          # 품량 단계: calc/quantity.py가 계산
    if labor["status"] != "computed":
        return quantity_refused(labor, ext["inputs"])
    resp, result = price_step(labor, rates, search, query, index, method, warning, ext["inputs"])
    return finalize(resp, result)
