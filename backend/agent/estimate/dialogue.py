"""대화 담당 LLM + 서버 도구 흐름(설계 docs/agent-tool-orchestration-plan.md §2~§8, PR 2).

한 사용자 턴: load_session → agent ⇄ tools → reply → commit.
- 대화 상태(EstimateSession·대기 질문·목표)는 LangGraph 체크포인터에 thread별로 저장한다. 턴 전체가 노드 하나라
  턴 중 예외가 나면 체크포인트가 쓰이지 않아 직전 확정 상태가 그대로 남는다(작업 사본 방식, §8).
- LLM은 행동(JSON)만 고른다. 수치 계산·입력 검증은 estimate/tools.py가 한다.
- source="answer"는 load_session이 현재 대기 질문(question_id·version·revision)에 대한 답임을 확인했을 때만 쓴다.
  LLM이 부르는 set_conditions는 항상 source="text"라 근거 대조를 거친다.
- LLM을 쓸 수 없으면(꺼짐·첫 호출 실패·예산 소진) 같은 도구를 규칙 정책으로 부른다. 기존 그래프로 넘기지 않는다.
"""

from __future__ import annotations

import copy
import json
import os
import re
import time
import unicodedata
from functools import cache
from pathlib import Path
from typing import Callable, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from backend.agent.estimate import reply_check, tools
from backend.agent.estimate.state import COMMON_FIELDS
from backend.agent.rules.specs import load_specs
from backend.agent.nodes.fill import _common_fields, extract_inputs
from backend.agent.nodes.retrieve import get_search
from backend.agent.nodes.route import _rule_route
from backend.agent.tools.calc.format import approx, rounded
from backend.agent.tools.llm import client
from backend.agent.tools.source import citation

PROMPTS = Path(__file__).resolve().parents[1] / "tools/llm/prompts"
# 턴 예산(§6): agent·reply·도구 내부 LLM의 요청 시도(재시도 포함)를 모두 합친 수, 도구 실행 수, 시간.
MAX_LLM_ATTEMPTS, MAX_TOOL_CALLS, TURN_SECONDS = 6, 4, 25
TOOLS = ("find_work", "set_conditions", "compute_labor", "estimate_cost", "explain_basis", "search_standard")
_EVIDENCED = {"type": "object", "properties": {"value": {"type": "string"}, "unit": {"type": "string"},
                                               "evidence": {"type": "string"}}, "required": ["value", "evidence"]}
# 구조화 출력은 속성 없는 object를 빈 {}로 채우므로 인자 모양을 모두 적는다. 조건 값은 목록으로 받는다.
ACTION_SCHEMA = {
    "type": "object",
    "properties": {"action": {"type": "string", "enum": ["call_tool", "reply"]},
                   "tool": {"type": "string", "enum": list(TOOLS)},
                   "args": {"type": "object", "properties": {
                       "values": {"type": "array", "items": {"type": "object", "properties": {
                           "field": {"type": "string"}, "value": {"type": "string"}, "evidence": {"type": "string"}},
                           "required": ["field", "value", "evidence"]}},
                       "quantity": _EVIDENCED, "work": {"type": "string"}, "query": {"type": "string"}}},
                   "reason": {"type": "string"}},
    "required": ["action", "reason"],
}
_TRUE, _FALSE = {"true", "예", "사용", "yes"}, {"false", "아니오", "미사용", "no"}
REPLY_SCHEMA = {
    "type": "object",
    "properties": {"text": {"type": "string"}},
    "required": ["text"],
}
PRICE_LABELS = {"ready_mix_price": "레미콘 단가"}
LABELS = {"quantity": "물량", "work": "공종", **PRICE_LABELS}
TOTAL_LABELS = {"contract_amount": "도급액", "total_cost": "총원가", "net_cost": "순공사원가", "materials": "재료비",
                "labor": "노무비", "expenses": "경비", "management": "일반관리비", "profit": "이윤", "vat": "부가가치세"}
_BASIS_WORDS = re.compile(r"근거|출처|어디서|왜|기준")
# 조회·설명 질문과 변경 요청을 나눈다. 숫자·단위가 있다는 이유만으로 조건을 바꾸지 않는다.
# '1세제곱미터당 몇 명'의 1㎥는 단위당 기준이지 물량이 아니다.
_CHANGE_WORDS = re.compile(r"바꿔|바꾸|바꿀|변경|수정|고쳐|(?:으)?로\s*해|계산해|다시\s*계산|늘려|줄여|추가|빼\s*줘|적용해"
                           r"|(?:이|으)?면\s*(?:얼마|어때|어떻게)")
# 확정된 견적이 있을 때 새 공종을 말했는지 판단한다(특정 표현 목록이 아니라 지금 공종의 낱말과 비교).
_JOSA = ("에서", "으로", "이야", "이요", "하고", "로", "은", "는", "이", "가", "을", "를", "도", "의", "에", "만", "야", "요",
         "과", "와", "랑")
_GENERIC_PREFIX = ("비용", "계산", "얼마", "견적", "공사비", "금액", "알려", "보여", "같은", "조건", "이대로", "그대로", "다시",
                   "지금", "현재", "원가", "도급", "부가세", "포함", "기준", "품셈", "인원", "뽑아", "부탁", "그러면", "어떻게")
_GENERIC = {"해", "해줘", "해주세요", "줘", "좀", "몇", "명", "총", "품", "그럼", "이제", "하면", "할래", "나와", "돼", "이거", "이걸",
            "그거", "이걸로", "그걸로", "전체", "내줘", "주세요", "드나", "드나요", "들어", "드는", "그", "이", "저", "것", "거"}
SCOPE_CURRENT, SCOPE_NEW = "지금 견적으로 계산", "새 견적 시작"
_LOOKUP_WORDS = re.compile(r"몇|얼마|무엇|뭐|어떻게|어디|왜|알려|궁금|\?")


