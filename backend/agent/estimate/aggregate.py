"""부모 세션에서 공종별 결과를 모아 통합 원가계산서를 만든다(단계 C1).

- 합산 대상: 상태가 PRICED이고 result_revision == input_revision인 공종만.
- 질문이 남았거나 결과가 낡은 공종이 있으면 견적을 확정하지 않는다(PENDING).
- 공종별 직접비(재료비·노무비·경비)만 더하고, 간접비·일반관리비·이윤·부가세는 기존
  calculate_cost_statement를 한 번 호출해 계산한다. 공종마다 계산한 원가계산서를 다시 더하지 않는다.
- 공통 공사 조건은 기본값도 값과 출처를 세션에 저장한다. 공종들의 부문이 달라 공사 종류 기본값이 갈리면
  첫 공종 기준으로 정하지 않고 확인 질문을 만든다(NEEDS_COMMON).
- 합산할 공종이 없으면 0원 견적을 만들지 않는다(NO_RESULT).

견적 상태(aggregate_result.status)는 처리 완료(flow.session_complete)와 별개다.
"""

from __future__ import annotations

import copy
from datetime import date

from backend.agent.estimate.state import SETTLED, EstimateSession, question_version
from backend.agent.nodes.fill import _common_fields
from backend.agent.rules.specs import load_specs
from backend.agent.tools.calc.cost_statement import calculate_cost_statement

EXPLICIT_SOURCES = {"plan", "answer"}
DIRECT_PARTS = ("재료비", "노무비", "경비")


def _division_default(division: str) -> str:
    """기존 fill과 같은 공사 종류 기본값."""
    return "주택 외 건축" if division in ("건축", "기계설비") else "기타 토목공사"


def resolve_common(session: EstimateSession) -> list[dict]:
    """공통 조건을 세션에 확정한다(기본값도 출처와 함께). 정할 수 없으면 확인 질문을 돌려준다."""
    common = session["common_conditions"]
    divisions = sorted({load_specs()[item["selected_spec_id"]]["division"] for item in session["items"].values()
                        if item.get("status") == "PRICED" and item.get("selected_spec_id")})
    questions = []
    for field in _common_fields():
        name = field["name"]
        if name in common and common[name]["source"] in EXPLICIT_SOURCES:
            continue
        if name == "work_category":
            defaults = sorted({_division_default(division) for division in divisions})
            if len(defaults) > 1:
                common.pop(name, None)
                questions.append({
                    "question_id": "common:work_category",
                    "version": question_version("common", name, divisions, field["allowed_values"]),
                    "scope": "common", "item_id": None, "field": name, "kind": "choice",
                    "allowed_values": field["allowed_values"], "required": True, "ask": field["ask"],
                    "reason": f"공종의 부문({', '.join(divisions)})이 달라 공사 종류를 하나로 정할 수 없어요. 전체 공사의 종류를 골라 주세요."})
                continue
            if defaults:
                common[name] = {"value": defaults[0], "source": "default_division", "explicit": False}
                continue
        common[name] = {"value": field["default"], "source": "default", "explicit": False}
    return questions


def _combined_priced(included: list[dict], failed: list[dict]) -> dict:
    """원가계산서 입력. 공종 하나면 그 공종의 가격 결과를 그대로 쓴다(단일 공종 main과 같은 계산)."""
    failed_entries = [{"name": f"{item['item_id']} {item['request_text']}", "category": "경비",
                       "reason": item.get("reason") or item["status"]} for item in failed]
    if len(included) == 1:
        priced = copy.deepcopy(included[0]["priced_result"])
        priced["unpriced"] = list(priced.get("unpriced", [])) + failed_entries
        return priced
    subtotals = {part: 0 for part in DIRECT_PARTS}
    unpriced, excluded = [], []
    for item in included:
        reference = item["priced_result"]["reference_amounts"]
        for part in DIRECT_PARTS:
            subtotals[part] += int((reference.get("subtotals") or {}).get(part) or 0)
        for target, source in ((unpriced, item["priced_result"].get("unpriced", [])),
                               (excluded, item["priced_result"].get("excluded", []))):
            target.extend(entry for entry in source if all(seen["name"] != entry["name"] for seen in target))
    return {"reference_amounts": {"subtotals": subtotals, "volume": None,
                                  # 단일 공종처럼 공종별 물량 기준 합계(버림 후)를 더한다
                                  "total": sum(int(item["priced_result"]["reference_amounts"]["total"]) for item in included)},
            "rate_version": included[0]["priced_result"].get("rate_version") or {},
            "unpriced": unpriced + failed_entries, "excluded": excluded}


def aggregate(session: EstimateSession) -> EstimateSession:
    """공종 결과를 모아 견적 상태·통합 원가계산서를 정한다. 공종 계산은 다시 하지 않는다."""
    session = copy.deepcopy(session)
    session["pending_questions"] = {qid: q for qid, q in session["pending_questions"].items() if q.get("scope") != "common"}
    items = [session["items"][item_id] for item_id in session["item_order"]]
    waiting = [item for item in items if item["status"] not in SETTLED or item.get("result_revision") != item["input_revision"]]
    session["statement"] = None
    if session["pending_questions"] or waiting:
        session["aggregate_result"] = {"status": "PENDING", "waiting": [
            {"item_id": item["item_id"], "status": item["status"],
             "reason": item.get("reason") or ("계산 결과가 최신이 아니에요" if item["status"] in SETTLED else "")}
            for item in waiting]}
        return session
    common_questions = resolve_common(session)
    if common_questions:
        session["pending_questions"].update({q["question_id"]: q for q in common_questions})
        session["aggregate_result"] = {"status": "NEEDS_COMMON", "waiting": []}
        return session
    included = [item for item in items if item["status"] == "PRICED"
                and ((item.get("priced_result") or {}).get("reference_amounts") or {}).get("total") is not None]
    failed = [item for item in items if item not in included]
    excluded_items = [{"item_id": item["item_id"], "request_text": item["request_text"], "status": item["status"],
                       "reason": item.get("reason") or "계산 결과가 없어요"} for item in failed]
    if not included:
        session["aggregate_result"] = {"status": "NO_RESULT", "included": [], "excluded": excluded_items}
        return session
    common_values = {name: entry["value"] for name, entry in session["common_conditions"].items()}
    statement = calculate_cost_statement(_combined_priced(included, failed), common_values,
                                         session.get("basis_date") or date.today().isoformat())
    session["statement"] = statement
    item_direct = {item["item_id"]: {"subtotals": item["priced_result"]["reference_amounts"].get("subtotals"),
                                     "total": item["priced_result"]["reference_amounts"]["total"],
                                     "result_revision": item["result_revision"]} for item in included}
    session["aggregate_result"] = {
        "status": "PARTIAL" if failed or statement["status"] in ("PARTIAL", "UNCALCULATED") else "COMPLETE",
        "included": [item["item_id"] for item in included], "excluded": excluded_items,
        "items": item_direct,
        "direct_total": sum(int(entry["total"]) for entry in item_direct.values()),
        "common": copy.deepcopy(session["common_conditions"]), "basis_date": session.get("basis_date"),
        "contract_amount": statement["totals"].get("contract_amount")}
    return session
