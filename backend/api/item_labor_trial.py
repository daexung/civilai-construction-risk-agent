"""확인한 여러 작업을 항목별 기존 품 도구로 보내는 로컬 전용 시험 경로.

실행: LOCAL_TRIAL_ITEM_LABOR=on python -m uvicorn backend.api.item_labor_trial:app --host 127.0.0.1 --port 8011
후보는 HTTP 요청에서 주입하는 모의 검색 결과다. 기본 상담/운영 앱에는 연결하지 않는다.
"""
from __future__ import annotations

import copy
import hashlib
import ipaddress
import json
import os
import threading
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from backend.agent.estimate import tools
from backend.agent.estimate.scope import analyze_request, confirm_analysis, confirmed_result
from backend.agent.estimate.state import PlanError, new_session, set_explicit, set_quantity, unit_key
from backend.agent.nodes.fill import _valid_for_field
from backend.api import runtime

PREFIX = "/api/item-labor"
app = FastAPI(title="항목별 품 시험(3단계)")
_TRIALS: dict[str, dict[str, Any]] = {}
_LOCK = threading.RLock()


class AnalyzeRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class ConfirmRequest(BaseModel):
    decisions: list[dict[str, Any]] = Field(max_length=100)


class SearchRequest(BaseModel):
    hits: list[dict[str, Any]] = Field(max_length=30)


class AnswerRequest(BaseModel):
    question_id: str
    version: str
    value: Any
    unit: str | None = None


class EditRequest(BaseModel):
    input_revision: int
    quantity: dict[str, Any] | None = None
    conditions: dict[str, Any] = Field(default_factory=dict)


class ConfirmEditRequest(BaseModel):
    input_revision: int
    confirmed: bool


class ReorderRequest(BaseModel):
    item_ids: list[str] = Field(max_length=30)


def _guard(request: Request) -> None:
    client_host = request.client.host if request.client else ""
    try:
        loopback = ipaddress.ip_address(client_host).is_loopback
    except ValueError:
        loopback = False
    if (runtime.production() or os.environ.get("K_SERVICE") or os.environ.get("K_REVISION") or not loopback
            or os.environ.get("LOCAL_TRIAL_ITEM_LABOR", "off").lower() != "on"):
        raise HTTPException(status_code=404, detail="시험 경로를 사용할 수 없습니다")


def _get_trial(trial_id: str) -> dict[str, Any]:
    trial = _TRIALS.get(trial_id)
    if trial is None:
        raise HTTPException(status_code=404, detail="시험 세션을 찾을 수 없습니다")
    return trial


def _get_item(trial: dict[str, Any], item_id: str) -> dict[str, Any]:
    item = trial["items"].get(item_id)
    if item is None:
        if item_id in trial["excluded_ids"]:
            raise HTTPException(status_code=409, detail="제외한 범위는 시공 항목이 아닙니다")
        raise HTTPException(status_code=404, detail="항목을 찾을 수 없습니다")
    return item


def _digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _mk_item(task: dict[str, Any], analysis: dict[str, Any], decisions: dict[str, dict], source: str) -> dict[str, Any]:
    item_id = task["id"]
    segment = next(span for span in analysis["scope_spans"] if span["span_id"] == task["segment_id"])
    selected = [(segment["start"], segment["text"])]
    source_spans = [{"kind": "scope_clause", "value": segment["text"],
                     "text": segment["text"], "start": segment["start"], "end": segment["end"]},
                    {"kind": "work", "value": task["work"], **task["evidence"]}]
    conditions = list(task.get("conditions", []))
    for condition in conditions:
        source_spans.append({"kind": condition["kind"], "value": condition["value"], **condition["evidence"]})
        if not (segment["start"] <= condition["evidence"]["start"]
                and condition["evidence"]["end"] <= segment["end"]):
            selected.append((condition["evidence"]["start"], condition["evidence"]["text"]))
    attached_background = []
    for surface in analysis["substrates"]:
        choice = decisions.get(surface["id"], {})
        if choice.get("action") == "keep_background" and surface["segment_id"] == task["segment_id"]:
            attached_background.append(surface)
            source_spans.append({"kind": "background", "value": surface["surface"], **surface["evidence"]})
            selected.append((surface["evidence"]["start"], surface["evidence"]["text"]))
    request_text = " ".join(text for _, text in sorted(set(selected)))
    if task["work"] not in request_text:
        request_text = f"{task['work']} {request_text}"
    quantity_conditions = [condition for condition in conditions if condition["kind"] == "quantity"]
    blocked_reason = None
    if any(condition.get("ambiguous") for condition in conditions):
        blocked_reason = "물량이 작업에 연결되는지 확인해야 합니다"
    elif len({condition.get("unit") for condition in quantity_conditions}) < len(quantity_conditions):
        blocked_reason = "같은 단위의 물량이 둘 이상이라 작업 물량을 확인해야 합니다"
    raw_item: dict[str, Any] = {"item_id": item_id, "request_text": request_text, "source_spans": source_spans}
    if len(quantity_conditions) == 1:
        quantity = quantity_conditions[0]
        raw_item["quantity"] = {"value": quantity["value"], "unit": quantity["unit"]}
    try:
        session = new_session({"original_request": source, "items": [raw_item]})
    except (PlanError, KeyError, TypeError, ValueError) as exc:
        session = None
        blocked_reason = str(exc)
    return {"item_id": item_id, "task": copy.deepcopy(task), "session": session,
            "source_spans": source_spans, "scope_confirmed": True,
            "scope_receipt": None, "pending_questions": [], "last_result": None,
            "unsupported_scope": blocked_reason,
            "scope_status": ("UNSUPPORTED" if blocked_reason and "단위" in blocked_reason else "BLOCKED"),
            "edit_version": 0}