def _lookup_only(message: str) -> bool:
    """조회·설명만 묻는 문장(변경 표현 없음)."""
    return bool(_LOOKUP_WORDS.search(message)) and not _CHANGE_WORDS.search(message)


def _answers_pending(state: DialogueState, message: str) -> bool:
    """대기 중인 서버 질문(붐 길이·물량 등)의 값을 문장으로 답했는지. 그런 답은 조회 질문이 아니다."""
    session, pending = state.get("session"), {question["field"] for question in state.get("pending") or []}
    if not session or not pending:
        return False
    changes = _rule_changes(session, message)
    spec = tools._spec(tools._item(session))
    quantity_name = (tools._quantity_field(spec) or {}).get("name") if spec else None
    return bool(pending & set(changes.get("values") or {})) or (
        "quantity" in changes and bool(pending & {"quantity", quantity_name}))


def _is_lookup(state: DialogueState, message: str) -> bool:
    return _lookup_only(message) and not _answers_pending(state, message)


def _words(text: str) -> list[str]:
    words = []
    for word in re.findall(r"[가-힣A-Za-z]+", unicodedata.normalize("NFKC", text or "")):
        for josa in _JOSA:
            if word.endswith(josa) and len(word) > len(josa) + 1:
                word = word[: -len(josa)]
                break
        words.append(word)
    return words


def _generic(word: str) -> bool:
    return word in _GENERIC or word.startswith(_GENERIC_PREFIX)


@cache
def _work_words() -> frozenset[str]:
    """품셈 전체 공종 제목의 낱말. 지금 공종에 없는 이 낱말이 나오면 다른 공종을 말한 것으로 본다."""
    index = get_search()[0]
    chunks = getattr(index, "chunks", None) or getattr(getattr(index, "bm25", None), "chunks", None) or []
    titles = {chunk.get("section") or "" for chunk in chunks} | {spec.get("section", "") for spec in load_specs().values()}
    return frozenset(word for title in titles for word in _words(title) if len(word) >= 2 and not _generic(word))


def _current_vocabulary(session: dict) -> tuple[str, str]:
    """지금 공종의 낱말: (절 제목, 입력·공통 공사 조건의 선택지·동의어). 질문 문장은 넣지 않는다(설치 같은 일반 낱말이 섞임)."""
    item = tools._item(session)
    spec = tools._spec(item) or {}
    title = " ".join([str((item.get("selection") or {}).get("section") or ""), str(spec.get("section", ""))])
    # 지금 견적의 품 항목(콘크리트공·콘크리트펌프차 등)도 지금 공종의 낱말이다.
    values = [str(line.get("name") or "") for line in (item.get("computed_result") or {}).get("unit_lines") or []]
    for field in [*spec.get("inputs", []), *_common_fields()]:
        allowed = field.get("allowed_values") if isinstance(field.get("allowed_values"), list) else []
        values += [*map(str, allowed), *map(str, (field.get("labels") or {}).values()),
                   *[str(word) for words in (field.get("synonyms") or {}).values() for word in words]]
    return title, " ".join(values)


def _cost_target(session: dict, message: str) -> str:
    """확정된 견적이 있을 때 요청이 어느 견적을 가리키는지: 'current' | 'new' | 'ambiguous'.

    공종을 말하지 않은 요청('비용 계산해줘')은 지금 견적이다. 지금 공종에 없는 공종 낱말만 있으면 새 견적,
    지금 공종 제목의 낱말과 다른 공종 낱말이 섞여 있으면 모호하다(상태를 바꾸지 않고 확인 질문).
    """
    title, values = _current_vocabulary(session)
    words = [word for word in _words(message) if not _generic(word)]
    other = [word for word in words if word not in title and word not in values and word in _work_words()]
    if not other:
        return "current"
    return "ambiguous" if any(word in title for word in words) else "new"


def _confirm_scope(state: DialogueState, message: str) -> dict:
    """모호한 요청: 지금 견적을 그대로 두고 어느 견적인지 묻는다. 고른 답은 run_turn이 처리한다."""
    section = (tools._item(state["session"]).get("selection") or {}).get("section") or "지금 공종"
    question = {"field": "scope", "question_id": "scope", "version": 1, "stage": "scope",
                "choices": [SCOPE_CURRENT, SCOPE_NEW], "labels": None, "decision_table": None, "reason": None,
                "ask": f"지금 견적({section})으로 계산할까요, 새 공종으로 견적을 시작할까요?", "request_text": message}
    return {"status": "needs_input", "data": {}, "missing": [question], "rejected": {}, "confirm_scope": True}


def _confirmed(session: dict | None) -> bool:
    return bool(session and (tools._item(session).get("selection") or {}).get("confirmed"))


def _about_current(session: dict, message: str) -> bool:
    """지금 견적의 품 항목(콘크리트공 등)을 묻는지."""
    lines = (tools._item(session).get("computed_result") or {}).get("unit_lines") or []
    return any(line["name"] in message for line in lines)


class DialogueState(TypedDict, total=False):
    request: dict
    session: dict | None       # EstimateSession(항목 하나)
    pending: list              # 현재 대기 질문(ref 포함)
    pending_revision: int      # 질문을 새로 낼 때마다 오른다. 같은 필드의 예전 질문 답을 거른다
    goal: str | None           # "labor" | "cost"
    route: str | None
    turn: dict                 # 마지막 턴의 답변·출처·예산 기록


def new_dialogue() -> DialogueState:
    return {"session": None, "pending": [], "pending_revision": 0, "goal": None, "route": None, "turn": {}}


