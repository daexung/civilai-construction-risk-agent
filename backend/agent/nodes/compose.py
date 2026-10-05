"""계산이 끝난 상태를 사람이 읽을 설명 문장으로 만든다.

숫자는 모두 state(계산 결과)에서 온다. LLM은 문장만 쓰고, 문장에 있는 모든 숫자가
facts에 있는 표기와 일치할 때만 그 문장을 쓴다. 하나라도 없으면 규칙 기반 기본
문장으로 대신한다. LLM이 꺼져 있거나 실패해도 서비스는 멈추지 않는다.
"""

from __future__ import annotations

import json
import re
import time
from decimal import Decimal

from backend.agent.nodes.fill import _common_fields
from backend.agent.rules.specs import load_specs
from backend.agent.state import AgentState
from backend.agent.tools.llm import client as llm_client

COMPOSE_STATUSES = {"OK", "PARTIAL", "BLOCKED", "EVIDENCE_ONLY", "OUT_OF_SCOPE"}

SYSTEM_PROMPT = (
    "당신은 건설 표준품셈 기반 공사비 계산 결과의 설명 담당입니다. "
    "facts(JSON)에 있는 숫자만 사용해 한국어로 최대 두 문장으로 답하세요. "
    "첫 문장에는 공종, 물량, 전체 물량 기준 부가세 포함 도급액을 말하고 조건 요약은 반복하지 마세요. "
    "미산정 항목이 있으면 두 번째 문장에는 항목 이름만 나열하세요. "
    "제외 항목이나 제외 사유, 시장 가격 차이는 설명하지 마세요. "
    "새로운 숫자나 금액을 만들거나 계산하지 말고, 금액에는 물량 기준을 함께 밝혀 주세요."
)

NUMBER_PATTERN = re.compile(r"\d+(?:-\d+){2}(?!\d)|\d[\d,]*(?:\.\d+)?(?:/\d+)?")