def _all_scope_choices_confirmed(analysis: dict, receipt: dict) -> dict[str, dict]:
    return {entry["span_id"]: entry for entry in receipt["decisions"]}


def _refresh_questions(item: dict[str, Any], result: dict) -> None:
    session = item.get("session")
    state_item = tools._item(session) if session else None
    revision = state_item["input_revision"] if state_item else 0
    item["pending_questions"] = [
        {**question, "version": _digest([question.get("version"), revision, item["edit_version"]])[:16]}
        for question in result.get("missing", [])
    ]
    item["last_result"] = copy.deepcopy(result)


def _as_public_item(item: dict[str, Any]) -> dict[str, Any]:
    session = item.get("session")
    state_item = tools._item(session) if session else None
    spec = tools._spec(state_item) if state_item else None
    valid = bool(item.get("scope_confirmed") and not item.get("unsupported_scope") and state_item and state_item.get("computed_result")
                 and item["last_result"] and item["last_result"].get("status") == "ok")
    raw_status = item.get("last_result", {}).get("status") if item.get("last_result") else None
    if item.get("unsupported_scope"):
        status = item.get("scope_status", "BLOCKED")
    elif not item.get("scope_confirmed"):
        status = "SCOPE_CONFIRMATION_REQUIRED"
    elif raw_status == "not_found" and (item.get("last_result", {}).get("data", {}).get("decision") == "no_spec"
                                         or state_item and state_item.get("status") == "UNSUPPORTED"):
        status = "UNSUPPORTED"
    elif raw_status == "not_found":
        status = "NOT_FOUND"
    elif raw_status == "blocked":
        status = "BLOCKED"
    elif raw_status == "error":
        status = "ERROR"
    elif item.get("pending_questions"):
        status = "NEEDS_INPUT"
    elif valid:
        status = "CALCULATED"
    elif raw_status == "needs_input":
        status = "NEEDS_INPUT"
    else:
        status = "NOT_STARTED"
    quantity = state_item.get("quantity") if state_item else None
    labor = copy.deepcopy(state_item.get("computed_result")) if valid else None
    if labor and item["last_result"].get("data"):
        labor = {**labor, **item["last_result"]["data"]}
    if quantity is None and item.get("last_result"):
        computed_quantity = (item["last_result"].get("data") or {}).get("quantity")
        if computed_quantity is not None:
            quantity = {"value": computed_quantity, "unit": (spec and tools._quantity_field(spec) or {}).get("unit"),
                        "source": "confirmed_request"}
    if quantity is None and spec and state_item:
        quantity_field = tools._quantity_field(spec)
        if quantity_field and state_item.get("conditions", {}).get(quantity_field["name"]) is not None:
            quantity = {"value": state_item["conditions"][quantity_field["name"]],
                        "unit": quantity_field.get("unit"), "source": "confirmed_request"}
    uncalculated = copy.deepcopy((labor or {}).get("not_calculated", spec.get("not_calculated", [])) if spec else [])
    if not valid:
        uncalculated.append({"item": item.get("unsupported_scope") or "항목별 품 산출",
                             "reason": "해당 항목의 품 산출이 완료되지 않았습니다"})
    evidence = {"source_spans": copy.deepcopy(item["source_spans"]),
                "labor_provenance": copy.deepcopy((labor or {}).get("provenance", {})),
                "unit_lines": copy.deepcopy((labor or {}).get("unit_lines", [])),
                "citations": copy.deepcopy((labor or {}).get("citations", [])),
                "spec_citations": copy.deepcopy(spec.get("citations", []) if spec else [])}
    return {
        "item_id": item["item_id"], "task": item["task"].get("work"),
        "selected_specification": ({"id": spec["id"], "section_no": spec["section_no"],
                                    "title": spec["title"]} if spec else None),
        "quantity": copy.deepcopy(quantity), "conditions": copy.deepcopy(state_item.get("conditions", {}) if state_item else {}),
        "status": status, "scope_confirmed": item["scope_confirmed"],
        "questions": copy.deepcopy(item["pending_questions"]), "labor": labor,
        "evidence": evidence,
        "unanswered_fields": [question["field"] for question in item["pending_questions"]],
        "not_calculated_scope": uncalculated,
        "input_revision": state_item["input_revision"] if state_item else 0,
    }