class Budget:
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self.clock, self.started, self.attempts, self.tool_calls = clock, clock(), 0, 0
        self.exhausted: str | None = None

    def remaining_ms(self) -> int:
        return int((TURN_SECONDS - (self.clock() - self.started)) * 1000)

    def llm_ok(self) -> bool:
        if self.attempts >= MAX_LLM_ATTEMPTS:
            self.exhausted = "LLM 시도 상한"
        elif self.remaining_ms() <= 500:
            self.exhausted = "시간 상한"
        return self.exhausted is None

    def record(self) -> dict:
        return {"llm_attempts": self.attempts, "tool_calls": self.tool_calls, "exhausted": self.exhausted,
                "elapsed_ms": round((self.clock() - self.started) * 1000)}


def _call_llm(budget: Budget, generate, prompt: dict, system: str, schema: dict) -> dict:
    """예산 안에서 한 번 부른다. 시도 수는 성공·실패 모두 예산에서 뺀다."""
    if not budget.llm_ok():
        raise client.LLMUnavailable(budget.exhausted)
    attempts = min(2, MAX_LLM_ATTEMPTS - budget.attempts)
    try:
        result = generate(json.dumps(prompt, ensure_ascii=False, default=str), system, response_schema=schema,
                          timeout_ms=max(1, budget.remaining_ms()), max_attempts=attempts,
                          retry_delays=[0.3] * (attempts - 1))
    except client.LLMUnavailable as exc:
        budget.attempts += max(1, exc.attempts)
        raise
    budget.attempts += getattr(result, "attempts", 1)
    data = json.loads(result.text if hasattr(result, "text") else result)
    if not isinstance(data, dict):
        raise ValueError("JSON 객체가 아닙니다")
    return data


# ---- load_session: 화면 답 검증 ----

def _label(state: DialogueState, name: str) -> str:
    """안내 문구의 조건 이름. 명세 질문('펌프차 붐 길이는? (…)')에서 이름만 뗀다. 없으면 필드명."""
    if name in LABELS or not state.get("session"):
        return LABELS.get(name, name)
    spec = tools._spec(tools._item(state["session"])) or {}
    field = next((f for f in spec.get("inputs", []) if f["name"] == name), None)
    return re.sub(r"\s*(?:은|는)?\?.*$", "", field["ask"]) if field else name


def _ref(question: dict, revision: int) -> str:
    return f"{question['question_id']}@{question['version']}@{revision}"


def _apply_answers(state: DialogueState, answers: dict, refs: dict, log: list, notices: list) -> None:
    current = {question["field"]: question for question in state["pending"]}
    session = state["session"]
    for name, value in answers.items():
        question = current.get(name)
        if question is None or refs.get(name) != question["ref"]:
            notices.append(f"{name}: 지금 확인하는 질문의 답이 아니라 반영하지 않았어요.")
            continue
        if name == "scope":
            if value in (SCOPE_CURRENT, SCOPE_NEW):
                state["scope_choice"] = (value, question.get("request_text") or "")
            else:
                notices.append("선택지에 없는 값이라 반영하지 않았어요.")
            continue
        if name == "work":
            outcome = tools.set_conditions(session, "", work=str(value), source="answer")
        elif isinstance(question.get("choices"), list) and value not in question["choices"] and not (
                question.get("labels") and value in question["labels"].values()):
            notices.append(f"{name}: 선택지에 없는 값이라 반영하지 않았어요.")
            continue
        else:
            outcome = tools.set_conditions(session, "", values={name: {"value": value}}, source="answer")
        log.append({"tool": "answers", "result": outcome})
        notices.extend(f"{_label(state, field)}: {reason}" for field, reason in outcome["rejected"].items())


# ---- tools: 도구 실행(LLM·규칙 공통) ----

