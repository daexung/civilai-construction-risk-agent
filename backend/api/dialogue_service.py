"""AGENT_MODE=tools일 때의 채팅·복원·내려받기(설계 §9).

대화 상태(estimate/dialogue.py)를 기존 응답 형식(ChatResponse)으로 바꿔 화면·Excel 코드를 그대로 쓴다.
원가계산서·Excel은 current_estimate()가 최신이라고 판정한 결과만 쓴다.
"""

from __future__ import annotations

import copy
import os
from datetime import date

from fastapi import HTTPException

from backend.agent.estimate import dialogue, tools
from backend.agent.tools.calc.format import approx
from backend.agent.rules.specs import load_specs
from backend.api.tables import add_tables, rate_rows, unit_price_rows


def enabled() -> bool:
    # New conversations use the unified Dialogue engine unless deployment opts
    # back into the legacy graph. Existing checkpoints are routed separately.
    return os.environ.get("AGENT_MODE", "tools") == "tools"


FREE_CARD_ANSWER_LIMIT = 30


def free_card_answer(graph, thread_id: str | None, request: dict) -> bool:
    """대화 lock 안에서 현재 질문과 무료 횟수를 확인한다. 판정만 하고 상태는 바꾸지 않는다."""
    answers, refs = request.get("answers") or {}, request.get("refs") or {}
    if (not thread_id or not answers or not refs or request.get("message")
            or request.get("conditions") is not None or request.get("restart")
            or set(answers) != set(refs) or answers.get("scope") == dialogue.SCOPE_NEW):
        return False  # 새 견적 시작은 새 검색이 필요하므로 기존처럼 차감한다.
    state = dialogue.load(graph, thread_id)
    if not state or state.get("free_card_answers", 0) >= FREE_CARD_ANSWER_LIMIT:
        return False
    pending = {question["field"]: question["ref"] for question in state.get("pending") or []}
    # A duplicate field across items is only free when its externally visible
    # composite key identifies exactly one current question.
    if any(name.endswith("::continue") or name.startswith(("scope::", "scope_owner::"))
           or name == "target_item" for name in refs):
        return False
    return all(name in pending and pending[name] == ref for name, ref in refs.items())


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
    pending = state.get("pending") or []
    if pending:
        out.update(status="MISSING_INFO", questions=[_question_out(q) for q in pending])
    if not session:
        return out
    item = tools._item(session)
    candidates = item.get("candidates") or []
    spec_id = item.get("selected_spec_id") or next(
        (spec["id"] for spec in map(tools._spec_for, candidates) if spec), "")
    spec = load_specs().get(spec_id) if spec_id else None
    common = {name: entry["value"] for name, entry in session["common_conditions"].items()}
    out.update(spec_id=spec_id, selection=item.get("selection") or {}, candidates=candidates,
               hits=item.get("hits") or [], search_info=item.get("search_info") or {}, basis_date=session.get("basis_date") or date.today().isoformat(),
               inputs={**common, **(item.get("conditions") or {})},
               input_sources={**{name: entry["source"] for name, entry in session["common_conditions"].items()},
                              **{name: "기본값" if name in item.get("defaulted_inputs", {}) else "답변"
                                 for name in item.get("conditions") or {}}},
               review_status=item.get("review_status") or (spec or {}).get("review", ""))
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
    from backend.api import main as main_api  # main이 이 모듈을 가져오므로 늦게 가져온다

    legacy = legacy_state(state)
    built = main_api._build_response(thread_id, legacy)
    for out, question in zip(built["questions"], state.get("pending") or []):
        out["ref"] = question["ref"]
    if state.get("turn", {}).get("knowledge"):
        built["knowledge"] = state["turn"]["knowledge"]
    built["questions_remaining"] = len(state.get("pending") or [])
    session = state.get("session")
    if session and len(session.get("item_order") or []) > 1:
        public_items, combined_units, combined_rates = [], [], []
        for item_id in session["item_order"]:
            item = session["items"][item_id]
            spec = tools._spec(item)
            priced = item.get("priced_result") or {}
            labor = item.get("computed_result") or {}
            quantity = item.get("quantity")
            if quantity is None and spec:
                quantity_field = tools._quantity_field(spec)
                if quantity_field and item.get("conditions", {}).get(quantity_field["name"]) is not None:
                    quantity = {"value": item["conditions"][quantity_field["name"]],
                                "unit": quantity_field.get("unit"), "source": "confirmed_request"}
            missing = [{"name": row.get("name") or row.get("item") or "범위",
                        "reason": row.get("reason") or row.get("source") or "미산정"}
                       for row in [*priced.get("unpriced", []), *labor.get("not_calculated", [])]]
            item_status = item.get("status", "NEEDS_WORK")
            ui_status = ("PARTIAL" if priced.get("partial") else "OK") if item_status == "PRICED" else (
                "COMPUTED" if labor else "MISSING_INFO" if item.get("questions") else item_status)
            common = {name: entry["value"] for name, entry in session["common_conditions"].items()}
            item_values = {**common, **{name: entry.get("value") if isinstance(entry, dict) else entry
                                        for name, entry in (item.get("conditions") or {}).items()}}
            raw_item_state = {"route": "estimate", "status": ui_status,
                              "spec_id": item.get("selected_spec_id", ""),
                              "selection": item.get("selection") or {},
                              "candidates": item.get("candidates") or [], "hits": item.get("hits") or [],
                              "search_info": item.get("search_info") or {},
                              "basis_date": session.get("basis_date"), "inputs": item_values,
                              "input_sources": {}, "review_status": item.get("review_status", ""),
                              "result": item.get("computed_result"), "priced": item.get("priced_result"),
                              "questions": [{**question, "name": question.get("name") or question.get("field"),
                                            "ask": question.get("ask", ""), "choices": question.get("choices")}
                                           for question in item.get("questions") or []], "statement": None}
            item_response = main_api._build_response(thread_id, raw_item_state)
            public = {"item_id": item_id, "request_text": item.get("request_text", ""),
                      "status": "PARTIAL" if priced.get("partial") else item_status,
                      "task": (item.get("selection") or {}).get("section"),
                      "work": item_response.get("work"), "quantity": quantity,
                      "result": item_response.get("result"), "labor": item_response.get("result"),
                      "priced": item_response.get("priced"),
                      "tables": item_response.get("tables"), "inputs": item_response.get("inputs"),
                      "evidence": item_response.get("evidence"),
                      "rate_version": copy.deepcopy(priced.get("rate_version")),
                      "equipment_rate_version": copy.deepcopy(priced.get("equipment_rate_version")),
                      "input_revision": item.get("input_revision", 0),
                      "questions": copy.deepcopy(item.get("questions", [])),
                      "not_calculated_scope": missing}
            public_items.append(public)
            combined_units.extend({**row, "item_id": item_id, "name": f"[{item_id}] {row['name']}"}
                                  for row in unit_price_rows(priced))
            combined_rates.extend({**row, "name": f"[{item_id}] {row['name']}"}
                                  for row in rate_rows(priced, None, []))
        built["multi_trade_items"] = public_items
        # The parent card represents only the shared statement. Per-item labor,
        # units and prices are rendered from each item's own converted response.
        built["result"], built["priced"], built["evidence"], built["inputs"] = None, None, [], []
        built["work"] = {"title": "복수 공종 견적", "spec_id": "", "section_no": None, "confirmed": True}
        built["tables"] = add_tables({"statement": built.get("statement"), "priced": None,
                                      "conditions": built.get("conditions", []), "result": {}, "work": {},
                                      "tables": {}}) | {"unit_rows": combined_units, "rate_rows": combined_rates}
    built["estimate_current"] = bool(session and tools.current_estimate(session))
    work_days = (built.get("result") or {}).get("work_days")
    if work_days and work_days.get("value"):
        work_days["display"] = approx(work_days["value"])  # 화면 표시만. value(정확값)·Excel은 그대로
    if legacy.get("answer"):
        built["message"] = legacy["answer"]
    return built