def _public_trial(trial: dict[str, Any]) -> dict[str, Any]:
    return {"trial_id": trial["trial_id"], "status": trial["status"],
            "scope_confirmation": copy.deepcopy(trial.get("confirmation")),
            "source_hash": trial["source_hash"],
            "items": [_as_public_item(trial["items"][item_id]) for item_id in trial["item_order"]],
            "excluded_scope": copy.deepcopy(trial.get("excluded_scope", [])),
            "unconfirmed_scope": copy.deepcopy(trial.get("unconfirmed_scope", [])),
            "not_calculated_scope": copy.deepcopy(trial.get("not_calculated_scope", []))}


@app.post(PREFIX + "/analyze")
def analyze(request: Request, payload: AnalyzeRequest) -> dict:
    _guard(request)
    result = analyze_request(payload.text)
    trial_id = uuid.uuid4().hex
    with _LOCK:
        _TRIALS[trial_id] = {"trial_id": trial_id, "status": "SCOPE_CONFIRMATION_REQUIRED",
                             "source": payload.text, "source_hash": _digest(payload.text),
                             "analysis": result, "confirmation": None, "items": {}, "item_order": [],
                             "excluded_ids": set(), "excluded_scope": [],
                             "unconfirmed_scope": copy.deepcopy(result.get("unconfirmed_scope", [])),
                             "not_calculated_scope": []}
        trial = _TRIALS[trial_id]
    return {"trial_id": trial_id, "status": trial["status"], "analysis": result,
            "confirmation_required": True, "items": []}


@app.post(PREFIX + "/{trial_id}/confirm")
def confirm(request: Request, trial_id: str, payload: ConfirmRequest) -> dict:
    _guard(request)
    with _LOCK:
        trial = _get_trial(trial_id)
        try:
            receipt = confirm_analysis(trial["source"], trial["analysis"], payload.decisions)["confirmation"]
            resolved = confirmed_result(trial["source"], trial["analysis"], receipt)
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if resolved["calculation"].get("blocked"):
            raise HTTPException(status_code=409, detail=resolved["calculation"].get("reason", "범위를 작업별로 연결할 수 없습니다"))
        if trial.get("confirmation") == receipt:
            return _public_trial(trial)
        decision_map = _all_scope_choices_confirmed(trial["analysis"], receipt)
        included = resolved["work_items"]
        items = {task["id"]: _mk_item(task, trial["analysis"], decision_map, trial["source"])
                 for task in included}
        excluded_ids = {entry["span_id"] for entry in receipt["decisions"] if entry["action"] in ("keep_excluded", "exclude_work")}
        assigned_surface_ids = {surface["id"] for task in included for surface in trial["analysis"]["substrates"]
                                if surface["segment_id"] == task["segment_id"]
                                and decision_map.get(surface["id"], {}).get("action") == "keep_background"}
        unassigned_surfaces = [surface for surface in trial["analysis"]["substrates"]
                               if decision_map.get(surface["id"], {}).get("action") == "keep_background"
                               and surface["id"] not in assigned_surface_ids]
        trial.update(confirmation=receipt, items=items,
                     item_order=[task["id"] for task in included], excluded_ids=excluded_ids,
                     excluded_scope=resolved.get("excluded_requests", []),
                     unconfirmed_scope=resolved.get("unconfirmed_scope", []),
                     not_calculated_scope=[{"kind": "background", **surface,
                                            "reason": "작업 항목과 바탕의 연결을 확인할 수 없음"}
                                           for surface in unassigned_surfaces])
        if trial["not_calculated_scope"]:
            for item in trial["items"].values():
                item["unsupported_scope"] = "바탕면을 어느 작업에 연결할지 확인이 필요합니다"
        trial["status"] = "ITEMS_READY" if items else "NO_INCLUDED_WORK"
        return _public_trial(trial)