def _run_tool(state: DialogueState, name: str, args: dict, message: str, budget: Budget) -> dict:
    budget.tool_calls += 1
    session = state["session"]
    if name == "find_work":
        if not message:
            return {"status": "error", "data": {"reason": "새 견적은 질문 문장이 필요합니다"}}
        if _confirmed(session) and not state.get("scope_new"):
            target = _cost_target(session, message)
            if target == "ambiguous":
                return _confirm_scope(state, message)
            if target == "current":  # 새 공종을 말하지 않았다: 지금 견적을 초기화하지 않는다
                return {"status": "rejected", "missing": [], "rejected": {}, "data": {
                    "reason": "지금 견적이 있어 새 견적을 시작하지 않았어요. 지금 견적으로 계산하려면 estimate_cost를 부르세요."}}
        state["session"] = session = tools.new_estimate(message, state["request"].get("basis_date"))
        # 계산 목표는 사용자 요청으로 정한다. 비용 요청이면 LLM이 compute_labor를 골라도 비용 목표를 유지한다.
        state["goal"] = "cost" if _rule_route(message, None) == "estimate" else "labor"
        state["fresh_session"] = True  # 첫 문장의 물량·조건은 변경이 아니라 시작 값이다
        result = tools.find_work(session)
        # 원래 요청의 물량은 LLM이 set_conditions를 생략해도 서버가 보존한다(서버 파서로 읽은 값·단위·근거).
        # 공종이 정해지면 명세 단위와 다시 대조한다. 물량이 여러 개면 고르지 않고 명세의 물량 질문으로 묻는다.
        quantity = _request_quantity(session, message)
        if quantity:
            kept = tools.set_conditions(session, message, quantity=quantity, source="text")
            result = {**result, "data": {**(result.get("data") or {}), "request_quantity": quantity,
                                         "request_quantity_rejected": kept["rejected"].get("quantity")}}
        return result
    if name == "search_standard":
        query = args.get("query") if isinstance(args.get("query"), str) and args["query"].strip() else message
        return tools.search_standard(query)
    if session is None:
        return {"status": "error", "data": {"reason": "견적을 먼저 시작해야 합니다(find_work)"}}
    if name == "set_conditions":
        if not state.get("fresh_session") and not args.get("work") and _confirmed(session)                 and not _answers_pending(state, message) and _cost_target(session, message) != "current":
            # 다른 공종(또는 모호한) 요청의 물량·조건을 지금 견적에 넣지 않는다(LLM이 불러도 같다).
            # 후보 공종으로 바꾸는 요청(args.work)은 set_conditions가 후보인지 검증한다.
            return {"status": "rejected", "missing": [], "rejected": {}, "data": {
                "reason": "다른 공종 요청이라 지금 견적의 조건을 바꾸지 않았어요. 새 견적은 find_work로 시작하세요."}}
        if not state.get("fresh_session") and _is_lookup(state, message):
            # 이번 턴에 시작한 견적이 아니면 조회 질문으로 저장된 조건을 바꾸지 않는다(LLM이 불러도 같다).
            return tools._result("ok", tools._item(session), {"applied": {}, "reason": "조회 질문이라 조건을 바꾸지 않았어요"})
        values, quantity, work = _values_arg(session, args.get("values")), args.get("quantity"), args.get("work") or None
        if values is False or (quantity is not None and not isinstance(quantity, dict)) \
                or (work is not None and not isinstance(work, str)):
            return {"status": "error", "data": {"reason": "set_conditions 인자 형식 오류"}}
        if isinstance(quantity, dict) and not str(quantity.get("value") or "").strip():
            quantity = None
        if isinstance(quantity, dict) and not quantity.get("unit"):
            # 단위를 빠뜨리면 사용자 문장의 근거 구절을 서버 파서로 읽어 같은 값의 단위를 쓴다.
            units = {unit for value, unit in tools._quantities(str(quantity.get("evidence") or ""))
                     if value == tools._fraction(quantity.get("value"))}
            if len(units) == 1:
                quantity = {**quantity, "unit": units.pop()}
        return tools.set_conditions(session, message, values=values or None, quantity=quantity, work=work, source="text")
    if name == "compute_labor":
        state["goal"] = state["goal"] or "labor"
        return tools.compute_labor(session)
    if name == "estimate_cost":
        state["goal"] = "cost"
        return tools.estimate_cost(session)
    if name == "explain_basis":
        return tools.explain_basis(session)
    if name == "confirm_scope":
        return _confirm_scope(state, message)
    return {"status": "error", "data": {"reason": f"알 수 없는 도구: {name}"}}


def _values_arg(session: dict, raw) -> dict | None | bool:
    """LLM의 조건 목록 [{field, value, evidence}]을 도구 인자 {field: {value, evidence}}로. 형식이 틀리면 False.

    구조화 출력은 값을 문자열로 주므로, 명세상 참/거짓 조건은 여기서 bool로 바꾼다(근거 대조는 도구가 한다).
    """
    if raw is None or isinstance(raw, dict):
        return raw
    if not isinstance(raw, list) or not all(isinstance(entry, dict) and isinstance(entry.get("field"), str) for entry in raw):
        return False
    spec = tools._spec(tools._item(session))
    kinds = {field["name"]: field["type"] for field in spec["inputs"]} if spec else {}
    values = {}
    for entry in raw:
        value = entry.get("value")
        if kinds.get(entry["field"]) == "boolean" and isinstance(value, str):
            value = True if value.strip().lower() in _TRUE else False if value.strip().lower() in _FALSE else value
        values[entry["field"]] = {"value": value, "evidence": entry.get("evidence")}
    return values


def _rule_actions(state: DialogueState, message: str, answered: bool) -> list[tuple[str, dict]]:
    """LLM 없이 쓰는 결정적 정책. 같은 도구를 같은 검증으로 부른다."""
    session = state["session"]
    finish = [("estimate_cost", {})] if state["goal"] == "cost" else [("compute_labor", {})]
    if answered and not message:
        return finish if session else []
    route = _rule_route(message, state.get("route"))
    state["route"] = route
    # '32m야'처럼 대기 질문에 값만 답한 문장은 라우터가 범위 밖으로 봐도 답으로 반영한다.
    if route == "out_of_scope" and not _answers_pending(state, message):  # 진행 중인 견적을 범위 밖 질문으로 바꾸지 않는다
        return []
    # 어느 견적인지 먼저 정한다. 새 공종 문장의 물량·조건('자동문 3개소')을 지금 견적에 반영하지 않기 위해서다.
    target = _cost_target(session, message) if _confirmed(session) and not _answers_pending(state, message) else "current"
    if route == "estimate" and target == "new":  # 새 세션을 만든 뒤 새 문장의 물량을 반영한다
        return _start_actions(state, message, route)
    if route == "estimate" and target == "ambiguous":  # 확인 전에는 물량·조건을 포함해 지금 상태를 바꾸지 않는다
        return [("confirm_scope", {})]
    computed = bool(session and tools._item(session).get("computed_result"))
    if computed and _BASIS_WORDS.search(message) and not tools._quantities(message):
        return [("explain_basis", {})]
    if computed and _is_lookup(state, message) and _about_current(session, message):
        return [("compute_labor", {})]  # 지금 견적의 품을 다시 보여준다(조건·물량·원가계산서 그대로)
    # 다른 공종(또는 모호한) 문장의 물량·조건은 지금 견적에 넣지 않는다.
    changes = _rule_changes(session, message) if session and target == "current" and not _is_lookup(state, message) else {}
    if session and changes:
        if route == "estimate":
            state["goal"] = "cost"
        return [("set_conditions", changes),
                ("estimate_cost", {}) if state["goal"] == "cost" else ("compute_labor", {})]
    if _confirmed(session) and route == "estimate":  # 새 공종을 말하지 않은 비용 요청: 지금 견적으로 계산
        state["goal"] = "cost"
        return [("estimate_cost", {})]
    if session and route == "qa" and not tools._quantities(message):
        return [("search_standard", {"query": message})]
    return _start_actions(state, message, route)


