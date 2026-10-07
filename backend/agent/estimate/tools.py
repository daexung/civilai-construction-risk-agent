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
import re
import unicodedata
from datetime import date
from fractions import Fraction

from backend.agent.estimate.aggregate import aggregate
from backend.agent.estimate.state import (COMMON_FIELDS, EstimateItem, EstimateSession, PlanError, choose_work,
                                          new_session, question_version, set_common, set_explicit, set_quantity,
                                          unit_key)
from backend.agent.nodes.compute import CALCULATORS
from backend.agent.nodes.fill import (_UNIT_ALIASES, _extract_common_inputs, _format_rational, _norm,
                                      _valid_for_field, extract_inputs)
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
        if quantity is None:
            # 기존 _volume은 '세제곱미터'를 읽지 못한다. 서버 단위 파서로 같은 단위의 물량이 하나일 때만 쓴다.
            found = {value for value, unit in _quantities(item["request_text"])
                     if unit and unit == unit_key(quantity_field.get("unit"))}
            if len(found) == 1:
                quantity = {"value": _format_rational(found.pop()), "unit": quantity_field.get("unit")}
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


_NUMERIC = {"positive_rational", "positive_currency", "nonnegative_integer"}
_MISSING = object()
_MULTIPLIER = {"억": 100_000_000, "만": 10_000}
_UNIT_WORDS = sorted({alias for aliases in _UNIT_ALIASES.values() for alias in aliases}, key=len, reverse=True)
_QUANTITY = re.compile(r"(?<![\d.])(\d[\d,]*(?:\.\d+)?)\s*(" + "|".join(map(re.escape, _UNIT_WORDS)) + r")(?![a-z0-9])")
_NUMBER = re.compile(r"(?<![\d.])(\d[\d,]*(?:\.\d+)?)\s*(억|만)?")


def _fraction(value) -> Fraction | None:
    try:
        return Fraction(str(value).replace(",", ""))
    except (ValueError, ZeroDivisionError):
        return None


def _numbers(evidence: str) -> set[Fraction]:
    """근거 구절의 숫자. '9만원'처럼 만·억 단위는 원 단위로 바꾼다."""
    text = unicodedata.normalize("NFKC", evidence)
    return {Fraction(raw.replace(",", "")) * _MULTIPLIER.get(scale, 1) for raw, scale in _NUMBER.findall(text)}


def _quantities(evidence: str) -> set[tuple[Fraction, str | None]]:
    """근거 구절의 (숫자, 단위 종류). ㎥·m3·루베·세제곱미터는 같은 단위다."""
    text = unicodedata.normalize("NFKC", evidence).casefold()
    return {(Fraction(raw.replace(",", "")), unit_key(unit)) for raw, unit in _QUANTITY.findall(text)}


