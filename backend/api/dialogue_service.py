"""AGENT_MODE=tools일 때의 채팅·복원·내려받기(설계 §9).

대화 상태(estimate/dialogue.py)를 기존 응답 형식(ChatResponse)으로 바꿔 화면·Excel 코드를 그대로 쓴다.
원가계산서·Excel은 current_estimate()가 최신이라고 판정한 결과만 쓴다.
"""

from __future__ import annotations

import os
from datetime import date

from fastapi import HTTPException

from backend.agent.estimate import dialogue, tools
from backend.agent.tools.calc.format import approx
from backend.agent.rules.specs import load_specs


def enabled() -> bool:
    return os.environ.get("AGENT_MODE", "") == "tools"


def respond(graph, thread_id: str, request: dict) -> dict:
    """한 턴을 실행해 저장하고 응답을 만든다. 턴 중 예외가 나면 저장하지 않고 직전 상태를 유지한다."""
    state = graph.invoke({"request": request}, dialogue.config(thread_id))
    return response(thread_id, state)


def restore(graph, thread_id: str) -> dict:
    """저장소에서 대화 상태를 새로 읽어 마지막 응답을 다시 만든다(새로고침 복원)."""
    state = dialogue.load(graph, thread_id)
    if not state:
        raise HTTPException(404, "대화를 찾을 수 없습니다.")
    return response(thread_id, state)


def export_response(graph, thread_id: str) -> dict:
    """Excel용 응답. 최신 확정 견적이 아니면 404."""
    state = dialogue.load(graph, thread_id)
    if not state or not state.get("session") or tools.current_estimate(state["session"]) is None:
        raise HTTPException(status_code=404, detail="계산 결과가 없는 대화입니다")
    return response(thread_id, state)


def _question_out(question: dict) -> dict:
    return {"name": question["field"], "ask": question["ask"], "choices": question.get("choices"),
            "labels": question.get("labels"), "decision_table": question.get("decision_table"),
            "reason": question.get("reason"), "default": None, "ref": question["ref"]}


def legacy_state(state: dict) -> dict:
    """대화 상태 → 기존 그래프 상태 모양. 응답·표·Excel 코드를 그대로 쓰기 위한 변환이다."""
    turn = state.get("turn") or {}
    session = state.get("session")
    out = {"route": state.get("route") or ("estimate" if state.get("goal") == "cost" else "qa"),
           "route_source": "agent", "answer": turn.get("answer"), "answer_source": turn.get("answer_source"),
           "llm_info": turn.get("llm_info"), "questions": [], "status": "ANSWERED", "reason": ""}
    if not session:
        return out
    item = tools._item(session)
    candidates = item.get("candidates") or []
    spec_id = item.get("selected_spec_id") or next(
        (spec["id"] for spec in map(tools._spec_for, candidates) if spec), "")
    spec = load_specs().get(spec_id) if spec_id else None
    common = {name: entry["value"] for name, entry in session["common_conditions"].items()}
    out.update(spec_id=spec_id, selection=item.get("selection") or {}, candidates=candidates,
               hits=item.get("hits") or [], basis_date=session.get("basis_date") or date.today().isoformat(),
               inputs={**common, **(item.get("conditions") or {})},
               input_sources={**{name: entry["source"] for name, entry in session["common_conditions"].items()},
                              **{name: "답변" for name in item.get("conditions") or {}}},
               review_status=item.get("review_status") or (spec or {}).get("review", ""))
    pending = state.get("pending") or []
    current = tools.current_estimate(session)
    labor_shown = item.get("computed_result") and all(q.get("stage") == "price" for q in pending)
    if pending:
        out.update(status="MISSING_INFO", questions=[_question_out(q) for q in pending])
    elif current:
        partial = current["statement"].get("status") in ("PARTIAL", "UNCALCULATED")
        out.update(status="PARTIAL" if partial else "OK", statement=current["statement"],
                   priced=item.get("priced_result"), reason=current["statement"].get("reason", ""))
    elif turn.get("last_status") == "blocked":
        out.update(status="BLOCKED", reason=item.get("reason", ""))
    elif labor_shown and turn.get("tools") and set(turn["tools"]) & {"compute_labor", "estimate_cost"}:
        out["status"] = "COMPUTED"
    if labor_shown and out["status"] in ("COMPUTED", "OK", "PARTIAL"):
        out["result"] = item["computed_result"]
    return out


def response(thread_id: str, state: dict) -> dict:
    from backend.api.main import _build_response  # main이 이 모듈을 가져오므로 늦게 가져온다

    legacy = legacy_state(state)
    built = _build_response(thread_id, legacy)
    for out, question in zip(built["questions"], state.get("pending") or []):
        out["ref"] = question["ref"]
    session = state.get("session")
    built["estimate_current"] = bool(session and tools.current_estimate(session))
    work_days = (built.get("result") or {}).get("work_days")
    if work_days and work_days.get("value"):
        work_days["display"] = approx(work_days["value"])  # 화면 표시만. value(정확값)·Excel은 그대로
    if legacy.get("answer"):
        built["message"] = legacy["answer"]
    return built