def _start_actions(state: DialogueState, message: str, route: str) -> list[tuple[str, dict]]:
    """새 견적 시작: 공종 찾기 → 같은 문장의 물량 → 품 또는 비용."""
    state["goal"] = "cost" if route == "estimate" else "labor"
    actions = [("find_work", {})]
    quantity = _rule_quantity(message)
    if quantity:
        actions.append(("set_conditions", {"quantity": quantity}))
    return actions + [("estimate_cost", {}) if state["goal"] == "cost" else ("compute_labor", {})]


def _request_quantity(session: dict, message: str) -> dict | None:
    """새 견적 요청의 물량. 공종이 이미 정해졌으면 명세 물량 단위와 같은 물량이 하나일 때만(32m·15cm 같은 조건 값 제외),
    아니면 문장 속 물량이 하나일 때만 고른다. 여럿이면 고르지 않는다(명세의 물량 질문으로 묻는다)."""
    spec = tools._spec(tools._item(session))
    field = tools._quantity_field(spec) if spec else None
    if not field:
        return _rule_quantity(message)
    text = unicodedata.normalize("NFKC", message).casefold()
    found = [match for match in tools._QUANTITY.finditer(text) if not text[match.end():].lstrip().startswith("당")
             and tools.unit_key(match.group(2)) == tools.unit_key(field.get("unit"))]
    if len(found) != 1:
        return None
    return {"value": found[0].group(1).replace(",", ""), "unit": found[0].group(2), "evidence": found[0].group(0)}


def _rule_quantity(message: str, per_unit: bool = True) -> dict | None:
    """문장 속 물량이 하나면 그 물량. per_unit=False면 '1㎥당'처럼 단위당 기준은 물량으로 보지 않는다."""
    text = unicodedata.normalize("NFKC", message).casefold()
    found = [match for match in tools._QUANTITY.finditer(text)
             if per_unit or not text[match.end():].lstrip().startswith("당")]
    if len(found) != 1:
        return None
    return {"value": found[0].group(1).replace(",", ""), "unit": found[0].group(2), "evidence": found[0].group(0)}


def _rule_changes(session: dict, message: str) -> dict:
    """사용자 문장에서 서버 파서로 읽은 물량·조건 변경. 근거는 문장 그대로다."""
    changes: dict = {}
    quantity = _rule_quantity(message, per_unit=False)
    if quantity:
        changes["quantity"] = quantity
    spec = tools._spec(tools._item(session))
    values = extract_inputs(message, spec)[0] if spec else {}
    quantity_name = (tools._quantity_field(spec) or {}).get("name") if spec else None
    values.update(tools._extract_common_inputs(message))
    found = {name: {"value": value, "evidence": message} for name, value in values.items() if name != quantity_name}
    if found:
        changes["values"] = found
    return changes


# ---- reply: 문장 작성과 대응 검증 ----

def _facts(state: DialogueState, log: list) -> tuple[list[dict], list[str]]:
    facts, literals = [], []
    last = {entry["tool"]: entry["result"] for entry in log}
    labor = (last.get("estimate_cost") or last.get("compute_labor") or {}).get("data") or {}
    if labor.get("unit_lines"):
        unit = (labor.get("unit_basis") or {}).get("per", "")[1:] or "단위"
        if labor.get("quantity"):
            facts.append({"id": "quantity", "item": "물량", "value": labor["quantity"], "unit": unit, "kind": "total",
                          "item_optional": True})
        for key, item, suffix, kind in (("daily_volume_m3", "일당 시공량", f"{unit}/일", "per_unit"),
                                        ("work_days", "작업일수", "일", "total")):
            if labor.get(key):
                facts.append({"id": key, "item": item, "value": labor[key], "unit": suffix, "kind": kind})
        if labor.get("work_days"):
            # 작업일수는 '약 2.31일'로 보여 준다. 검증은 정확값과 이 반올림 결과(소수 둘째 자리)만 허용한다.
            facts[-1].update(shown=approx(labor["work_days"]), rounded=str(rounded(labor["work_days"])))
        for index, line in enumerate(labor["unit_lines"]):
            facts.append({"id": f"line{index}", "item": line["name"], "value": line["applied"], "unit": line["unit"],
                          "kind": "per_unit"})
        literals += [labor.get("section") or "", *map(str, (labor.get("conditions") or {}).values())]
    cost = (last.get("estimate_cost") or {}).get("data") or {}
    for name, value in (cost.get("price_conditions") or {}).items():
        if reply_check._value(str(value)) is not None:  # 사용자가 준 가격 조건(레미콘 단가 등)
            facts.append({"id": name, "item": PRICE_LABELS.get(name, name), "value": str(value), "unit": "원",
                          "kind": "per_unit", "item_optional": True})
    statement = cost.get("statement") or {}
    for key, value in (statement.get("totals") or {}).items():
        if key in TOTAL_LABELS and value is not None:
            facts.append({"id": key, "item": TOTAL_LABELS[key], "value": str(value), "unit": "원", "kind": "total"})
    for question in state["pending"]:
        literals += [question["ask"], *map(str, question.get("choices") or [])]
    return facts, literals


