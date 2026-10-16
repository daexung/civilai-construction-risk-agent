"""확인한 여러 작업을 항목별 기존 품 도구로 보내는 로컬 전용 시험 경로.

실행: LOCAL_TRIAL_ITEM_LABOR=on python -m uvicorn backend.api.item_labor_trial:app --host 127.0.0.1 --port 8011
검색은 저장된 knowledge-v1 release/chunk/vector/query-cache 파일을 읽고 기존 Retriever.search를 사용한다.
기본 상담/운영 앱에는 연결하지 않는다.
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import threading
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from backend.agent.estimate import tools
from backend.agent.estimate.scope import analyze_request, confirm_analysis, confirmed_result
from backend.agent.estimate.state import PlanError, new_session, set_explicit, set_quantity, unit_key
from backend.agent.nodes.fill import _valid_for_field
from backend.api import runtime

PREFIX = "/api/item-labor"
app = FastAPI(title="항목별 품 시험(3단계)")
_TRIALS: dict[str, dict[str, Any]] = {}
_LOCK = threading.RLock()


def _configure_trial_citations() -> None:
    """Use the citation source files beside the pinned local knowledge assets."""
    if os.environ.get("LOCAL_TRIAL_ITEM_LABOR", "off").lower() != "on":
        return
    assets = Path(os.environ.get("KNOWLEDGE_ASSET_DIR", ""))
    if assets.name != "knowledge" or assets.parent.name != "data":
        return
    source_root = assets.parent.parent
    page_map = source_root / "data/processed/page_map.json"
    pdf = source_root / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
    all_chunks = source_root / "data/processed/chunks.all.jsonl"
    chunks = all_chunks if all_chunks.is_file() else source_root / "data/processed/chunks.jsonl"
    if not (page_map.is_file() and pdf.is_file() and chunks.is_file()):
        return

    from backend.agent.tools.source import citation

    if citation.PAGE_MAP != page_map or citation.PDF != pdf or citation.CHUNKS != chunks:
        citation.PAGE_MAP = page_map
        citation.PDF = pdf
        citation.CHUNKS = chunks
        citation._pages.cache_clear()
        citation._pdf_text.cache_clear()
        citation._chunks.cache_clear()


_configure_trial_citations()


class AnalyzeRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class ConfirmRequest(BaseModel):
    decisions: list[dict[str, Any]] = Field(max_length=100)


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


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


class SummaryRequest(BaseModel):
    basis_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    common_conditions: dict[str, Any] = Field(default_factory=dict)


class CommonAnswerRequest(BaseModel):
    field: str
    value: Any


def _guard(request: Request) -> None:
    client_host = request.client.host if request.client else ""
    try:
        loopback = ipaddress.ip_address(client_host).is_loopback
    except ValueError:
        loopback = False
    if (runtime.production() or os.environ.get("K_SERVICE") or os.environ.get("K_REVISION") or not loopback
            or os.environ.get("LOCAL_TRIAL_ITEM_LABOR", "off").lower() != "on"):
        raise HTTPException(status_code=404, detail="시험 경로를 사용할 수 없습니다")


def _get_trial(trial_id: str, owner_token: str) -> dict[str, Any]:
    trial = _TRIALS.get(trial_id)
    token_hash = hashlib.sha256(owner_token.encode("utf-8")).hexdigest() if owner_token else ""
    if trial is None or not hmac.compare_digest(trial.get("owner_token_hash", ""), token_hash):
        raise HTTPException(status_code=404, detail="시험 세션을 찾을 수 없습니다")
    return trial


def _get_item(trial: dict[str, Any], item_id: str) -> dict[str, Any]:
    item = trial["items"].get(item_id)
    if item is None:
        if item_id in trial["excluded_ids"]:
            raise HTTPException(status_code=409, detail="제외한 범위는 시공 항목이 아닙니다")
        raise HTTPException(status_code=404, detail="항목을 찾을 수 없습니다")
    return item


def _invalidate_summary(trial: dict[str, Any]) -> None:
    trial.pop("summary", None)
    trial.pop("summary_xlsx", None)


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
            if not (segment["start"] <= surface["evidence"]["start"]
                    and surface["evidence"]["end"] <= segment["end"]):
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
    elif item.get("search_status") in ("CACHE_MISS", "UNAVAILABLE"):
        status = "SEARCH_INCOMPLETE"
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
        "request_text": (state_item or {}).get("request_text") or item["task"].get("text") or "",
        "source_spans": copy.deepcopy(item["source_spans"]),
        "selected_specification": ({"id": spec["id"], "section_no": spec["section_no"],
                                    "title": spec["title"]} if spec else None),
        "quantity": copy.deepcopy(quantity), "conditions": copy.deepcopy(state_item.get("conditions", {}) if state_item else {}),
        "status": status, "scope_confirmed": item["scope_confirmed"],
        "search_status": item.get("search_status"), "search_info": copy.deepcopy(item.get("search_info")),
        "search_message": item.get("search_message"),
        "candidates": copy.deepcopy(((item.get("last_result") or {}).get("data") or {}).get("candidates", [])),
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
    owner_token = secrets.token_urlsafe(32)
    with _LOCK:
        _TRIALS[trial_id] = {"trial_id": trial_id, "status": "SCOPE_CONFIRMATION_REQUIRED",
                             "source": payload.text, "source_hash": _digest(payload.text),
                             "owner_token_hash": hashlib.sha256(owner_token.encode("utf-8")).hexdigest(),
                             "analysis": result, "confirmation": None, "items": {}, "item_order": [],
                             "excluded_ids": set(), "excluded_scope": [],
                             "unconfirmed_scope": copy.deepcopy(result.get("unconfirmed_scope", [])),
                             "not_calculated_scope": []}
        trial = _TRIALS[trial_id]
    return {"trial_id": trial_id, "owner_token": owner_token, "status": trial["status"], "analysis": result,
            "confirmation_required": True, "items": []}


@app.post(PREFIX + "/{trial_id}/confirm")
def confirm(request: Request, trial_id: str, payload: ConfirmRequest,
            x_trial_owner: str = Header(default="", alias="X-Trial-Owner")) -> dict:
    _guard(request)
    with _LOCK:
        trial = _get_trial(trial_id, x_trial_owner)
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
        _invalidate_summary(trial)
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


def _search_candidates(session: dict) -> dict[str, Any]:
    from backend.agent.estimate.local_v1_search import get_local_v1_search
    return get_local_v1_search().search(tools._item(session)["request_text"])


@app.post(PREFIX + "/{trial_id}/items/{item_id}/search")
def search_item(request: Request, trial_id: str, item_id: str,
                payload: SearchRequest = SearchRequest(),
                x_trial_owner: str = Header(default="", alias="X-Trial-Owner")) -> dict:
    _guard(request)
    with _LOCK:
        trial = _get_trial(trial_id, x_trial_owner)
        item = _get_item(trial, item_id)
        session = _require_confirmed(trial, item)
        from backend.agent.estimate.local_v1_search import QueryCacheMiss, SearchAssetsUnavailable
        try:
            found = _search_candidates(session)
        except QueryCacheMiss as exc:
            item.update(search_status="CACHE_MISS", search_info={"method": "knowledge-v1-hybrid-local-cache",
                         "query_cache_hit": False, "api_calls": 0, "release_id": None},
                        search_message=str(exc), last_result={"status": "search_incomplete", "reason": str(exc)})
            _invalidate_summary(trial)
            return _public_trial(trial)
        except SearchAssetsUnavailable as exc:
            item.update(search_status="UNAVAILABLE", search_info={"method": "knowledge-v1-hybrid-local-cache",
                         "query_cache_hit": False, "api_calls": 0}, search_message=str(exc),
                        last_result={"status": "search_incomplete", "reason": str(exc)})
            _invalidate_summary(trial)
            return _public_trial(trial)
        result = tools.find_work(session, hits=found["hits"])
        item["search_info"] = found["search_info"]
        item["search_status"] = "COMPLETE" if found["search_info"].get("query_cache_hit") else "UNAVAILABLE"
        item.pop("search_message", None)
        if result["status"] == "ok":
            result = tools.compute_labor(session)
        _refresh_questions(item, result)
        _invalidate_summary(trial)
        return _public_trial(trial)


def _current_question(item: dict, payload: AnswerRequest) -> dict:
    current = next((question for question in item["pending_questions"]
                    if question["question_id"] == payload.question_id), None)
    if current is None or current["version"] != payload.version:
        raise HTTPException(status_code=409, detail="오래되었거나 다른 항목에 속한 질문 답입니다")
    return current


@app.post(PREFIX + "/{trial_id}/items/{item_id}/answer")
def answer_item(request: Request, trial_id: str, item_id: str, payload: AnswerRequest,
                x_trial_owner: str = Header(default="", alias="X-Trial-Owner")) -> dict:
    _guard(request)
    with _LOCK:
        trial = _get_trial(trial_id, x_trial_owner)
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
        _invalidate_summary(trial)
        return _public_trial(trial)


@app.post(PREFIX + "/{trial_id}/items/{item_id}/edit")
def edit_item(request: Request, trial_id: str, item_id: str, payload: EditRequest,
              x_trial_owner: str = Header(default="", alias="X-Trial-Owner")) -> dict:
    _guard(request)
    with _LOCK:
        trial = _get_trial(trial_id, x_trial_owner)
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
        _invalidate_summary(trial)
        item["scope_confirmed"] = False
        item["scope_receipt"] = None
        item["edit_version"] += 1
        item["pending_questions"] = []
        item["last_result"] = None
        item["search_status"] = None
        item["search_info"] = None
        item["search_message"] = None
        trial["status"] = "ITEM_EDIT_RECONFIRMATION_REQUIRED"
        return _public_trial(trial)


@app.post(PREFIX + "/{trial_id}/items/{item_id}/confirm-edit")
def confirm_edit(request: Request, trial_id: str, item_id: str, payload: ConfirmEditRequest,
                 x_trial_owner: str = Header(default="", alias="X-Trial-Owner")) -> dict:
    _guard(request)
    with _LOCK:
        trial = _get_trial(trial_id, x_trial_owner)
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
        _invalidate_summary(trial)
        trial_item = item
        trial["status"] = "ITEMS_IN_PROGRESS"
        return {**_public_trial(trial), "item_action": result["status"],
                "confirmed_item_id": trial_item["item_id"]}


@app.post(PREFIX + "/{trial_id}/reorder")
def reorder(request: Request, trial_id: str, payload: ReorderRequest,
            x_trial_owner: str = Header(default="", alias="X-Trial-Owner")) -> dict:
    _guard(request)
    with _LOCK:
        trial = _get_trial(trial_id, x_trial_owner)
        if len(payload.item_ids) != len(set(payload.item_ids)) or set(payload.item_ids) != set(trial["item_order"]):
            raise HTTPException(status_code=422, detail="현재 항목 ID를 각각 한 번씩 보내야 합니다")
        trial["item_order"] = list(payload.item_ids)
        trial.pop("summary", None)
        return _public_trial(trial)


@app.post(PREFIX + "/{trial_id}/invalidate")
def invalidate_trial(request: Request, trial_id: str,
                     x_trial_owner: str = Header(default="", alias="X-Trial-Owner")) -> dict:
    """Remove any aggregate/download result after a client-side input change."""
    _guard(request)
    with _LOCK:
        trial = _get_trial(trial_id, x_trial_owner)
        _invalidate_summary(trial)
        return {"trial_id": trial_id, "invalidated": True}


def _summary_payload(trial: dict[str, Any]) -> dict:
    from backend.agent.estimate.aggregate import aggregate
    from backend.agent.estimate.state import new_session
    from backend.api.tables import add_tables, rate_rows, unit_price_rows
    summary = trial.get("summary")
    if not summary:
        raise HTTPException(status_code=409, detail="먼저 통합 견적을 계산해 주세요")
    parent = copy.deepcopy(summary)
    result = aggregate(parent)
    trial["summary"] = result
    status = result["aggregate_result"]["status"]
    public_items = []
    combined_unit_rows = []
    combined_rate_rows = []
    for item_id in result["item_order"]:
        state = result["items"][item_id]
        priced = state.get("priced_result") or {}
        labor = state.get("computed_result") or {}
        missing = [{"name": entry.get("name") or entry.get("item") or "범위",
                    "reason": entry.get("reason") or entry.get("source") or "미산정"}
                   for entry in [*priced.get("unpriced", []), *labor.get("not_calculated", [])]]
        public_items.append({"item_id": item_id, "request_text": state["request_text"],
                             "status": ("PARTIAL" if priced.get("partial") else state["status"]),
                             "quantity": state.get("quantity"), "priced": copy.deepcopy(state.get("priced_result")),
                             "labor": copy.deepcopy(state.get("computed_result")),
                             "rate_version": copy.deepcopy(priced.get("rate_version")),
                             "equipment_rate_version": copy.deepcopy(priced.get("equipment_rate_version")),
                             "input_revision": state["input_revision"],
                             "questions": copy.deepcopy(state.get("questions", [])),
                             "not_calculated_scope": missing})
        for row in unit_price_rows(priced):
            combined_unit_rows.append({**row, "item_id": item_id, "name": f"[{item_id}] {row['name']}"})
        combined_rate_rows.extend({**row, "name": f"[{item_id}] {row['name']}"}
                                  for row in rate_rows(priced, None, []))
    if status in ("PENDING", "NEEDS_COMMON", "NO_RESULT", "RATE_VERSION_CONFLICT"):
        partial_items = [item for item in result["items"].values()
                         if item.get("status") == "PRICED" and item.get("result_revision") == item.get("input_revision")
                         and (item.get("priced_result") or {}).get("reference_amounts", {}).get("total") is not None]
        if status == "RATE_VERSION_CONFLICT":
            partial_items = []
        partial_direct = {part: sum(int(((item.get("priced_result") or {}).get("reference_amounts") or {})
                                     .get("subtotals", {}).get(part) or 0) for item in partial_items)
                          for part in ("재료비", "노무비", "경비")}
        partial_total = sum(int(item["priced_result"]["reference_amounts"]["total"]) for item in partial_items)
        unpriced_by_category = {
            part: [item["item_id"] for item in partial_items
                   if ((item.get("priced_result") or {}).get("reference_amounts") or {})
                   .get("subtotals", {}).get(part) is None]
            for part in ("재료비", "노무비", "경비")}
        unpriced_by_category = {part: ids for part, ids in unpriced_by_category.items() if ids}
        public_status = "NO_RESULT" if status == "PENDING" and not partial_items else status
        return {"status": public_status, "aggregate": result.get("aggregate_result"),
                "partial_estimate": ({"scope": "priced_items_only", "direct_subtotals": partial_direct,
                                      "direct_total": partial_total, "complete_contract_amount": None,
                                      "unpriced_by_category": unpriced_by_category,
                                      "item_ids": [item["item_id"] for item in partial_items]}
                                     if partial_items else None),
                "common_questions": list(result.get("pending_questions", {}).values()),
                "basis_date": result.get("basis_date"), "items": public_items}
    aggregate_public = copy.deepcopy(result["aggregate_result"])
    aggregate_public["complete_contract_amount"] = (aggregate_public.get("contract_amount")
                                                     if status == "COMPLETE" else None)
    aggregate_public["partial_contract_amount"] = (aggregate_public.get("contract_amount")
                                                     if status == "PARTIAL" else None)
    aggregate_public["contract_amount_scope"] = "all_items" if status == "COMPLETE" else "priced_items_only"
    aggregate_public["contract_amount"] = aggregate_public["complete_contract_amount"]
    return {"status": status, "aggregate": aggregate_public,
            "statement": result["statement"], "basis_date": result["basis_date"],
            "common_conditions": copy.deepcopy(result["common_conditions"]),
            "items": public_items,
            "tables": add_tables({"statement": result["statement"], "priced": None,
                                  "conditions": [], "result": {}, "work": {}, "tables": {}})
                    | {"unit_rows": combined_unit_rows, "rate_rows": combined_rate_rows},
            "overhead_version": result["statement"].get("overhead_version")}


@app.post(PREFIX + "/{trial_id}/estimate")
def estimate_trial(request: Request, trial_id: str, payload: SummaryRequest,
                   x_trial_owner: str = Header(default="", alias="X-Trial-Owner")) -> dict:
    _guard(request)
    from datetime import date
    from backend.agent.estimate.state import new_session, set_common
    from backend.agent.nodes.fill import _common_fields
    from backend.agent.rules.specs import load_specs
    from backend.agent.estimate.tools import price_item_for_aggregate
    with _LOCK:
        trial = _get_trial(trial_id, x_trial_owner)
        if not trial.get("confirmation"):
            raise HTTPException(status_code=409, detail="범위 확인을 먼저 완료해 주세요")
        try:
            date.fromisoformat(payload.basis_date)
            trial.pop("summary", None)
            trial["summary_xlsx"] = None
            template = new_session({"original_request": trial["source"], "basis_date": payload.basis_date,
                                    "items": [{"item_id": item_id,
                                               "request_text": (trial["items"][item_id].get("session") or {}).get("original_request")
                                               or trial["items"][item_id]["task"].get("work", "요청 항목")}
                                              for item_id in trial["item_order"]]})
            children = {}
            for field, value in payload.common_conditions.items():
                set_common(template, field, value)
            for item_id in trial["item_order"]:
                trial_item = trial["items"][item_id]
                if not trial_item.get("scope_confirmed") or trial_item.get("unsupported_scope") or not trial_item.get("session"):
                    state = template["items"][item_id]
                    state["status"] = trial_item.get("scope_status", "UNSUPPORTED")
                    state["reason"] = trial_item.get("unsupported_scope") or "작업 항목을 지원하지 않습니다"
                    state["selected_spec_id"] = ""
                    continue
                search_status = trial_item.get("search_status")
                if search_status in (None, "CACHE_MISS", "UNAVAILABLE"):
                    state = template["items"][item_id]
                    # Until a local search yields candidates, the work is still open for confirmation.
                    # Cache misses and unavailable assets are not proof that this item is unsupported.
                    state["status"] = "NEEDS_WORK"
                    state["reason"] = trial_item.get("search_message") or "작업 검색이 완료되지 않아 확인이 필요합니다"
                    continue
                if search_status != "COMPLETE":
                    state = template["items"][item_id]
                    state["status"] = "ERROR"
                    state["reason"] = trial_item.get("search_message") or "실제 검색이 완료되지 않았습니다"
                    state["selected_spec_id"] = ""
                    continue
                session = copy.deepcopy(trial_item["session"])
                session["basis_date"] = payload.basis_date
                for field, value in payload.common_conditions.items():
                    set_common(session, field, value)
                child_state = session["items"][session["item_order"][0]]
                category_defaults = {"주택 외 건축" if load_specs()[entry["selected_spec_id"]]["division"] in ("건축", "기계설비")
                                     else "기타 토목공사"
                                     for entry in [child_state] if entry.get("selected_spec_id")}
                for definition in _common_fields():
                    name = definition["name"]
                    if name in session["common_conditions"] or name in payload.common_conditions:
                        continue
                    default = (next(iter(category_defaults)) if name == "work_category" and len(category_defaults) == 1
                               else None if name == "work_category" else definition.get("default"))
                    if default is not None:
                        session["common_conditions"][name] = {"value": default, "source":
                                                               "default_division" if name == "work_category" else "default",
                                                               "explicit": False}
                item_state = session["items"][session["item_order"][0]]
                if item_state.get("status") not in ("UNSUPPORTED", "NOT_FOUND", "BLOCKED", "ERROR"):
                    price_item_for_aggregate(session)
                    item_state = session["items"][session["item_order"][0]]
                children[item_id] = session
                template["items"][item_id] = copy.deepcopy(item_state)
                template["items"][item_id]["item_id"] = item_id
            template["item_order"] = list(trial["item_order"])
            for item_id, session in children.items():
                trial["items"][item_id]["session"] = session
            trial["summary"] = template
            return _summary_payload(trial)
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post(PREFIX + "/{trial_id}/common-answer")
def answer_common(request: Request, trial_id: str, payload: CommonAnswerRequest,
                  x_trial_owner: str = Header(default="", alias="X-Trial-Owner")) -> dict:
    _guard(request)
    from backend.agent.estimate.state import set_common
    with _LOCK:
        trial = _get_trial(trial_id, x_trial_owner)
        if not trial.get("summary"):
            raise HTTPException(status_code=409, detail="통합 견적을 먼저 계산해 주세요")
        try:
            set_common(trial["summary"], payload.field, payload.value)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _summary_payload(trial)


@app.get(PREFIX + "/{trial_id}/estimate.xlsx")
def export_trial(request: Request, trial_id: str,
                 x_trial_owner: str = Header(default="", alias="X-Trial-Owner")) -> Response:
    _guard(request)
    from backend.api.tables import build_xlsx
    with _LOCK:
        trial = _get_trial(trial_id, x_trial_owner)
        summary = _summary_payload(trial)
        if summary["status"] not in ("COMPLETE", "PARTIAL") or not summary.get("aggregate", {}).get("included"):
            raise HTTPException(status_code=409, detail="내보낼 수 있는 계산 금액이 없습니다")
        response = {"tables": summary["tables"], "statement": summary["statement"],
                    "basis_date": summary["basis_date"], "work": {"title": "복수 공종 견적"},
                    "result": {"review_status": "부분 산정" if summary["status"] == "PARTIAL" else "산정 완료"},
                    "conditions": [{"name": name, **entry} for name, entry in summary["common_conditions"].items()],
                    "multi_trade_items": summary["items"],
                    "aggregate": summary["aggregate"]}
        body = build_xlsx(response)
        return Response(body, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": 'attachment; filename="multi-trade-estimate.xlsx"'})


@app.get(PREFIX + "/health")
def health(request: Request) -> dict:
    _guard(request)
    from backend.agent.estimate.local_v1_search import SearchAssetsUnavailable, get_local_v1_search
    try:
        search = get_local_v1_search()
        return {"status": "ok", "search": "knowledge-v1-hybrid-local-cache",
                "release_id": search.release_id, "chunk_set_id": search.chunk_set_id,
                "query_cache_count": len(search.query_cache), "embedding_calls_enabled": False,
                "database_path_verified": False}
    except SearchAssetsUnavailable as exc:
        raise HTTPException(status_code=503, detail={"code": "SEARCH_ASSETS_UNAVAILABLE", "message": str(exc)}) from exc


@app.get(PREFIX + "/{trial_id}")
def get_trial(request: Request, trial_id: str,
              x_trial_owner: str = Header(default="", alias="X-Trial-Owner")) -> dict:
    _guard(request)
    with _LOCK:
        return _public_trial(_get_trial(trial_id, x_trial_owner))