def _require_confirmed(trial: dict[str, Any], item: dict[str, Any]) -> dict:
    if not trial.get("confirmation"):
        raise HTTPException(status_code=409, detail="범위를 먼저 확인해야 합니다")
    if trial.get("source_hash") != _digest(trial["source"]):
        item["scope_confirmed"] = False
        item["last_result"] = None
        raise HTTPException(status_code=409, detail="원문 범위가 바뀌어 확인이 무효가 되었습니다")
    if not item.get("scope_confirmed"):
        raise HTTPException(status_code=409, detail="수정한 작업 범위를 다시 확인해야 합니다")
    if item.get("unsupported_scope"):
        raise HTTPException(status_code=409, detail=item["unsupported_scope"])
    if item.get("session") is None:
        raise HTTPException(status_code=409, detail=item.get("unsupported_scope") or "작업 범위가 지원되지 않습니다")
    return item["session"]


def _calculate_after(session: dict, item: dict) -> dict:
    result = tools.compute_labor(session)
    _refresh_questions(item, result)
    return result


@app.post(PREFIX + "/{trial_id}/items/{item_id}/search")
def search_item(request: Request, trial_id: str, item_id: str, payload: SearchRequest) -> dict:
    _guard(request)
    with _LOCK:
        trial = _get_trial(trial_id)
        item = _get_item(trial, item_id)
        session = _require_confirmed(trial, item)
        result = tools.find_work(session, hits=payload.hits)
        if result["status"] == "ok":
            result = tools.compute_labor(session)
        _refresh_questions(item, result)
        return _public_trial(trial)


def _current_question(item: dict, payload: AnswerRequest) -> dict:
    current = next((question for question in item["pending_questions"]
                    if question["question_id"] == payload.question_id), None)
    if current is None or current["version"] != payload.version:
        raise HTTPException(status_code=409, detail="오래되었거나 다른 항목에 속한 질문 답입니다")
    return current


@app.post(PREFIX + "/{trial_id}/items/{item_id}/answer")
def answer_item(request: Request, trial_id: str, item_id: str, payload: AnswerRequest) -> dict:
    _guard(request)
    with _LOCK:
        trial = _get_trial(trial_id)
        item = _get_item(trial, item_id)
        session = _require_confirmed(trial, item)
        question = _current_question(item, payload)
        answer = payload.value
        if question["field"] == "work":
            answer = str(answer)
            changed = tools.set_conditions(session, answer, work=answer, source="answer")
        else:
            spec = tools._spec(tools._item(session))
            field = next((field for field in spec["inputs"] if field["name"] == question["field"]), None) if spec else None
            if field is None:
                raise HTTPException(status_code=409, detail="현재 명세에서 질문 조건을 찾을 수 없습니다")
            expected_unit = field.get("unit")
            if expected_unit:
                submitted_unit = payload.unit or expected_unit
                if unit_key(submitted_unit) != unit_key(expected_unit):
                    raise HTTPException(status_code=422, detail=f"단위가 질문과 다릅니다. {expected_unit} 단위로 답해 주세요")
            elif payload.unit:
                raise HTTPException(status_code=422, detail="이 조건은 단위를 받지 않습니다")
            else:
                submitted_unit = None
            if field["type"] == "boolean":
                if isinstance(answer, bool):
                    pass
                elif isinstance(answer, str) and answer.strip().lower() in ("true", "예", "네", "yes", "1"):
                    answer = True
                elif isinstance(answer, str) and answer.strip().lower() in ("false", "아니오", "아니요", "no", "0"):
                    answer = False
                else:
                    raise HTTPException(status_code=422, detail="참/거짓 조건은 true 또는 false로 답해 주세요")
            elif not isinstance(answer, str):
                answer = str(answer)
            quantity_field = tools._quantity_field(spec)
            if quantity_field and question["field"] == quantity_field["name"]:
                changed = tools.set_conditions(session, str(answer), quantity={"value": answer,
                                                "unit": submitted_unit or quantity_field.get("unit")}, source="answer")
            else:
                changed = tools.set_conditions(session, str(answer), values={question["field"]: {"value": answer}}, source="answer")
        if changed.get("rejected"):
            item["last_result"] = changed
            _refresh_questions(item, {**changed, "missing": item["pending_questions"]})
            raise HTTPException(status_code=422, detail=changed["rejected"])
        _calculate_after(session, item)
        return _public_trial(trial)