def _template(state: DialogueState, log: list, facts: list[dict], notices: list) -> str:
    by_id = {fact["id"]: fact for fact in facts}
    parts = list(notices)
    last = log[-1]["result"] if log else None
    answer = None
    if "contract_amount" in by_id:
        answer = f"도급액(부가세 포함) {reply_check.display(by_id['contract_amount']['value'])}원으로 계산했어요."
    elif any(key.startswith("line") for key in by_id):
        lines = ", ".join(f"{fact['item']} {reply_check.display(fact['value'])}{fact['unit']}" for key, fact in by_id.items()
                          if key.startswith("line"))
        answer = f"1단위당 품: {lines}"
    elif last and last.get("status") == "ok" and "citations" in last.get("data", {}):
        answer = f"계산에 쓴 품셈 원문 근거 {len(last['data']['citations'])}건을 확인했어요. 견적 조건은 그대로예요."
    elif last and last.get("status") == "ok" and "sections" in last.get("data", {}):
        answer = "관련 품셈 원문: " + ", ".join(section["section"] for section in last["data"]["sections"][:3])
    elif last and last.get("data", {}).get("reason"):
        answer = str(last["data"]["reason"])
    elif not log:
        answer = "공사비·품셈과 관련된 질문을 해 주세요."
    if state["pending"]:
        # 조회만 한 턴(대기 질문 유지)이면 물은 내용을 먼저 답하고 대기 질문을 다시 안내한다.
        if state.get("pending_kept") and answer:
            parts.append(answer)
        stage = state["pending"][0].get("stage")
        parts.append({"work": "먼저 공종을 골라 주세요.",
                      "price": "비용을 계산하려면 가격 조건이 필요해요. 아래에서 골라 주세요.",
                      "scope": "지금 견적은 그대로예요. 어느 견적으로 계산할지 골라 주세요."}.get(
            stage, "품을 계산하려면 아래 조건을 확인해 주세요."))
    elif answer:
        parts.append(answer)
    return "\n".join(part for part in parts if part)


def _reply(state: DialogueState, log: list, notices: list, message: str, budget: Budget, generate, use_llm: bool) -> dict:
    facts, literals = _facts(state, log)
    template = _template(state, log, facts, notices)
    if not use_llm or not log:
        return {"text": template, "source": "template", "rejected": None}
    # 사용자에게 보일 값은 기존 표시 규칙(끝나는 소수 그대로, 순환소수 괄호 표기)으로 준다. 검증은 정확값으로 한다.
    shown = [{**fact, "value": fact.get("shown") or reply_check.display(fact["value"])} for fact in facts]
    prompt = {"user_message": message, "notices": notices, "facts": shown,
              "pending_questions": [question["ask"] for question in state["pending"]],
              "tool_results": [{"tool": entry["tool"], "status": entry["result"]["status"],
                                "data": _compact(entry["result"].get("data", {}))} for entry in log]}
    try:
        data = _call_llm(budget, generate, prompt, (PROMPTS / "reply.md").read_text(encoding="utf-8"), REPLY_SCHEMA)
    except Exception as exc:  # noqa: BLE001 - 문장 작성 실패는 도구 결과를 버리지 않고 템플릿으로 답한다
        return {"text": template, "source": "template", "rejected": f"{type(exc).__name__}: {exc}"}
    session = state.get("session")
    item = tools._item(session) if session else {}
    spec = tools._spec(item) if session else None
    refused = {name: value for e in log if e["tool"] in ("set_conditions", "answers")
               for name, value in ((e["result"].get("data") or {}).get("refused") or {}).items()}
    # 서버 문자열: 기준 문서명('2026 건설공사 표준품셈'), 공종 이름, 지금 조건 값(기존 32m 유지 등), 거부한 조건의 선택지.
    literals += [citation.CODE, str((item.get("selection") or {}).get("section") or ""),
                 str((item.get("selection") or {}).get("section_no") or ""),
                 *_citation_names([entry["result"].get("data") for entry in log]),
                 *[str(c.get(key, "")) for c in item.get("candidates") or [] for key in ("section", "section_no")],
                 *map(str, (item.get("conditions") or {}).values()),
                 *[str(v) for f in (spec or {}).get("inputs", []) if f["name"] in refused
                   and isinstance(f.get("allowed_values"), list) for v in f["allowed_values"]]]
    # 근거 설명 턴에는 원문 인용 속 숫자(할증률·조항 번호 등)를 그대로 옮길 수 있다.
    quoted = [c.get("quote") or "" for e in log if e["tool"] == "explain_basis"
              for c in (e["result"].get("data") or {}).get("citations", [])]
    problem = reply_check.verify(data.get("text"), facts, literals, quoted=quoted, refused=list(refused.values()))
    if problem:
        return {"text": template, "source": "template", "rejected": problem, "rejected_text": data.get("text")}
    return {"text": "\n".join([*notices, data["text"]]) if notices else data["text"], "source": "llm", "rejected": None}


def _citation_names(value) -> list[str]:
    """도구 결과 속 인용(code가 있는 dict)의 절 제목·소제목. 숫자가 들어 있지만 계산값이 아닌 서버 문자열이다.
    인용의 값·쪽수·원문(quote)은 넣지 않는다."""
    if isinstance(value, dict):
        own = [value[key] for key in ("section", "subsection") if "code" in value and isinstance(value.get(key), str)]
        return own + [name for child in value.values() for name in _citation_names(child)]
    if isinstance(value, list):
        return [name for child in value for name in _citation_names(child)]
    return []


def _compact(data: dict) -> dict:
    """LLM에 줄 도구 결과. 원문 인용·계산 근거 같은 큰 필드는 줄인다."""
    keep = {}
    for key, value in data.items():
        if key in ("statement",):
            keep[key] = {"totals": (value or {}).get("totals"), "status": (value or {}).get("status")}
        elif key in ("priced", "provenance"):
            continue
        elif key == "citations":
            keep[key] = [{"section": c.get("section") or c.get("title"), "quote": (c.get("quote") or "")[:200]}
                         for c in value[:6]]
        elif key == "sections":
            keep[key] = [{"section": s["section"], "text": s["text"][:1500]} for s in value[:3]]
        else:
            keep[key] = value
    return keep


