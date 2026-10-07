"""새 공종별 견적 흐름의 서비스 계층(단계 C2-1).

구조화된 계획으로 세션 시작·질문 답변·공종 조건 수정·공통 조건 수정·Excel 생성을 연결한다.
- 견적 세션은 기존 대화와 같은 저장소에 별도 체크포인트 키(대화ID#estimate)로 둔다.
  (LangGraph 최상위 그래프는 checkpoint_ns를 하위 그래프 이름으로 해석하므로 이름공간 방식은 쓰지 않는다.)
- 기존 대화 상태(키 = 대화ID)는 건드리지 않는다. 진행 중인 기존 대화는 기존 흐름으로 재개된다.
- 사용량 차감·로그인·소유권·중복 요청은 호출하는 채팅 API가 그대로 처리한다. 여기서는 차감하지 않는다.
- 자연어 해석은 아직 연결하지 않는다. 계획은 호출자가 구조화된 형태로 넘긴다.
"""

from __future__ import annotations

import copy
from uuid import uuid4

from fastapi import HTTPException
from langgraph.types import Command

from backend.agent.estimate.state import PlanError, new_session, set_common, set_explicit, set_quantity
from backend.api.chat_storage import estimate_thread_id

_MESSAGES = {
    "PENDING": "공종별로 확인할 조건이 있어요. 아래 질문에 답해 주세요.",
    "NEEDS_COMMON": "전체 공사의 공통 조건을 확인해 주세요.",
    "COMPLETE": "입력하신 조건으로 전체 견적을 계산했어요.",
    "PARTIAL": "계산된 공종만 포함한 부분 견적이에요. 빠진 공종과 이유를 함께 확인해 주세요.",
    "NO_RESULT": "계산할 수 있는 공종이 없어 견적 금액을 만들지 않았어요.",
}


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": estimate_thread_id(thread_id)}}


def snapshot(graph, thread_id: str):
    """새 견적 상태. 없으면 None."""
    state = graph.get_state(_config(thread_id))
    return state if state.values.get("estimate") else None


def latest_flow(legacy_graph, estimate_graph, thread_id: str) -> str | None:
    """같은 대화에서 마지막으로 진행된 흐름('legacy' | 'estimate')."""
    legacy = legacy_graph.get_state({"configurable": {"thread_id": thread_id}})
    estimate = snapshot(estimate_graph, thread_id)
    if estimate is None:
        return "legacy" if legacy.values else None
    if not legacy.values:
        return "estimate"
    return "estimate" if (estimate.created_at or "") >= (legacy.created_at or "") else "legacy"


def _question_out(question: dict, session: dict) -> dict:
    """기존 화면 질문 형식. name에 공종 ID·버전을 담아 화면이 그대로 돌려보내면 답이 연결된다."""
    if question.get("scope") == "common":
        label = "전체 공사"
    else:
        number = session["item_order"].index(question["item_id"]) + 1
        label = f"{number}번 {session['items'][question['item_id']]['request_text']}"
    choices = question.get("allowed_values")
    return {"name": f"{question['question_id']}@{question['version']}", "ask": f"[{label}] {question['ask']}",
            "choices": choices, "labels": question.get("labels"), "hint": question.get("hint"), "default": None,
            "decision_table": None, "reason": question.get("reason"), "optional": not question.get("required", True),
            "free_input": not isinstance(choices, list), "citations": []}


def response(thread_id: str, session: dict) -> dict:
    """기존 채팅 응답 모양 + 새 견적 필드(estimate_id·estimate_status·items·notices)."""
    from backend.api.estimate_output import build_output
    output = build_output(session)
    status = output["estimate_status"]
    notices = [notice["message"] for notice in session.get("notices", [])]
    output.update({
        "answer_id": str(uuid4()), "thread_id": thread_id, "flow": "estimate", "route": "estimate",
        "message": " ".join([*notices, _MESSAGES[status]]) if notices else _MESSAGES[status],
        "questions": [_question_out(q, session) for q in session["pending_questions"].values()],
        "evidence": [], "answer": None, "qa": None, "answer_source": "fixed", "llm_info": None,
        "search": {"method": "", "api_calls": 0, "warnings": [], "raw_warnings": [], "fallback_reason": None, "queries": []},
    })
    return output


def _session(graph, thread_id: str) -> tuple[dict, object]:
    state = snapshot(graph, thread_id)
    if state is None:
        raise HTTPException(404, "견적 결과가 없는 대화입니다")
    return copy.deepcopy(state.values["estimate"]), state


