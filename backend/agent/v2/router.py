"""v2 라우터: 뜻은 AI가 고르고, 사실은 코드가 확인한다.

- 버튼 카드 답은 라우터를 거치지 않고 견적 에이전트로 바로 간다(AI 호출 0).
- 글로 쓴 문장은 항상 AI가 정해진 스키마(enum)로 판단한다.
- 코드는 근거 글자가 문장에 있는지, 카드 값이 허용 목록에 있는지 같은 사실만 확인한다.
- 확인 실패면 오류 목록을 붙여 한 번만 고쳐 달라고 하고, 그래도 틀리면 실패로 돌려준다.
- 낱말 규칙으로 갈래를 대신 정하지 않는다. 실패는 실패로 보인다.

설계 원본: 노션 '에이전트 v2 설계' 0-1 라우터.
아직 운영 경로에 연결하지 않았다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel, ValidationError

PROMPT_DIR = Path(__file__).parent / "prompts" / "router"
MAX_CALLS = 2  # 첫 판단 1 + 고치기 1


# ---- 입력 ----
class Question(BaseModel):
    question_id: str
    ask: str
    allowed_values: list[str]


class Previous(BaseModel):
    kind: str  # needs_input | estimate_result | qa_answer ...
    work: str | None = None
    pending_questions: list[Question] = []
    last_answer_summary: str = ""


class RouterInput(BaseModel):
    message: str
    previous: Previous | None = None


# ---- 출력 ----
class Target(BaseModel):
    user_text: str
    evidence: str
    search_terms: list[str]


class Quantity(BaseModel):
    value: str
    unit: str
    evidence: str


class Condition(BaseModel):
    text: str
    evidence: str


class CardAnswer(BaseModel):
    question_id: str
    value: str
    evidence: str


class Request(BaseModel):
    id: str
    kind: Literal["estimate", "qa"]
    estimate_mode: Literal["new", "change", "ask_about", "card_answer", "none"]
    target: Target | None
    quantity: Quantity | None
    conditions: list[Condition]
    asks: str
    wants: Literal["explain", "value", "calculate"]  # 사용자가 원하는 결과
    card_answer: CardAnswer | None


class Clarify(BaseModel):
    ask: str
    options: list[str]


class RouterOutput(BaseModel):
    route: Literal["work", "out_of_scope", "clarify"]
    requests: list[Request]
    clarify: Clarify | None
    out_of_scope_kind: Literal["unrelated", "chitchat", "none"]
    confidence: float


# Gemini response_schema (pydantic 스키마는 $defs/anyOf라 직접 쓴다)
def _obj(props: dict, nullable: bool = False) -> dict:
    out = {"type": "object", "properties": props, "required": list(props)}
    if nullable:
        out["nullable"] = True
    return out


_S = {"type": "string"}
_SL = {"type": "array", "items": _S}
RESPONSE_SCHEMA = _obj({
    "route": {"type": "string", "enum": ["work", "out_of_scope", "clarify"]},
    "requests": {"type": "array", "items": _obj({
        "id": _S,
        "kind": {"type": "string", "enum": ["estimate", "qa"]},
        "estimate_mode": {"type": "string", "enum": ["new", "change", "ask_about", "card_answer", "none"]},
        "target": _obj({"user_text": _S, "evidence": _S, "search_terms": _SL}, nullable=True),
        "quantity": _obj({"value": _S, "unit": _S, "evidence": _S}, nullable=True),
        "conditions": {"type": "array", "items": _obj({"text": _S, "evidence": _S})},
        "asks": _S,
        "wants": {"type": "string", "enum": ["explain", "value", "calculate"]},
        "card_answer": _obj({"question_id": _S, "value": _S, "evidence": _S}, nullable=True),
    })},
    "clarify": _obj({"ask": _S, "options": _SL}, nullable=True),
    "out_of_scope_kind": {"type": "string", "enum": ["unrelated", "chitchat", "none"]},
    "confidence": {"type": "number"},
})


# ---- 프롬프트 ----
def load_system_prompt() -> str:
    system = (PROMPT_DIR / "system.md").read_text(encoding="utf-8")
    lines = ["", "## 예시 (지어낸 예시다. 형식과 판단 방식만 참고한다)", ""]
    for raw in (PROMPT_DIR / "examples.jsonl").read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        ex = json.loads(raw)
        lines.append(f"입력: {json.dumps(ex['input'], ensure_ascii=False)}")
        lines.append(f"출력: {json.dumps(ex['output'], ensure_ascii=False)}")
        lines.append("")
    return system + "\n".join(lines)


def build_prompt(inp: RouterInput) -> str:
    return "입력: " + inp.model_dump_json()


def build_repair_prompt(inp: RouterInput, bad_text: str, errors: list[str]) -> str:
    return (build_prompt(inp) + "\n\n직전 출력: " + bad_text
            + "\n\n직전 출력이 아래 규칙을 어겼다. 고친 JSON 전체를 다시 내라.\n- " + "\n- ".join(errors))


# ---- 사실 확인 ----
def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def validate(out: RouterOutput, inp: RouterInput) -> list[str]:
    """AI 판단을 뒤집지 않는다. 문장·카드와 맞지 않는 사실만 오류로 모은다."""
    errors: list[str] = []
    msg = _squash(inp.message)
    prev = inp.previous
    pending = {q.question_id: q for q in (prev.pending_questions if prev else [])}
    has_estimate = bool(prev and prev.work)

    def check_evidence(where: str, ev: str):
        if not _squash(ev):
            errors.append(f"{where}: evidence가 비었다")
        elif _squash(ev) not in msg:
            errors.append(f"{where}: evidence '{ev}'가 사용자 문장에 그대로 없다")

    if out.route == "work" and not out.requests:
        errors.append("route=work인데 requests가 비었다")
    if out.route != "work" and out.requests:
        errors.append(f"route={out.route}인데 requests가 있다")
    if out.route == "clarify":
        if out.clarify is None or not out.clarify.ask.strip():
            errors.append("route=clarify인데 clarify.ask가 비었다")
    elif out.clarify is not None:
        errors.append(f"route={out.route}인데 clarify가 null이 아니다")
    if (out.route == "out_of_scope") != (out.out_of_scope_kind != "none"):
        errors.append("out_of_scope_kind는 route=out_of_scope일 때만 none이 아니다")
    if not 0 <= out.confidence <= 1:
        errors.append("confidence는 0~1이다")

    ids = [r.id for r in out.requests]
    if len(ids) != len(set(ids)):
        errors.append("requests id가 겹친다")

    for r in out.requests:
        at = f"requests[{r.id}]"
        if r.kind == "qa" and r.estimate_mode != "none":
            errors.append(f"{at}: qa면 estimate_mode는 none이다")
        if r.kind == "estimate" and r.estimate_mode == "none":
            errors.append(f"{at}: estimate면 estimate_mode가 none일 수 없다")
        if r.estimate_mode == "new" and r.target is None:
            errors.append(f"{at}: 새 견적인데 target이 없다(모르면 clarify)")
        if r.estimate_mode in ("change", "ask_about") and not has_estimate:
            errors.append(f"{at}: 진행 중 견적이 없는데 {r.estimate_mode}이다")
        if (r.estimate_mode == "card_answer") != (r.card_answer is not None):
            errors.append(f"{at}: card_answer는 estimate_mode=card_answer일 때만 채운다")
        if r.card_answer is not None:
            q = pending.get(r.card_answer.question_id)
            if q is None:
                errors.append(f"{at}: question_id '{r.card_answer.question_id}'인 떠 있는 카드가 없다")
            elif r.card_answer.value not in q.allowed_values:
                errors.append(f"{at}: 값 '{r.card_answer.value}'는 허용 값 {q.allowed_values}에 없다")
            check_evidence(f"{at}.card_answer", r.card_answer.evidence)
        if r.target is not None:
            check_evidence(f"{at}.target", r.target.evidence)
        if r.quantity is not None:
            check_evidence(f"{at}.quantity", r.quantity.evidence)
            if _squash(r.quantity.value).replace(",", "") not in msg.replace(",", ""):
                errors.append(f"{at}: 물량 숫자 '{r.quantity.value}'가 문장에 없다")
            if r.quantity.unit and _squash(r.quantity.unit) not in msg:
                errors.append(f"{at}: 단위 '{r.quantity.unit}'가 문장에 없다")
        for i, c in enumerate(r.conditions):
            check_evidence(f"{at}.conditions[{i}]", c.evidence)
    return errors


# ---- 보내기 ----
def dispatch(out: RouterOutput) -> list[dict]:
    """코드는 enum 값만 보고 다음 노드를 고른다."""
    if out.route == "out_of_scope":
        return [{"node": "out_of_scope_reply", "kind": out.out_of_scope_kind}]
    if out.route == "clarify":
        return [{"node": "clarify_reply", "ask": out.clarify.ask if out.clarify else ""}]
    node = {"estimate": "estimate_agent", "qa": "qa_agent"}
    return [{"node": node[r.kind], "request_id": r.id} for r in out.requests]


# ---- 한 턴 ----
def route_turn(
    message: str,
    previous: dict | None = None,
    *,
    button: dict | None = None,
    generate: Callable | None = None,
) -> dict:
    """결과: {status, output, dispatch, errors, calls_used}.

    status: ok(통과) | output_error(출력 오류: 고치기 후에도 규칙 위반) | failed(처리 실패: AI 호출 불가)
    """
    inp = RouterInput(message=message, previous=previous)

    if button is not None:  # 버튼 카드 답: 라우터 생략, 값만 확인
        pending = {q.question_id: q for q in (inp.previous.pending_questions if inp.previous else [])}
        q = pending.get(button.get("question_id"))
        if q is None or button.get("value") not in q.allowed_values:
            return {"status": "output_error", "output": None, "dispatch": [],
                    "errors": ["버튼 답이 떠 있는 카드·허용 값과 맞지 않는다"], "calls_used": 0}
        return {"status": "ok", "output": None, "calls_used": 0, "errors": [],
                "dispatch": [{"node": "estimate_agent", "card_answer": dict(button)}]}

    if generate is None:
        from backend.agent.tools.llm.client import generate
    from backend.agent.tools.llm.client import LLMUnavailable

    system = load_system_prompt()
    prompt = build_prompt(inp)
    errors: list[str] = []
    calls = 0
    while calls < MAX_CALLS:
        calls += 1
        try:
            result = generate(prompt, system, response_schema=RESPONSE_SCHEMA,
                              timeout_ms=8000, max_attempts=2, retry_delays=[0.5])
        except LLMUnavailable as exc:
            return {"status": "failed", "output": None, "dispatch": [],
                    "errors": [f"AI 호출 실패: {exc}"], "calls_used": calls}
        text = getattr(result, "text", result)
        try:
            out = RouterOutput.model_validate_json(text)
            errors = validate(out, inp)
        except ValidationError as exc:
            out, errors = None, [f"스키마 위반: {e['loc']} {e['msg']}" for e in exc.errors()[:5]]
        if not errors:
            return {"status": "ok", "output": out.model_dump(), "dispatch": dispatch(out),
                    "errors": [], "calls_used": calls}
        prompt = build_repair_prompt(inp, text, errors)
    return {"status": "output_error", "output": None, "dispatch": [], "errors": errors, "calls_used": calls}