# ---- 한 턴 ----

def run_turn(state: DialogueState, request: dict, generate=None, clock=time.monotonic) -> DialogueState:
    """request: {message, answers, refs, conditions, restart, basis_date}. 예외가 나면 호출자는 저장하지 않는다."""
    working: DialogueState = new_dialogue() if request.get("restart") else copy.deepcopy(state or new_dialogue())
    for key, value in new_dialogue().items():
        working.setdefault(key, value)
    working["request"] = request
    budget, log, notices = Budget(clock), [], []
    before = _inputs_key(working)
    message = (request.get("message") or "").strip()
    generate = generate or client.generate
    use_llm = os.environ.get("AGENT_LLM", "off") == "on" or generate is not client.generate

    answers = request.get("answers") or {}
    if answers and working["session"]:
        _apply_answers(working, answers, request.get("refs") or {}, log, notices)
    choice = working.pop("scope_choice", None)
    if choice:
        value, text = choice
        if value == SCOPE_NEW:  # 사용자가 고른 경우에만 새 견적을 시작한다
            working["scope_new"] = True
            actions = _start_actions(working, text, _rule_route(text, working.get("route")))
        else:
            working["goal"] = "cost"
            actions = [("estimate_cost", {})]
        for name, args in actions:
            result = _run_tool(working, name, args, text, budget)
            log.append({"tool": name, "args": args, "result": result})
            if _stops(name, result):
                break
        use_llm = False
    elif request.get("conditions") is not None and working["session"]:
        values = {name: {"value": value} for name, value in request["conditions"].items() if name in COMMON_FIELDS}
        log.append({"tool": "answers", "result": tools.set_conditions(working["session"], "", values=values,
                                                                       source="answer")})
        log.append({"tool": "estimate_cost", "result": _run_tool(working, "estimate_cost", {}, "", budget)})
        use_llm = False
    elif message or answers:
        policy = "llm" if use_llm else "rule"
        if use_llm:
            policy = _agent_loop(working, message, bool(answers), log, budget, generate)
        if policy == "rule":
            for name, args in _rule_actions(working, message, bool(answers)):
                if budget.tool_calls >= MAX_TOOL_CALLS:
                    break
                result = _run_tool(working, name, args, message, budget)
                log.append({"tool": name, "args": args, "result": result})
                if _stops(name, result):
                    break
        use_llm = use_llm and policy == "llm"
        # 입력을 바꾸거나(카드 답·조건·새 견적) 새 견적을 시작했는데 계산으로 끝나지 않았으면(LLM이 바로 답한 경우)
        # 목표에 맞는 계산을 한다. 그래야 남은 질문이 나오고, 바뀐 입력으로 결과가 최신이 된다.
        changed = _inputs_key(working) != before or any(entry["tool"] == "answers" for entry in log)
        last = log[-1] if log else None
        if working["session"] and changed and last and last["tool"] not in ("compute_labor", "estimate_cost")                 and last["result"]["status"] in ("ok", "needs_input") and not last["result"].get("confirm_scope"):
            finish = "estimate_cost" if working["goal"] == "cost" else "compute_labor"
            log.append({"tool": finish, "args": {}, "result": _run_tool(working, finish, {}, message, budget)})
        # 비용 목표인데 이번 턴이 품 계산에서 끝났으면(LLM이 compute_labor만 고른 경우 등) 비용 계산까지 잇는다.
        # 가격 조건이 없으면 estimate_cost가 질문을 낸다. 이미 최신 견적이면(조회 턴) 다시 계산하지 않는다.
        labor = [entry for entry in log if entry["tool"] == "compute_labor"]
        if working["goal"] == "cost" and working["session"] and labor and labor[-1]["result"]["status"] == "ok"                 and not any(entry["tool"] == "estimate_cost" for entry in log)                 and tools.current_estimate(working["session"]) is None:
            log.append({"tool": "estimate_cost", "args": {}, "result": _run_tool(working, "estimate_cost", {}, message, budget)})
    # 반영하지 못한 값은 답변 첫머리에 알린다(이전 결과를 새 결과처럼 보이지 않게).
    notices += [f"반영하지 못했어요 - {_label(working, name)}: {reason}" for entry in log if entry["tool"] == "set_conditions"
                for name, reason in (entry["result"].get("rejected") or {}).items()]
    refresh = bool(answers) or request.get("conditions") is not None or _inputs_key(working) != before
    previous = working["pending"]
    _update_pending(working, log, refresh)
    working["pending_kept"] = bool(previous) and working["pending"] is previous  # 조회 턴: 답한 뒤 같은 질문을 다시 안내
    reply = _reply(working, log, notices, message, budget, generate, use_llm)
    trace = [{"tool": e["tool"], "args": e.get("args"), "status": e["result"].get("status"),
              "rejected": e["result"].get("rejected") or None,
              "reason": (e["result"].get("data") or {}).get("reason")} for e in log]
    working["turn"] = {"answer": reply["text"], "answer_source": reply["source"], "tools": [e["tool"] for e in log],
                       "trace": [*working.pop("agent_errors", []), *trace],
                       "llm_info": {**budget.record(), "rejected": reply["rejected"],
                                    "rejected_text": reply.get("rejected_text")},
                       "last_status": log[-1]["result"]["status"] if log else None}
    working.pop("request", None)
    working.pop("fresh_session", None)
    working.pop("pending_kept", None)
    working.pop("scope_new", None)
    return working