def _won(value: str | int | None) -> str | None:
    if value is None:
        return None
    amount = Decimal(str(value))
    rendered = format(amount, ",f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return f"{rendered}원"


def _label(field: dict) -> str:
    match = re.search(r"^(.+?)(?:은|는|이|가)\s", field.get("ask", ""))
    return match.group(1) if match else field["name"]


def _percent(rate: str) -> str:
    value = (Decimal(rate) * 100).normalize()
    return f"{format(value, 'f')}%"


def _josa(word: str, pair: str) -> str:
    """Select a Korean particle using the final Hangul syllable before punctuation."""
    left, right = pair.split("/", 1)
    value = word.rstrip(" \t.,!?…:;\"'”’")
    if value.endswith(")"):
        opening = value.rfind("(")
        if opening >= 0:
            value = value[:opening].rstrip()
    final = value[-1] if value else ""
    has_batchim = "가" <= final <= "힣" and (ord(final) - 0xAC00) % 28 != 0
    return left if has_batchim else right


def condition_summary(inputs: dict) -> str:
    """'토목 · 1~6개월 · 종합건설업 · 단독 공사' 형태의 조건 요약."""
    fields = {field["name"]: field for field in _common_fields()}
    category = inputs.get("work_category", fields["work_category"]["default"])
    group = next((name for name, values in fields["work_category"]["groups"].items() if category in values), category)
    scale = inputs.get("project_scale", "이 견적만")
    scale_text = "단독 공사" if scale == "이 견적만" else f"전체 공사 {int(scale):,}원"
    return " · ".join([group, inputs.get("duration", fields["duration"]["default"]),
                       inputs.get("contractor_type", fields["contractor_type"]["default"]), scale_text])


def _spec(state: AgentState) -> dict | None:
    spec_id = state.get("spec_id")
    return load_specs().get(spec_id) if spec_id else None


def _work_facts(state: AgentState, spec: dict | None) -> dict | None:
    if spec is None:
        return None
    selection = state.get("selection", {})
    return {"section_no": selection.get("section_no") or spec["section_no"],
            "title": selection.get("section") or spec["title"]}


def _inputs_facts(state: AgentState, spec: dict | None) -> list[dict]:
    if spec is None:
        return []
    by_name = {field["name"]: field for field in spec["inputs"]}
    out = []
    for name, value in state.get("inputs", {}).items():
        field = by_name.get(name)
        out.append({"name": name, "label": _label(field) if field else name, "value": value})
    return out


def _line_fact(line: dict, unit: str = "㎥") -> dict:
    fact = {"category": line.get("category"), "name": line.get("name"), "unit": line.get("unit"),
            "quantity": line.get("quantity"),
            "unit_price": f"단가 {_won(line['unit_price'])}" if line.get("unit_price") is not None else None,
            "amount": f"1{unit}당 {_won(line['amount'])}" if line.get("amount") is not None else None,
            "reason": line.get("reason")}
    rate = line.get("rate")
    if rate is not None:
        fact["rate_percent"] = _percent(rate)
    return fact


def _citation_labels(citations: list[dict]) -> list[str]:
    labels: list[str] = []
    for citation in citations:
        label = (citation.get("label") or "").split("\n")[0]
        if label and label not in labels:
            labels.append(label)
    return labels[:20]


def _priced_citations(priced: dict) -> list[dict]:
    collected = list(priced.get("total_citations", []))
    for key in ("lines", "equipment_lines", "cost_lines"):
        for line in priced.get(key, []):
            collected += line.get("citations", [])
    return collected


def _priced_facts(priced: dict | None, unit: str = "㎥") -> dict | None:
    if not priced:
        return None
    lines = [_line_fact(line, unit) for line in priced.get("lines", []) if line.get("kind") != "equipment"]
    lines += [_line_fact(line, unit) for line in priced.get("equipment_lines", [])]
    lines += [_line_fact(line, unit) for line in priced.get("cost_lines", [])]
    excluded = [{"name": item["name"], "reason": item["reason"]} for item in priced.get("excluded", [])]
    unpriced = [{"name": item["name"], "reason": item["reason"]} for item in priced.get("unpriced", [])]
    rate_version = priced.get("rate_version")
    equipment_rate_version = priced.get("equipment_rate_version")
    reference = priced.get("reference_amounts") or {}
    volume = reference.get("volume")
    reference_label = f"{volume}{unit} 기준 참고 금액(부분)" if priced.get("partial") else f"{volume}{unit} 기준 참고 금액"
    return {
        "lines": lines,
        f"1{unit}당 소계": {f"1{unit}당 {name} 소계": _won(value)
                       for name, value in (priced.get("unit_prices") or priced.get("subtotals") or {}).items()},
        f"1{unit}당 합계(부분)" if priced.get("partial") else f"1{unit}당 합계": _won(priced.get("total")),
        reference_label: _won(reference.get("total")),
        "물량 기준 참고 소계": {f"{volume}{unit} 기준 {name} 소계(부분)" if priced.get("partial")
                              else f"{volume}{unit} 기준 {name} 소계": _won(value)
                              for name, value in reference.get("subtotals", {}).items()},
        "partial": priced.get("partial"),
        "excluded": excluded, "excluded_count": len(excluded),
        "unpriced": unpriced, "unpriced_count": len(unpriced),
        "rate_version": {"id": rate_version["id"], "effective_from": rate_version["effective_from"]}
                        if rate_version else None,
        "equipment_rate_version": {"version": equipment_rate_version["version"],
                                    "published": equipment_rate_version["published"]}
                                   if equipment_rate_version else None,
    }


def _statement_facts(statement: dict | None) -> dict | None:
    if not statement:
        return None
    totals = statement.get("totals") or {}
    total_names = {
        "materials": "전체 물량 기준 재료비",
        "labor": "전체 물량 기준 노무비",
        "expenses": "전체 물량 기준 경비",
        "net_cost": "전체 물량 기준 순공사원가",
        "management": "전체 물량 기준 일반관리비",
        "profit": "전체 물량 기준 이윤",
        "total_cost": "전체 물량 기준 총원가",
        "vat": "전체 물량 기준 부가가치세",
        "contract_amount": "전체 물량 기준 도급액(부가세 포함)",
    }
    return {
        "status": statement.get("status"),
        "basis_date": statement.get("basis_date"),
        "overhead_version": statement.get("overhead_version"),
        "conditions": statement.get("conditions"),
        "totals": {label: _won(totals[key]) for key, label in total_names.items() if key in totals},
        "lines": [{"name": line.get("name"), "category": line.get("category"),
                   "base": line.get("base"),
                   "전체 물량 기준 기준액": _won(line.get("base_amount")),
                   "rate": f"{line['rate']}%" if line.get("rate") is not None else None,
                   "전체 물량 기준 금액": _won(line.get("amount")), "note": line.get("note")}
                  for line in statement.get("lines", [])],
        "excluded": statement.get("excluded", []),
        "unpriced": statement.get("unpriced", []),
        "basis_notes": statement.get("basis_notes", []),
        "reason": statement.get("reason"),
    }


def _evidence_facts(state: AgentState) -> list[dict]:
    return [{"section_no": hit["section_no"], "section": hit["section"], "page": hit["page"],
             "snippet": hit["text"]} for hit in state.get("hits", [])[:3]]


def build_facts(state: AgentState) -> dict:
    """숫자 잠금 검사와 LLM·기본 문장이 함께 쓰는 사실 모음을 만든다."""
    status = state.get("status")
    spec = _spec(state)
    facts: dict = {"status": status, "work": _work_facts(state, spec), "reason": state.get("reason")}
    if status in ("OK", "PARTIAL"):
        priced = state.get("priced") or {}
        facts["inputs"] = _inputs_facts(state, spec)
        inputs = state.get("inputs", {})
        sources = state.get("input_sources", {})
        facts["condition_summary"] = condition_summary(inputs)
        facts["condition_default"] = all(sources.get(field["name"]) == "기본값" for field in _common_fields())
        facts["input_count"] = len(facts["inputs"])
        quantity_input = (spec or {}).get("quantity_model", {}).get("params", {}).get("quantity_input")
        facts["quantity"] = inputs.get(quantity_input) if quantity_input else None
        unit = next((field["unit"] for field in spec["inputs"]
                     if field["name"] == spec["quantity_model"]["params"]["quantity_input"]), "㎥") if spec else "㎥"
        facts["unit"] = unit
        facts["priced"] = _priced_facts(priced, unit)
        facts["statement"] = _statement_facts(state.get("statement"))
        facts["citation_labels"] = _citation_labels(_priced_citations(priced))
    elif status == "BLOCKED":
        result = state.get("result") or {}
        facts["blocked"] = {"reason": result.get("reason"), "source": result.get("source"),
                            "input": result.get("input")}
        facts["citation_labels"] = _citation_labels(result.get("citations", []))
    elif status == "EVIDENCE_ONLY":
        facts["evidence"] = _evidence_facts(state)
    return facts


def _template_priced(facts: dict) -> str:
    work = facts.get("work")
    label = work["title"] if work else "공사"
    priced = facts.get("priced") or {}
    statement = facts.get("statement") or {}
    quantity = facts.get("quantity")
    quantity_text = f"{quantity}{facts.get('unit', '㎥')} " if quantity is not None else ""
    totals = statement.get("totals") or {}
    contract_amount = totals.get("전체 물량 기준 도급액(부가세 포함)")
    if contract_amount is not None:
        sentences = [f"{label} {quantity_text}전체 물량 기준 부가세 포함 도급액은 {contract_amount}입니다."]
    else:
        unit = facts.get("unit", "㎥")
        total = priced.get(f"1{unit}당 합계(부분)") or priced.get(f"1{unit}당 합계")
        sentences = [f"{label} {total}입니다."] if total is not None else [f"{label}은(는) 현재 적용 가능한 단가가 없어 금액을 계산하지 못했습니다."]
    unpriced = list(dict.fromkeys(item["name"] for item in [*(priced.get("unpriced") or []), *(statement.get("unpriced") or [])]))
    if unpriced:
        sentences.append("미산정 항목: " + ", ".join(unpriced) + ".")
    return " ".join(sentences)



def _template_blocked(facts: dict) -> str:
    work = facts.get("work")
    label = f"{work['title']}({work['section_no']})" if work else "이번 계산"
    blocked = facts.get("blocked") or {}
    reason = blocked.get("reason") or facts.get("reason") or "원문 근거가 불명확합니다"
    return f"{label} 계산은 보류합니다. 사유: {reason}"


def _template_evidence(facts: dict) -> str:
    reason = facts.get("reason") or "아직 계산을 지원하지 않는 공종입니다"
    evidence = facts.get("evidence") or []
    if evidence:
        sources = "; ".join(f"{item['section']}(PDF {item['page']}쪽)" for item in evidence)
        return f"{reason} 관련 근거: {sources}."
    return reason


def _template_out_of_scope(facts: dict) -> str:
    reason = facts.get("reason") or "공사비·품셈 계산과 관련이 없는 질문입니다"
    return f"{reason} 공사비 계산과 관련된 질문으로 다시 문의해 주세요."


def build_template(facts: dict) -> str:
    status = facts.get("status")
    if status in ("OK", "PARTIAL"):
        return _template_priced(facts)
    if status == "BLOCKED":
        return _template_blocked(facts)
    if status == "EVIDENCE_ONLY":
        return _template_evidence(facts)
    if status == "OUT_OF_SCOPE":
        return _template_out_of_scope(facts)
    return facts.get("reason") or ""


def _normalize_number(token: str) -> str:
    if re.fullmatch(r"\d+(?:-\d+){2}", token):
        return token
    token = token.replace(",", "")
    if "." in token and "/" not in token:
        token = token.rstrip("0").rstrip(".")
        if token in ("", "-"):
            token = "0"
    return token


def _numbers_in(text: str) -> set[str]:
    return {_normalize_number(token) for token in NUMBER_PATTERN.findall(text)}


def validate_numbers(text: str, facts: dict) -> tuple[bool, list[str]]:
    """문장의 모든 숫자가 facts 안의 숫자 표기와 일치해야 통과한다."""
    allowed = _numbers_in(json.dumps(facts, ensure_ascii=False))
    found = _numbers_in(text)
    bad = sorted(found - allowed)
    return not bad, bad


def validate_amount_basis(text: str) -> bool:
    """Require each currency amount to carry an adjacent quantity basis."""
    for match in re.finditer(r"\d[\d,]*(?:\.\d+)?\s*원", text):
        context = text[max(0, match.start() - 24):match.start()]
        if not re.search(r"(?:1\s*[㎥㎡]\s*당|[㎥㎡]\s*기준|전체\s*물량\s*기준)", context):
            return False
    return True


def unpriced_names(facts: dict) -> list[str]:
    names: list[str] = []
    for source in (facts.get("priced") or {}, facts.get("statement") or {}):
        for item in source.get("unpriced") or []:
            if item["name"] not in names:
                names.append(item["name"])
    return names


def validate_unpriced(text: str, facts: dict) -> list[str]:
    """문장에 이름이 나오지 않은 미산정 항목을 돌려준다."""
    return [name for name in unpriced_names(facts) if name not in text]


def _prompt(facts: dict) -> str:
    return "다음 계산 결과를 설명해 주세요.\n\nfacts:\n" + json.dumps(facts, ensure_ascii=False, indent=2)


def compose(state: AgentState, generate_fn=None) -> dict:
    status = state.get("status")
    if status not in COMPOSE_STATUSES:
        return {}
    facts = build_facts(state)
    template_text = build_template(facts)
    fn = generate_fn or llm_client.generate
    try:
        provider = llm_client.provider_name()
    except llm_client.LLMUnavailable:
        provider = None
    try:
        model = llm_client.model_name()
    except llm_client.LLMUnavailable:
        model = None
    llm_info = {"provider": provider, "model": model, "elapsed_ms": None,
                "attempts": 0, "error": None, "bad_numbers": []}
    start = time.monotonic()
    try:
        generated = fn(_prompt(facts), SYSTEM_PROMPT)
        if isinstance(generated, llm_client.LLMResult):
            text = generated.text
            llm_info["provider"] = generated.provider
            llm_info["attempts"] = generated.attempts
        else:
            text = generated
            llm_info["attempts"] = 1
    except Exception as exc:  # 키 없음·한도 초과·시간 초과 등 무엇이 와도 기본 문장으로 대신한다
        llm_info["elapsed_ms"] = round((time.monotonic() - start) * 1000)
        llm_info["attempts"] = getattr(exc, "attempts", 1)
        llm_info["provider"] = getattr(exc, "provider", None) or llm_info["provider"]
        llm_info["error"] = str(exc) if isinstance(exc, llm_client.LLMUnavailable) \
            else f"{type(exc).__name__}: {str(exc)[:200]}"
        return {"answer": template_text, "answer_source": "template", "llm_info": llm_info}
    llm_info["elapsed_ms"] = round((time.monotonic() - start) * 1000)
    ok, bad = validate_numbers(text, facts)
    if not ok:
        llm_info["error"] = "숫자 불일치"
        llm_info["bad_numbers"] = bad
        return {"answer": template_text, "answer_source": "template", "llm_info": llm_info}
    if not validate_amount_basis(text):
        llm_info["error"] = "금액 기준 누락"
        return {"answer": template_text, "answer_source": "template", "llm_info": llm_info}
    if validate_unpriced(text, facts):
        llm_info["error"] = "미산정 누락"
        return {"answer": template_text, "answer_source": "template", "llm_info": llm_info}
    return {"answer": text, "answer_source": "llm", "llm_info": llm_info}