def start(graph, thread_id: str, plan: dict, max_items: int | None = None) -> dict:
    """구조화된 계획으로 새 견적을 시작한다. 같은 대화의 이전 견적은 이 키에서 새 견적으로 바뀐다."""
    try:
        session = new_session(plan, max_items=max_items)
    except PlanError as exc:
        raise HTTPException(422, str(exc)) from None
    state = graph.invoke({"estimate": session, "reply": {}}, _config(thread_id))
    return response(thread_id, state["estimate"])


def restart(graph, thread_id: str, max_items: int | None = None) -> dict:
    """다시 보내기: 저장된 입력 계획으로 새 견적 흐름을 다시 실행한다(새 estimate_id, 같은 공종 ID·순서)."""
    session, _ = _session(graph, thread_id)
    plan = session.get("source_plan")
    if not plan:
        raise HTTPException(409, "다시 실행할 견적 계획이 없습니다")
    return start(graph, thread_id, plan, max_items)


def parse_answers(answers: dict) -> list[dict]:
    """화면 답 {name: value}을 공종 질문 답으로 바꾼다. name은 '{question_id}@{version}'."""
    parsed = []
    for name, value in (answers or {}).items():
        question_id, _, version = str(name).rpartition("@")
        parsed.append({"question_id": question_id or name, "version": version if question_id else "", "value": value})
    return parsed


def answer(graph, thread_id: str, answers: dict | None) -> dict:
    """질문 답. 질문 대기 중이면 부모 ask에서 재개하고, 이미 끝난 견적이면 상태를 바꾸지 않고 안내한다."""
    from backend.agent.estimate.flow import answer_after_completion
    session, state = _session(graph, thread_id)
    reply = {"answers": parse_answers(answers or {})}
    if not state.next:
        return response(thread_id, answer_after_completion(session, reply))
    if not reply["answers"]:
        session["notices"] = [{"kind": "invalid", "question_id": "", "message": "선택지에서 골라 주세요."}]
        return response(thread_id, session)
    result = graph.invoke(Command(resume=reply), _config(thread_id))
    return response(thread_id, result["estimate"])


def _require_settled(state) -> None:
    if state.next:
        raise HTTPException(409, "남은 질문에 먼저 답해 주세요")


def update_item(graph, thread_id: str, item_id: str, quantity: dict | None = None,
                conditions: dict | None = None) -> dict:
    """같은 견적의 한 공종만 고친다(물량·조건). 다른 공종 결과는 유지하고, 그 공종 계산과 합계만 갱신한다."""
    session, state = _session(graph, thread_id)
    _require_settled(state)
    item = session["items"].get(item_id)
    if item is None:
        raise HTTPException(404, f"공종을 찾을 수 없습니다: {item_id}")
    try:
        if quantity is not None:
            set_quantity(item, quantity["value"], quantity["unit"], "answer")
        for field, value in (conditions or {}).items():
            set_explicit(item, field, value, "answer")
    except (PlanError, ValueError, KeyError) as exc:
        raise HTTPException(422, f"수정 값이 올바르지 않습니다: {exc}") from None
    session["revision"] += 1
    graph.update_state(_config(thread_id), {"estimate": session, "reply": {}}, as_node="apply_answers")
    result = graph.invoke(None, _config(thread_id))
    return response(thread_id, result["estimate"])


def change_common(graph, thread_id: str, changes: dict, fields: dict) -> dict:
    """공통 공사 조건 변경: 공종 계산은 유지하고 통합 원가계산서만 다시 만든다."""
    session, state = _session(graph, thread_id)
    _require_settled(state)
    changes = dict(changes)
    group = changes.pop("group", None)
    if group is not None and "work_category" not in changes:
        defaults = fields["work_category"]["group_default"]
        if group not in defaults:
            raise HTTPException(422, f"알 수 없는 공사 묶음입니다: {group}")
        changes["work_category"] = defaults[group]
    try:
        for name, value in changes.items():
            set_common(session, name, str(value) if name == "project_scale" else value)
    except PlanError as exc:
        raise HTTPException(422, f"바꿀 수 없는 조건 값입니다: {exc}") from None
    graph.update_state(_config(thread_id), {"estimate": session, "reply": {}}, as_node="run_items")
    result = graph.invoke(None, _config(thread_id))
    return response(thread_id, result["estimate"])


def export(graph, thread_id: str) -> tuple[bytes, str]:
    """마지막 견적 세션으로 Excel을 만든다. 확정되지 않은 견적이면 404."""
    from backend.api.estimate_output import EstimateNotReady, build_estimate_xlsx
    session, state = _session(graph, thread_id)
    try:
        data, filename, _ = build_estimate_xlsx(session)
    except EstimateNotReady:
        raise HTTPException(404, "계산 결과가 없는 대화입니다") from None
    return data, filename