def _agent_loop(state: DialogueState, message: str, answered: bool, log: list, budget: Budget, generate) -> str:
    """LLM이 고른 행동을 실행한다. 상태를 바꾸기 전에 실패하면 'rule'을 돌려 규칙 정책으로 처리한다."""
    system = (PROMPTS / "agent.md").read_text(encoding="utf-8")
    started = len(log)
    while budget.tool_calls < MAX_TOOL_CALLS:
        prompt = {"user_message": message, "answered_questions": answered, "session": _summary(state),
                  "tool_results": [{"tool": e["tool"], "status": e["result"]["status"],
                                    "data": _compact(e["result"].get("data", {})),
                                    "missing": [q["ask"] for q in e["result"].get("missing", [])]} for e in log]}
        try:
            action = _call_llm(budget, generate, prompt, system, ACTION_SCHEMA)
            if action.get("action") not in ("call_tool", "reply") or (
                    action["action"] == "call_tool" and action.get("tool") not in TOOLS):
                raise ValueError(f"행동 형식 오류: {action}")
        except Exception as exc:  # noqa: BLE001
            state.setdefault("agent_errors", []).append({"agent_error": f"{type(exc).__name__}: {str(exc)[:200]}"})
            return "rule" if len(log) == started else "llm"
        if action["action"] == "reply":
            return "llm"
        args = action.get("args") if isinstance(action.get("args"), dict) else {}
        if any(e["tool"] == action["tool"] and e.get("args") == args and e["result"]["status"] == "ok"
               for e in log[started:]):
            return "llm"  # 같은 도구를 같은 인자로 다시 부르면 결과가 같다. 반복하지 않고 답한다
        result = _run_tool(state, action["tool"], args, message, budget)
        log.append({"tool": action["tool"], "args": args, "result": result})
        if _stops(action["tool"], result):
            return "llm"
    return "llm"


def _stops(tool: str, result: dict) -> bool:
    """이번 턴을 멈출 결과. 공종 미확정(find_work의 needs_input) 뒤에는 같은 문장의 물량·조건을 마저 반영한다."""
    if result["status"] in ("not_found", "blocked", "error") or result.get("confirm_scope"):
        return True
    return result["status"] == "needs_input" and tool != "find_work"


def _summary(state: DialogueState) -> dict:
    session = state["session"]
    if not session:
        return {"estimate": None}
    item = tools._item(session)
    spec = tools._spec(item)
    fields = {field["name"]: field["allowed_values"] if isinstance(field["allowed_values"], list) else field["type"]
              for field in (spec["inputs"] if spec else [])}
    fields.update({field["name"]: field["allowed_values"] for field in _common_fields()})
    return {"goal": state["goal"], "work": (item.get("selection") or {}).get("section"),
            "work_confirmed": bool((item.get("selection") or {}).get("confirmed")),
            "work_candidates": [c["section"] for c in item.get("candidates") or []], "fields": fields,
            "quantity": item.get("quantity"), "conditions": item.get("conditions"),
            "common": {name: entry["value"] for name, entry in session["common_conditions"].items()},
            "has_labor_result": bool(item.get("computed_result")),
            "has_current_estimate": tools.current_estimate(session) is not None,
            "pending_questions": [{"field": q["field"], "ask": q["ask"]} for q in state["pending"]]}


def _inputs_key(state: DialogueState):
    """견적 입력의 식별값. 이 값이 그대로면 이번 턴은 조건·물량·공종을 바꾸지 않은 것이다."""
    session = state.get("session")
    if not session:
        return None
    item = tools._item(session)
    return session["estimate_id"], session["revision"], item["input_revision"], item.get("selection")


def _update_pending(state: DialogueState, log: list, refresh: bool = True) -> None:
    """마지막 도구 결과로 대기 질문을 정한다. 새로 낼 때마다 revision을 올려 예전 질문의 답을 거른다.

    refresh=False(입력 변경·카드 답이 없는 턴)면 대기 질문과 ref를 그대로 둔다(단위당 인원·근거·원문 검색 등 조회).
    단, 계산 도구가 다른 필수 질문을 돌려주면(품 → 비용으로 목표가 바뀌어 관급/사급이 필요해진 경우) 새로 낸다.
    같은 질문을 다시 보여줄 때는 ref를 바꾸지 않는다. 조건·공종이 실제로 바뀌면(refresh=True) 질문을 다시 정해
    예전 ref의 답은 계속 거부한다.
    """
    if not refresh:
        calc = [entry["result"] for entry in log
                if entry["tool"] in ("compute_labor", "estimate_cost") or entry["result"].get("confirm_scope")]
        if not calc or calc[-1]["status"] != "needs_input":
            return
        asked = lambda questions: [(q["field"], q["question_id"], q["version"]) for q in questions]  # noqa: E731
        if asked(calc[-1]["missing"]) != asked(state["pending"]):
            state["pending_revision"] += 1
            state["pending"] = [{**question, "ref": _ref(question, state["pending_revision"])}
                                for question in calc[-1]["missing"]]
        return
    results = [entry["result"] for entry in log if entry["tool"] != "answers"]
    if not results and not log:
        return
    last = results[-1] if results else None
    if last and last["status"] == "needs_input":
        state["pending_revision"] += 1
        state["pending"] = [{**question, "ref": _ref(question, state["pending_revision"])} for question in last["missing"]]
    elif last or log:
        state["pending"] = []


# ---- 저장: LangGraph 체크포인터 ----

def build_dialogue_graph(checkpointer=None, generate=None):
    def turn(state: DialogueState) -> DialogueState:
        return run_turn(state, state["request"], generate=generate)

    graph = StateGraph(DialogueState)
    graph.add_node("turn", turn)
    graph.add_edge(START, "turn")
    graph.add_edge("turn", END)
    return graph.compile(checkpointer=checkpointer if checkpointer is not None else MemorySaver())


def config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": f"dlg:{thread_id}"}}


def load(graph, thread_id: str) -> DialogueState | None:
    values = graph.get_state(config(thread_id)).values
    return values or None
