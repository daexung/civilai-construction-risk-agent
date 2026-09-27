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

from agent.rules.specs import load_specs
from agent.state import AgentState
from agent.tools.llm import client as llm_client

COMPOSE_STATUSES = {"OK", "PARTIAL", "BLOCKED", "EVIDENCE_ONLY", "OUT_OF_SCOPE"}

SYSTEM_PROMPT = (
    "당신은 건설 표준품셈 기반 공사비 계산 도우미의 설명 담당입니다. "
    "아래 facts(JSON)에 있는 숫자만 사용해 한국어로 3~6문장의 설명을 쓰세요. "
    "현장 공무 담당자에게 설명하듯 자연스러운 문장으로 쓰고, 표를 다시 나열하지 마세요. "
    "facts는 JSON 자료 구조일 뿐이니 amount·unit_price 같은 영어 필드 이름을 문장에 그대로 "
    "쓰지 말고 자연스러운 한국어로 바꿔 부르세요(예: 소계, 합계, 금액). "
    "새로운 숫자·단가·금액을 추정하거나 만들어내지 마세요. 금액의 숫자 값 자체는 facts에 "
    "있는 표기를 그대로 쓰고 임의로 반올림하거나 계산하지 마세요. "
    "unit_price처럼 소수점이 긴 값은 가능하면 인용하지 말고 금액·합계 위주로 설명하세요. "
    "계산 금액이 있다면 '표준품셈 기준 금액이며 시장 가격과 다를 수 있다'는 점을 반드시 "
    "언급하고, 제외 항목이나 미산정 항목이 있다면 그 이름과 사유를 반드시 언급하세요."
)

NUMBER_PATTERN = re.compile(r"\d+(?:-\d+){2}(?!\d)|\d[\d,]*(?:\.\d+)?(?:/\d+)?")


def _label(field: dict) -> str:
    match = re.search(r"^(.+?)(?:은|는|이|가)\s", field.get("ask", ""))
    return match.group(1) if match else field["name"]


def _percent(rate: str) -> str:
    value = (Decimal(rate) * 100).normalize()
    return f"{format(value, 'f')}%"


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


def _line_fact(line: dict) -> dict:
    fact = {"category": line.get("category"), "name": line.get("name"), "unit": line.get("unit"),
            "quantity": line.get("quantity"), "unit_price": line.get("unit_price"),
            "amount": line.get("amount"), "reason": line.get("reason")}
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


def _priced_facts(priced: dict | None) -> dict | None:
    if not priced:
        return None
    lines = [_line_fact(line) for line in priced.get("lines", []) if line.get("kind") != "equipment"]
    lines += [_line_fact(line) for line in priced.get("equipment_lines", [])]
    lines += [_line_fact(line) for line in priced.get("cost_lines", [])]
    excluded = [{"name": item["name"], "reason": item["reason"]} for item in priced.get("excluded", [])]
    unpriced = [{"name": item["name"], "reason": item["reason"]} for item in priced.get("unpriced", [])]
    rate_version = priced.get("rate_version")
    equipment_rate_version = priced.get("equipment_rate_version")
    return {
        "lines": lines,
        "소계": priced.get("subtotals"),
        "합계": priced.get("total"),
        "partial": priced.get("partial"),
        "excluded": excluded, "excluded_count": len(excluded),
        "unpriced": unpriced, "unpriced_count": len(unpriced),
        "rate_version": {"id": rate_version["id"], "effective_from": rate_version["effective_from"]}
                        if rate_version else None,
        "equipment_rate_version": {"version": equipment_rate_version["version"],
                                    "published": equipment_rate_version["published"]}
                                   if equipment_rate_version else None,
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
        facts["input_count"] = len(facts["inputs"])
        facts["priced"] = _priced_facts(priced)
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
    label = f"{work['title']}({work['section_no']})" if work else "이번 계산"
    priced = facts.get("priced") or {}
    total = priced.get("합계")
    subtotals = priced.get("소계") or {}
    sentences = []
    if total is not None:
        sentences.append(
            f"{label} 계산 결과 재료비 {subtotals.get('재료비') or '0'}원, "
            f"노무비 {subtotals.get('노무비') or '0'}원, 경비 {subtotals.get('경비') or '0'}원으로, "
            f"{'미산정 항목을 제외한 부분 합계는' if priced.get('partial') else '합계는'} {total}원입니다."
        )
    else:
        sentences.append(f"{label}은(는) 현재 적용 가능한 단가가 없어 금액을 계산하지 못했습니다.")
    excluded = priced.get("excluded") or []
    if excluded:
        parts = "; ".join(f"{item['name']}({item['reason']})" for item in excluded)
        sentences.append(f"제외 항목: {parts}.")
    unpriced = priced.get("unpriced") or []
    if unpriced:
        parts = "; ".join(f"{item['name']}({item['reason']})" for item in unpriced)
        sentences.append(f"미산정 항목: {parts}.")
    sentences.append("표준품셈 기준 금액이며 시장 가격과 다를 수 있습니다.")
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
        model = llm_client.model_name()
    except llm_client.LLMUnavailable:
        model = None
    llm_info = {"model": model, "elapsed_ms": None, "error": None, "bad_numbers": []}
    start = time.monotonic()
    try:
        text = fn(_prompt(facts), SYSTEM_PROMPT)
    except Exception as exc:  # 키 없음·한도 초과·시간 초과 등 무엇이 와도 기본 문장으로 대신한다
        llm_info["elapsed_ms"] = round((time.monotonic() - start) * 1000)
        llm_info["error"] = str(exc) if isinstance(exc, llm_client.LLMUnavailable) \
            else f"{type(exc).__name__}: {str(exc)[:200]}"
        return {"answer": template_text, "answer_source": "template", "llm_info": llm_info}
    llm_info["elapsed_ms"] = round((time.monotonic() - start) * 1000)
    ok, bad = validate_numbers(text, facts)
    if not ok:
        llm_info["error"] = "숫자 불일치"
        llm_info["bad_numbers"] = bad
        return {"answer": template_text, "answer_source": "template", "llm_info": llm_info}
    return {"answer": text, "answer_source": "llm", "llm_info": llm_info}