def _digest(*parts) -> str:
    return hashlib.sha1(json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def _labor_key(spec: dict, values: dict) -> str:
    excluded = price_fields(spec)
    return _digest(spec["id"], {name: value for name, value in values.items()
                                if name not in excluded and name not in COMMON_FIELDS})


def _statement_key(session: EstimateSession) -> str:
    """원가계산서에 영향을 주는 입력: 기준일·공통 조건·항목별 입력/결과 버전과 품·가격 키."""
    return _digest(session.get("basis_date"),
                   {name: entry["value"] for name, entry in session["common_conditions"].items()},
                   [(item_id, item["input_revision"], item.get("result_revision"), item.get("labor_key"),
                     item.get("price_key")) for item_id, item in
                    ((item_id, session["items"][item_id]) for item_id in session["item_order"])])


def current_estimate(session: EstimateSession) -> dict | None:
    """최신 확정 원가계산서. 입력이 바뀐 뒤 다시 계산하지 않았으면 None(화면·내려받기는 이것만 쓴다)."""
    if session.get("statement") and session.get("statement_key") == _statement_key(session):
        return {"statement": session["statement"], "aggregate_result": session["aggregate_result"]}
    return None


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


def _not_allowed(value, field: dict) -> str:
    """선택지 밖 값의 안내 문구. 명세의 제외 사유(excluded)가 있으면 그대로 쓴다."""
    labels = field.get("labels") or {}
    choices = " / ".join(str(labels.get(v, v)) for v in field.get("allowed_values") or [])
    excluded = (field.get("excluded") or {}).get(str(value))
    if excluded:
        return f"{value}는 이 공종의 적용 범위 밖입니다({excluded}). 가능한 값: {choices}"
    return f"{value}는 선택지에 없습니다. 가능한 값: {choices}" if choices else f"{value}는 허용값이 아닙니다"


def set_conditions(session: EstimateSession, user_text: str, *, values: dict | None = None,
                   quantity: dict | None = None, work: str | None = None, source: str = "text") -> dict:
    """조건·물량·공종 선택을 검증해 반영한다.

    source="text"(LLM이 사용자 문장에서 읽은 값)이면 evidence가 그 문장에 실제로 있어야 한다.
    source="answer"(서버가 낸 질문의 선택지 답)이면 evidence 없이 허용값만 검사한다.
    """
    item = _item(session)
    said = _norm(user_text or "")
    rejected, applied = {}, {}
    before = (item["input_revision"], session["revision"], item.get("selection"))

    def grounded(entry: dict) -> bool:
        evidence = entry.get("evidence")
        return source == "answer" or (isinstance(evidence, str) and bool(_norm(evidence)) and _norm(evidence) in said)

    def consistent(name: str, value, evidence: str, field: dict | None) -> bool:
        """근거 구절을 서버 파서로 다시 읽어 보낸 값과 같은지 본다(단위·금액 표기 차이는 허용)."""
        if source == "answer":
            return True
        if name in COMMON_FIELDS:
            return str(_extract_common_inputs(evidence).get(name)) == str(value)
        if field is None:  # 공종 확정 전: 값이 근거 구절에 그대로 있어야 한다
            return bool(_norm(str(value))) and _norm(str(value)) in _norm(evidence)
        if quantity_field and name == quantity_field["name"]:
            return (_fraction(value), unit_key(field.get("unit"))) in _quantities(evidence)
        if field["type"] in _NUMERIC:
            if value == "모름":
                return "모름" in _norm(evidence)
            return _fraction(value) in _numbers(evidence)
        return extract_inputs(evidence, {**spec, "inputs": [field]})[0].get(name, _MISSING) == value

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
        elif source != "answer" and (_fraction(quantity.get("value")), unit_key(quantity.get("unit"))) \
                not in _quantities(quantity["evidence"]):
            rejected["quantity"] = "물량 값·단위가 근거와 다릅니다"
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
        field = fields.get(name)
        if field and field.get("labels") and value not in field["allowed_values"]:
            raw = [key for key, label in field["labels"].items() if label == value]
            value = raw[0] if len(raw) == 1 else value
        if not isinstance(entry, dict) or not grounded(entry):
            rejected[name] = "원문에 근거가 없습니다"
        elif spec and name not in fields and name not in COMMON_FIELDS:
            rejected[name] = "이 공종에 없는 조건입니다"
        elif field and not _valid_for_field(value, field):
            # 근거 대조보다 먼저 본다: '25m'처럼 선택지 밖 값은 파서가 못 읽어 '근거와 다름'으로 잘못 안내된다.
            rejected[name] = _not_allowed(value, field)
        elif not consistent(name, value, entry.get("evidence") or "", field):
            rejected[name] = "값이 근거와 다릅니다"
        elif name in COMMON_FIELDS:
            try:
                set_common(session, name, value)
                applied[name] = value
            except PlanError:
                rejected[name] = "허용값이 아닙니다"
        elif spec is None:
            set_explicit(item, name, value, source)  # 공종이 정해지면 choose_work가 호환 값만 남긴다
            applied[name] = value
        else:
            if quantity_field and name == quantity_field["name"]:
                set_quantity(item, value, quantity_field.get("unit"), source)
                applied[name] = item["quantity"]["value"]
            else:
                if field["type"] in ("positive_rational", "positive_currency") and value != "모름":
                    value = _format_rational(Fraction(str(value).replace(",", "")))
                set_explicit(item, name, value, source)
                applied[name] = value
    if (item["input_revision"], session["revision"], item.get("selection")) != before:
        # 입력이 실제로 바뀌면 이전 원가계산서는 최신 결과가 아니다(다시 estimate_cost를 불러야 한다).
        # 같은 값을 다시 넣은 경우(LLM이 같은 물량을 한 번 더 보냄)는 최신 견적을 버리지 않는다.
        session.update(statement=None, aggregate_result=None, statement_key=None)
    # 요청했지만 적용하지 않은 값. 응답 문장이 '적용하지 않았다'고 설명할 때만 이 숫자를 허용한다(reply_check).
    requested = {**{name: entry.get("value") for name, entry in (values or {}).items() if isinstance(entry, dict)},
                 "quantity": f"{quantity.get('value')}{quantity.get('unit') or ''}" if isinstance(quantity, dict) else None,
                 "work": work}
    refused = {name: str(requested[name]) for name in rejected if requested.get(name) not in (None, "")}
    return _result("ok", item, {"applied": applied, "dropped": item.get("dropped_conditions", []), "refused": refused},
                   rejected=rejected)


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
    # price_unit은 품 결과와 장비 규격(품 조건)·가격 조건·기준일만 읽는다. 공통 조건이 바뀌어도 다시 하지 않는다.
    key = _digest(item["labor_key"], {name: conditions.get(name) for name in sorted(price_fields(spec))}, basis)
    if not (item.get("priced_result") and item.get("price_key") == key
            and item.get("result_revision") == item["input_revision"]):
        common = {name: entry["value"] for name, entry in session["common_conditions"].items()}
        priced = price_unit(spec, item["computed_result"]["unit_lines"], select_rate_version(basis),
                            {**common, **conditions}, basis)
        item.update(priced_result=priced, price_key=key, result_revision=item["input_revision"])
    item.update(status="PRICED", questions=[], review_status=spec.get("review", ""))
    priced = item["priced_result"]
    session.update(aggregate(session))
    outcome = session["aggregate_result"]
    if outcome["status"] in ("PENDING", "NEEDS_COMMON", "NO_RESULT"):
        session.update(statement=None, statement_key=None)
        return _result("error", item, {"reason": f"원가계산서를 만들 수 없습니다({outcome['status']})",
                                       "priced": priced})
    session["statement_key"] = _statement_key(session)
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
    # 계산 방식마다 근거 구조가 다르다(daily_crew: daily_volume_m3·person_days…, per_unit: unit_rates).
    # 방식별 키를 가정하지 않고 provenance 전체와 품 줄에서 citations를 모은다.
    for citation in [*_citations_in(result.get("provenance", {})),
                     *(citation for line in result["unit_lines"] for citation in line.get("citations", []))]:
        key = json.dumps(citation, ensure_ascii=False, sort_keys=True, default=str)
        if key not in seen:
            seen.add(key)
            citations.append(citation)
    return _result("ok", item, {"spec_id": item["selected_spec_id"], "citations": citations,
                                "memos": result.get("adjustment_memos", [])})


def _citations_in(node) -> list[dict]:
    if isinstance(node, dict):
        found = list(node.get("citations") or [])
        return found + [c for key, value in node.items() if key != "citations" for c in _citations_in(value)]
    if isinstance(node, list):
        return [c for value in node for c in _citations_in(value)]
    return []


def search_standard(query: str, hits: list[dict] | None = None) -> dict:
    """품셈 원문 자료만 돌려준다. 답변 문장은 만들지 않는다(대화 담당 LLM이 쓴다)."""
    hits = retrieve({"query": query})["hits"] if hits is None else hits
    contexts = build_context(hits, query=query)
    sections = [{"section": context["section"], "truncated": context["truncated"], "text": context["text"],
                 "chunk_ids": [chunk["chunk_id"] for chunk in context["chunks"]]} for context in contexts]
    return {"status": "ok" if sections else "not_found", "data": {"sections": sections},
            "missing": [], "rejected": {}, "revision": None}