@app.post(PREFIX + "/{trial_id}/items/{item_id}/edit")
def edit_item(request: Request, trial_id: str, item_id: str, payload: EditRequest) -> dict:
    _guard(request)
    with _LOCK:
        trial = _get_trial(trial_id)
        item = _get_item(trial, item_id)
        session = _require_confirmed(trial, item)
        state_item = tools._item(session)
        if payload.input_revision != state_item["input_revision"]:
            raise HTTPException(status_code=409, detail="항목 입력 버전이 바뀌었습니다")
        if payload.quantity is None and not payload.conditions:
            raise HTTPException(status_code=422, detail="바꿀 물량이나 조건이 없습니다")
        draft = copy.deepcopy(item)
        draft_session = draft["session"]
        draft_state = tools._item(draft_session)
        try:
            if payload.quantity is not None:
                set_quantity(draft_state, payload.quantity["value"], payload.quantity["unit"], "answer")
            for name, value in payload.conditions.items():
                if isinstance(value, dict):
                    value = value.get("value")
                spec = tools._spec(draft_state)
                field = next((candidate for candidate in spec["inputs"] if candidate["name"] == name), None) if spec else None
                if field is None or not _valid_for_field(value, field):
                    raise PlanError(f"현재 명세에서 허용하지 않는 조건입니다: {name}")
                set_explicit(draft_state, name, value, "answer")
        except (PlanError, KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        item.update(draft)
        item["scope_confirmed"] = False
        item["scope_receipt"] = None
        item["edit_version"] += 1
        item["pending_questions"] = []
        item["last_result"] = None
        trial["status"] = "ITEM_EDIT_RECONFIRMATION_REQUIRED"
        return _public_trial(trial)


@app.post(PREFIX + "/{trial_id}/items/{item_id}/confirm-edit")
def confirm_edit(request: Request, trial_id: str, item_id: str, payload: ConfirmEditRequest) -> dict:
    _guard(request)
    with _LOCK:
        trial = _get_trial(trial_id)
        item = _get_item(trial, item_id)
        session = item.get("session")
        if session is None:
            raise HTTPException(status_code=409, detail="차단된 항목은 확인할 수 없습니다")
        state_item = tools._item(session)
        if payload.input_revision != state_item["input_revision"] or not payload.confirmed:
            raise HTTPException(status_code=409, detail="수정 범위와 현재 버전을 확인해야 합니다")
        receipt_body = {"scope_receipt": trial["confirmation"], "item_id": item_id,
                        "request_text": state_item["request_text"], "quantity": state_item.get("quantity"),
                        "explicit": state_item.get("explicit"), "revision": state_item["input_revision"]}
        item["scope_receipt"] = {**receipt_body, "receipt_hash": _digest(receipt_body)}
        item["scope_confirmed"] = True
        result = _calculate_after(session, item)
        trial["status"] = "ITEMS_IN_PROGRESS"
        return {**_public_trial(trial), "item_action": result["status"]}


@app.post(PREFIX + "/{trial_id}/reorder")
def reorder(request: Request, trial_id: str, payload: ReorderRequest) -> dict:
    _guard(request)
    with _LOCK:
        trial = _get_trial(trial_id)
        if len(payload.item_ids) != len(set(payload.item_ids)) or set(payload.item_ids) != set(trial["item_order"]):
            raise HTTPException(status_code=422, detail="현재 항목 ID를 각각 한 번씩 보내야 합니다")
        trial["item_order"] = list(payload.item_ids)
        return _public_trial(trial)


@app.get(PREFIX + "/{trial_id}")
def get_trial(request: Request, trial_id: str) -> dict:
    _guard(request)
    with _LOCK:
        return _public_trial(_get_trial(trial_id))
