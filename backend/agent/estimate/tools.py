"""검증 가능한 서버 도구(설계 docs/agent-tool-orchestration-plan.md §4, PR 1).

세션(EstimateSession, 항목 하나)의 작업 사본을 직접 바꾸고 공통 형식 결과를 돌려준다.
품 계수·단가·금액은 모두 기존 계산기·가격·원가계산서 코드가 만든다. 이 모듈은 순서·검증·캐시만 맡는다.

공통 결과: {"status": ok|needs_input|not_found|blocked|error, "data", "missing", "rejected", "revision"}
- missing의 질문은 stage(work·labor·price)를 가진다. 공종이 미확정이면 work만 묻는다.
- 품 산출 조건과 가격 조건은 rules/conditions.price_fields로 나눈다. 품은 labor_only 모드로 계산한다.
- 품 결과는 품 입력 키(labor_key)가 같으면 다시 계산하지 않는다(가격 조건만 바뀐 경우).
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import date
from fractions import Fraction

from backend.agent.estimate.aggregate import aggregate
from backend.agent.estimate.state import (COMMON_FIELDS, EstimateItem, EstimateSession, PlanError, choose_work,
                                          new_session, question_version, set_common, set_explicit, set_quantity,
                                          unit_key)
from backend.agent.nodes.compute import CALCULATORS
from backend.agent.nodes.fill import _format_rational, _norm, _valid_for_field, extract_inputs
from backend.agent.nodes.qa_context import build_context
from backend.agent.nodes.retrieve import retrieve
from backend.agent.nodes.select import select
from backend.agent.rules.conditions import price_fields
from backend.agent.rules.specs import load_specs, specs_by_section
from backend.agent.tools.calc.adjustments import adjustment_questions
from backend.agent.tools.calc.daily_crew import check_blocked
from backend.agent.tools.calc.price import price_unit, select_rate_version


# ---- 세션·결과 형식 ----

def new_estimate(request_text: str, basis_date: str | None = None) -> EstimateSession:
    return new_session({"original_request": request_text, "basis_date": basis_date,
                        "items": [{"request_text": request_text}]})


def _item(session: EstimateSession) -> EstimateItem:
    return session["items"][session["item_order"][0]]


def _result(status: str, item: EstimateItem, data: dict | None = None, missing: list | None = None,
            rejected: dict | None = None) -> dict:
    return {"status": status, "data": data or {}, "missing": missing or [], "rejected": rejected or {},
            "revision": item["input_revision"]}


def _spec(item: EstimateItem) -> dict | None:
    if not (item.get("selection") or {}).get("confirmed"):
        return None
    return load_specs().get(item["selected_spec_id"])


def _spec_for(candidate: dict) -> dict | None:
    entries = specs_by_section().get((candidate.get("division", "공통"), candidate["section_no"]))
    return entries[0] if entries else None


def _quantity_field(spec: dict) -> dict | None:
    name = spec["quantity_model"]["params"].get("quantity_input")
    return next((field for field in spec["inputs"] if field["name"] == name), None)


def _question(item: EstimateItem, field: str, ask: str, choices, stage: str, **extra) -> dict:
    choices = choices if isinstance(choices, list) else None  # PR #22: 목록 또는 null
    return {"question_id": f"{item['item_id']}:{field}",
            "version": question_version(item["item_id"], field, item.get("selected_spec_id"), choices),
            "field": field, "ask": ask, "choices": choices, "stage": stage,
            "reason": item["question_reasons"].get(field) or extra.pop("reason", None),
            **{key: value for key, value in extra.items() if value is not None}}


def _work_question(item: EstimateItem) -> dict:
    return _question(item, "work", "어느 공종(타설 방식)으로 계산할까요?",
                     [candidate["section"] for candidate in item["candidates"]], "work")


def _field_question(item: EstimateItem, spec: dict, field: dict, stage: str) -> dict:
    tables = {table["id"]: table for table in spec["tables"]}
    return _question(item, field["name"], field["ask"], field["allowed_values"], stage,
                     unit=field.get("unit"), labels=field.get("labels"),
                     decision_table=tables[field["decision_table"]]["values"] if field.get("decision_table") else None)


# ---- 조건 구성 ----

def _build_conditions(item: EstimateItem, spec: dict) -> tuple[dict, str | None]:
    """확정 명세 기준 조건: 원래 요청에서 읽은 값 ← 사용자 값(explicit). 물량은 단위가 맞을 때만 넣는다.

    체크포인트 ad38869의 estimate/flow.py와 같은 규칙이다.
    """
    stated, _ = extract_inputs(item["request_text"], spec)
    fields = {field["name"]: field for field in spec["inputs"]}
    conditions = {name: value for name, value in stated.items() if name in fields}
    quantity_field = _quantity_field(spec)
    mismatch = None
    if quantity_field:
        conditions.pop(quantity_field["name"], None)
        quantity = item.get("quantity")
        if quantity is None and quantity_field["name"] in stated:
            quantity = {"value": stated[quantity_field["name"]], "unit": quantity_field.get("unit")}
        if quantity:
            if unit_key(quantity["unit"]) and unit_key(quantity["unit"]) == unit_key(quantity_field.get("unit")):
                conditions[quantity_field["name"]] = quantity["value"]
            else:
                mismatch = (f"요청 물량 {quantity['value']}{quantity['unit']}는 이 공종의 물량 단위"
                            f"({quantity_field.get('unit') or '알 수 없음'})와 맞지 않아요. 이 단위로 물량을 알려 주세요.")
    for name, entry in item["explicit"].items():
        if quantity_field and name == quantity_field["name"]:
            continue
        if name.startswith("apply_adj_") or (name in fields and _valid_for_field(entry["value"], fields[name])):
            conditions[name] = entry["value"]
        elif name in fields:
            conditions.pop(name, None)
            item["question_reasons"].setdefault(name, "받은 값이 이 공종의 선택지와 맞지 않아요. 다시 골라 주세요.")
    return conditions, mismatch


def _missing_fields(spec: dict, values: dict, names) -> list[dict]:
    return [field for field in spec["inputs"]
            if field["name"] in names and field["required"] and field["name"] not in values
            and (not field.get("when") or values.get(field["when"]["input"]) == field["when"]["equals"])]


def _labor_key(spec: dict, values: dict) -> str:
    excluded = price_fields(spec)
    labor = {name: value for name, value in values.items()
             if name not in excluded and name not in COMMON_FIELDS}
    return hashlib.sha1(json.dumps([spec["id"], labor], ensure_ascii=False, sort_keys=True,
                                   default=str).encode()).hexdigest()


# ---- 도구 ----

def find_work(session: EstimateSession, hits: list[dict] | None = None) -> dict:
    """공종 후보를 찾는다. hits를 주지 않으면 검색 색인을 쓴다."""
    item = _item(session)
    item["hits"] = retrieve({"query": item["request_text"]})["hits"] if hits is None else hits
    decided = select({"hits": item["hits"], "query": item["request_text"]})
    item["candidates"] = decided["candidates"]
    decision = decided["selection"]["decision"]
    candidates = [{"spec_id": (_spec_for(c) or {}).get("id"), "section": c["section"], "section_no": c["section_no"],
                   "has_spec": c["has_spec"]} for c in item["candidates"]]
    if decision == "chosen":
        top = item["candidates"][0]
        choose_work(item, {"decision": "chosen", "confirmed": True, "section_no": top["section_no"],
                           "section": top["section"]}, load_specs()[decided["spec_id"]])
        return _result("ok", item, {"decision": decision, "candidates": candidates, "spec_id": decided["spec_id"]})
    if decision == "provisional":
        item["selection"] = {"decision": "provisional", "confirmed": False}
        item["status"] = "NEEDS_WORK"
        return _result("needs_input", item, {"decision": decision, "candidates": candidates},
                       missing=[_work_question(item)])
    item["selection"] = decided["selection"]
    item.update(status="UNSUPPORTED" if decision == "no_spec" else "NOT_FOUND", reason=decided["selection"]["reason"])
    return _result("not_found", item, {"decision": decision, "candidates": candidates,
                                       "reason": decided["selection"]["reason"]})


def set_conditions(session: EstimateSession, user_text: str, *, values: dict | None = None,
                   quantity: dict | None = None, work: str | None = None, source: str = "text") -> dict:
    """조건·물량·공종 선택을 검증해 반영한다.

    source="text"(LLM이 사용자 문장에서 읽은 값)이면 evidence가 그 문장에 실제로 있어야 한다.
    source="answer"(서버가 낸 질문의 선택지 답)이면 evidence 없이 허용값만 검사한다.
    """
    item = _item(session)
    said = _norm(user_text or "")
    rejected, applied = {}, {}

    def grounded(entry: dict) -> bool:
        evidence = entry.get("evidence")
        return source == "answer" or (isinstance(evidence, str) and bool(_norm(evidence)) and _norm(evidence) in said)

    if work is not None:
        chosen = [c for c in item.get("candidates", []) if work in (c["section"], c["section_no"], (_spec_for(c) or {}).get("id"))]
        spec = _spec_for(chosen[0]) if len(chosen) == 1 else None
        if spec is None:
            rejected["work"] = "후보에 없는 공종입니다"
        else:
            choose_work(item, {"decision": "chosen", "confirmed": True, "section_no": chosen[0]["section_no"],
                               "section": chosen[0]["section"]}, spec)
            applied["work"] = spec["id"]
    spec = _spec(item)
    fields = {field["name"]: field for field in spec["inputs"]} if spec else {}
    quantity_field = _quantity_field(spec) if spec else None
    if quantity is not None:
        if not grounded(quantity):
            rejected["quantity"] = "원문에 근거가 없습니다"
        elif unit_key(quantity.get("unit")) is None or (
                quantity_field and unit_key(quantity["unit"]) != unit_key(quantity_field.get("unit"))):
            rejected["quantity"] = f"물량 단위가 맞지 않습니다: {quantity.get('unit')}"
        else:
            try:
                set_quantity(item, quantity["value"], quantity["unit"], source)
                applied["quantity"] = item["quantity"]["value"]
            except (ValueError, ZeroDivisionError, PlanError):
                rejected["quantity"] = "물량은 0보다 큰 수여야 합니다"
    for name, entry in (values or {}).items():
        value = entry.get("value") if isinstance(entry, dict) else None
        if not isinstance(entry, dict) or not grounded(entry):
            rejected[name] = "원문에 근거가 없습니다"
        elif name in COMMON_FIELDS:
            try:
                set_common(session, name, value)
                applied[name] = value
            except PlanError:
                rejected[name] = "허용값이 아닙니다"
        elif spec is None:
            set_explicit(item, name, value, source)  # 공종이 정해지면 choose_work가 호환 값만 남긴다
            applied[name] = value
        elif name not in fields:
            rejected[name] = "이 공종에 없는 조건입니다"
        else:
            field = fields[name]
            if field.get("labels") and value not in field["allowed_values"]:
                raw = [key for key, label in field["labels"].items() if label == value]
                value = raw[0] if len(raw) == 1 else value
            if not _valid_for_field(value, field):
                rejected[name] = "허용값이 아닙니다"
            elif quantity_field and name == quantity_field["name"]:
                set_quantity(item, value, quantity_field.get("unit"), source)
                applied[name] = item["quantity"]["value"]
            else:
                if field["type"] in ("positive_rational", "positive_currency") and value != "모름":
                    value = _format_rational(Fraction(str(value).replace(",", "")))
                set_explicit(item, name, value, source)
                applied[name] = value
    return _result("ok", item, {"applied": applied, "dropped": item.get("dropped_conditions", [])}, rejected=rejected)


def compute_labor(session: EstimateSession) -> dict:
    """품 산출 모드: 가격 조건 없이 1단위당 품과 물량 기준 작업일수·인일·장비를 계산한다."""
    item = _item(session)
    if not (item.get("selection") or {}).get("confirmed"):
        if not item.get("candidates"):
            return _result("not_found", item, {"reason": "공종 후보를 먼저 찾아야 합니다"})
        return _result("needs_input", item, missing=[_work_question(item)])
    spec = _spec(item)
    if spec is None:
        return _result("not_found", item, {"reason": f"{item['selection'].get('section_no')} 절의 계산 명세가 없습니다"})
    conditions, mismatch = _build_conditions(item, spec)
    excluded = price_fields(spec)
    labor_names = {field["name"] for field in spec["inputs"]} - excluded
    missing = [_field_question(item, spec, field, "labor") for field in _missing_fields(spec, conditions, labor_names)]
    quantity_field = _quantity_field(spec)
    if mismatch and quantity_field:
        item["question_reasons"].setdefault(quantity_field["name"], mismatch)
        if not any(question["field"] == quantity_field["name"] for question in missing):
            missing.insert(0, _field_question(item, spec, quantity_field, "labor"))
    missing += [_question(item, raw["name"], raw["ask"], raw["choices"], "labor")
                for raw in adjustment_questions(spec, conditions)]
    item["conditions"] = conditions
    if missing:
        item.update(status="NEEDS_INPUT", questions=missing)
        return _result("needs_input", item, missing=missing)
    key = _labor_key(spec, conditions)
    if item.get("labor_key") != key or not item.get("computed_result"):
        blocked = check_blocked(spec, conditions)
        if blocked:
            item.update(status="BLOCKED", reason=blocked["reason"], questions=[])
            return _result("blocked", item, {"reason": blocked["reason"], "citations": blocked.get("citations", [])})
        inputs = {name: value for name, value in conditions.items()
                  if name in {field["name"] for field in spec["inputs"]} or name.startswith("apply_adj_")}
        result = CALCULATORS[spec["quantity_model"]["name"]](spec, inputs, labor_only=True)
        if result.get("status") == "ask":
            missing = [_question(item, raw["name"], raw["ask"], raw.get("choices") or raw.get("allowed_values"), "labor")
                       for raw in result.get("questions", [])]
            item.update(status="NEEDS_INPUT", questions=missing)
            return _result("needs_input", item, missing=missing)
        if result.get("status") == "blocked":
            item.update(status="BLOCKED", reason=result["reason"], questions=[])
            return _result("blocked", item, {"reason": result["reason"]})
        if result.get("status") != "computed":
            item.update(status="ERROR", reason=result.get("reason", ""), questions=[])
            return _result("error", item, {"reason": result.get("reason", "")})
        item.update(computed_result=result, labor_key=key)
    item.update(questions=[], reason="")
    # 최신 가격 결과가 있는 견적은 품 결과를 다시 읽어도(explain_basis 등) 완료 상태를 유지한다.
    if not (item["status"] == "PRICED" and item.get("result_revision") == item["input_revision"]):
        item["status"] = "READY"
    result = item["computed_result"]
    return _result("ok", item, {
        "spec_id": spec["id"], "section": item["selection"].get("section"), "review_status": spec.get("review", ""),
        "unit_basis": result.get("unit_basis"), "unit_lines": result["unit_lines"],
        **{name: result.get(name) for name in ("daily_volume_m3", "work_days", "person_days",
                                               "equipment_days", "equipment_units")},
        "quantity": conditions.get(quantity_field["name"]) if quantity_field else None,
        "conditions": {name: value for name, value in conditions.items() if name not in excluded}})


def estimate_cost(session: EstimateSession) -> dict:
    """품 결과가 최신인지 확인하고, 가격 조건을 받아 일위대가와 원가계산서를 만든다."""
    labor = compute_labor(session)
    if labor["status"] != "ok":
        return labor
    item = _item(session)
    spec = _spec(item)
    conditions = item["conditions"]
    missing = [_field_question(item, spec, field, "price")
               for field in _missing_fields(spec, conditions, price_fields(spec))]
    if missing:
        item.update(status="NEEDS_INPUT", questions=missing)
        return _result("needs_input", item, labor["data"], missing=missing)
    basis = session.get("basis_date") or date.today().isoformat()
    common = {name: entry["value"] for name, entry in session["common_conditions"].items()}
    priced = price_unit(spec, item["computed_result"]["unit_lines"], select_rate_version(basis),
                        {**common, **conditions}, basis)
    item.update(priced_result=priced, status="PRICED", result_revision=item["input_revision"], questions=[],
                review_status=spec.get("review", ""))
    session.update(aggregate(session))
    outcome = session["aggregate_result"]
    if outcome["status"] in ("PENDING", "NEEDS_COMMON", "NO_RESULT"):
        return _result("error", item, {"reason": f"원가계산서를 만들 수 없습니다({outcome['status']})",
                                       "priced": priced})
    return _result("ok", item, {**labor["data"], "priced": priced, "statement": session["statement"],
                                "common": copy.deepcopy(session["common_conditions"]),
                                "price_conditions": {name: conditions[name] for name in price_fields(spec)
                                                     if name in conditions}})


def explain_basis(session: EstimateSession) -> dict:
    """최신 품 결과에 붙은 표·주석 원문 인용."""
    labor = compute_labor(session)
    if labor["status"] != "ok":
        return labor
    item = _item(session)
    result = item["computed_result"]
    seen, citations = set(), []
    sources = [*result["provenance"]["daily_volume_m3"]["citations"],
               *(citation for line in result["unit_lines"] for citation in line.get("citations", []))]
    for citation in sources:
        key = json.dumps(citation, ensure_ascii=False, sort_keys=True, default=str)
        if key not in seen:
            seen.add(key)
            citations.append(citation)
    return _result("ok", item, {"spec_id": item["selected_spec_id"], "citations": citations,
                                "memos": result.get("adjustment_memos", [])})


def search_standard(query: str, hits: list[dict] | None = None) -> dict:
    """품셈 원문 자료만 돌려준다. 답변 문장은 만들지 않는다(대화 담당 LLM이 쓴다)."""
    hits = retrieve({"query": query})["hits"] if hits is None else hits
    contexts = build_context(hits, query=query)
    sections = [{"section": context["section"], "truncated": context["truncated"], "text": context["text"],
                 "chunk_ids": [chunk["chunk_id"] for chunk in context["chunks"]]} for context in contexts]
    return {"status": "ok" if sections else "not_found", "data": {"sections": sections},
            "missing": [], "rejected": {}, "revision": None}
