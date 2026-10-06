"""route부터 fill까지의 그래프를 부르는 채팅 API."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import re
import copy
import hashlib
from contextlib import ExitStack
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import date
from time import perf_counter
from typing import Optional
from uuid import uuid4
from uuid import UUID
from secrets import token_urlsafe, compare_digest
from time import monotonic
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Header, Request
from fastapi import HTTPException
from fastapi.responses import FileResponse, Response, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from langgraph.types import Command
from pydantic import BaseModel, Field, field_validator

from backend.agent.graph import build_graph, capture_node_timings
from backend.agent.rules.specs import load_specs
from backend.agent.nodes.retrieve import get_search
from backend.render_sources import render_source
from backend.agent.state import new_state
from backend.agent.nodes.fill import _common_fields, _valid_for_field
from backend.api.tables import add_tables, build_xlsx, estimate_filename
from backend.agent.tools.source.citation import prepare_citations, resolve_cites
from backend.agent.tools.llm.client import LLMUnavailable, warmup_client
from backend.api import chat_storage
from backend.api import usage_limits
from backend.api import runtime
from backend.api import feedback
from backend.api import answer_feedback
from backend.api import accounts
from backend.api.client_ip import client_ip
from langgraph.checkpoint.postgres import PostgresSaver

GRAPH = build_graph()
_GUESTS: dict[str, dict] = {}
_GUEST_LOCK = threading.Lock()
_GUEST_TTL = 24 * 60 * 60

DEV_ORIGINS = runtime.allowed_origins()

_READY_EVENT = threading.Event()
_LIFESPAN_ACTIVE = False
_READY_ERROR: Exception | None = None


def _prepare_service() -> None:
    global _READY_ERROR
    started = perf_counter()
    try:
        chat_storage.setup()
        prepare_citations()
        get_search()
        load_specs()
        if os.environ.get("AGENT_LLM", "off") == "on":
            try:
                warmup_client()
            except LLMUnavailable:
                logging.getLogger(__name__).warning("LLM client warmup failed; rule fallback remains available")
    except Exception as exc:
        _READY_ERROR = exc
        logging.getLogger(__name__).exception("Service preparation failed")
    finally:
        logging.getLogger(__name__).info("Service preparation completed in %.2f sec", perf_counter() - started)
        _READY_EVENT.set()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _LIFESPAN_ACTIVE, _READY_ERROR
    runtime.validate_production()
    _LIFESPAN_ACTIVE = True
    _READY_ERROR = None
    _READY_EVENT.clear()
    prepare_task = asyncio.create_task(asyncio.to_thread(_prepare_service))
    async def account_maintenance():
        while True:
            await asyncio.to_thread(accounts.recover)
            await asyncio.sleep(60)
    maintenance_task = None
    try:
        if runtime.production():
            # Request-based Cloud Run may throttle background CPU after startup.
            # Keep ASGI startup open until the index and citations are ready.
            await prepare_task
            if _READY_ERROR is not None:
                raise RuntimeError('Service preparation failed during startup') from _READY_ERROR
        maintenance_task = asyncio.create_task(account_maintenance())
        yield
    finally:
        if maintenance_task is not None:
            maintenance_task.cancel()
            try:
                await maintenance_task
            except asyncio.CancelledError:
                pass
        await prepare_task
        _LIFESPAN_ACTIVE = False


app = FastAPI(title="civilai-construction-risk-agent chat api", lifespan=lifespan,
              docs_url=None if runtime.production() else '/docs',
              redoc_url=None if runtime.production() else '/redoc',
              openapi_url=None if runtime.production() else '/openapi.json')
app.add_middleware(
    CORSMiddleware,
    allow_origins=DEV_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)


from backend.paths import ROOT

SOURCES = ROOT / "data/processed/sources"


class ChatRequest(BaseModel):
    thread_id: Optional[str] = None
    message: Optional[str] = None
    restart: bool = False
    answers: Optional[dict] = None
    basis_date: Optional[date] = None
    conditions: Optional[dict] = None
    conversation_id: Optional[UUID] = None
    request_id: Optional[UUID] = None
    user_label: Optional[str] = None


class GuestImportRequest(BaseModel):
    thread_id: str
    conversation_id: UUID


class AccountDeletionRequest(BaseModel):
    challenge_id: UUID
    confirmation: str


_FIELD_LABELS = {
    "structure": "구조물",
    "placement": "타설방식",
    "vibrator_used": "진동기 사용",
}


def _label(field: dict) -> str:
    if field.get("label"):
        return field["label"]
    if field["name"] in _FIELD_LABELS:
        return _FIELD_LABELS[field["name"]]
    match = re.search(r"^(.+?)(?:은|는|이|가)\s", field.get("ask", ""))
    return match.group(1) if match else field["name"]


def _questions_out(questions: list[dict]) -> list[dict]:
    return [
        {
            "name": question["name"],
            "ask": question["ask"],
            "choices": question.get("choices"),
            "labels": question.get("labels"),
            "hint": question.get("hint"),
            "default": question.get("default"),
            "decision_table": question.get("decision_table"),
            "reason": question.get("reason"),
            "optional": question.get("optional", False),
            "free_input": question.get("free_input", False),
            "citations": _citations_out(question.get("citations", [])),
        }
        for question in questions
    ]


def _inputs_out(state: dict, spec: dict | None) -> list[dict]:
    field_by_name = {field["name"]: field for field in spec["inputs"]} if spec else {}
    field_by_name.update({field["name"]: field for field in _common_fields()})
    sources = state.get("input_sources", {})
    out = []
    for name, value in state.get("inputs", {}).items():
        field = field_by_name.get(name)
        label = _label(field) if field else name
        out.append({"name": name, "label": label, "value": value, "source": sources.get(name, "")})
    return out


def _conditions_out(state: dict) -> list[dict]:
    """공사 조건 현재 값과 출처, 선택지, 설명. 공사 종류에는 토목/건축 묶음을 붙인다."""
    sources = state.get("input_sources", {})
    inputs = state.get("inputs", {})
    out = []
    for field in _common_fields():
        name = field["name"]
        item = {"name": name, "label": field["label"], "value": inputs.get(name, field["default"]),
                "source": sources.get(name, "기본값"), "type": field["type"],
                "choices": field["allowed_values"],
                "help": field.get("help", {}), "default": field["default"]}
        if "groups" in field:
            item["groups"] = field["groups"]
            item["group"] = next(group for group, values in field["groups"].items() if item["value"] in values)
        out.append(item)
    return out


def _evidence_out(state: dict) -> list[dict]:
    return [
        {
            "section_no": hit["section_no"],
            "section": hit["section"],
            "page": hit["page"],
            "table_id": hit.get("table_id"),
            "snippet": hit["text"],
        }
        for hit in state.get("hits", [])[:3]
    ]


def _work_out(state: dict, spec: dict | None) -> dict | None:
    spec_id = state.get("spec_id", "")
    if not spec_id or spec is None:
        return None
    selection = state.get("selection", {})
    return {
        "spec_id": spec_id,
        "section_no": selection.get("section_no") or spec["section_no"],
        "title": f"{spec['division']} {spec['section_no']} {spec['title']}",
        "confirmed": bool(selection.get("confirmed")),
    }


def _status_out(state: dict) -> str:
    return state.get("status", "RUNNING")


def _message_out(status: str, state: dict) -> str:
    if status == "PARTIAL":
        return state.get("reason") or "확인 가능한 단가로 부분 금액을 계산했어요. 미산정 항목은 금액에 포함하지 않았어요."
    if status == "OK":
        return "입력하신 조건으로 견적을 계산했어요."
    if status == "COMPUTED":
        return "품셈에 따른 투입량을 계산했어요. 금액은 다음 단계에서 계산해요."
    if status == "BLOCKED":
        return state.get("reason") or "현재 조건에 맞는 원문 근거를 확인하지 못해 계산을 보류했어요."
    if status == "EVIDENCE_ONLY":
        return state.get("reason") or "아직 견적 계산을 지원하지 않는 공종이에요. 확인한 품셈 근거를 안내해 드릴게요."
    if status == "ERROR":
        return state.get("reason") or "처리 중 문제가 생겼어요. 잠시 후 다시 시도해 주세요."
    return state.get("reason") or ""


def _source_label(cell: dict) -> str:
    return f"{cell['table']} {cell['row']}·{cell['column']} {cell['value']}"


def _rule_label(rule: dict) -> str:
    when = ", ".join(f"{name}={value}" for name, value in rule["when"].items())
    return f"{when} → {rule['change']} ({rule['source']})"


def _citations_out(citations: list[dict]) -> list[dict]:
    return [{**citation, **({"image_url": f"/api/source/{citation['internal_id']}.png"}
                           if re.fullmatch(r"p\d+(?:-[tx]\d+)?", citation["internal_id"]) else {})}
            for citation in citations]


def _computed_result_out(raw: dict, spec: dict, review_status: str) -> dict:
    if "daily_volume_m3" not in raw:
        from fractions import Fraction
        from backend.agent.tools.calc.daily_crew import _exact_text

        quantity = Fraction(raw["provenance"]["quantity"])
        lines = [{"kind": line["kind"], "name": line["name"],
                  "value": _exact_text(Fraction(line["exact"]) * quantity),
                  "unit": ("인·일" if line["kind"] == "labor" else
                           line["unit"].split("/", 1)[0] if line["kind"] == "material" else "대·일"),
                  "crew": None, "rules": [], "source": line["source"],
                  "citations": _citations_out(line["citations"])}
                 for line in raw["unit_lines"]]
        return {"daily_volume": None, "work_days": None, "lines": lines,
                "unit_lines": [{**line, "citations": _citations_out(line["citations"])}
                               for line in raw["unit_lines"]],
                "unit_basis": raw["unit_basis"],
                "not_calculated": [{**item, "citations": _citations_out(resolve_cites(item.get("cite")))}
                                   for item in raw["not_calculated"]],
                "review_status": review_status, "adjustment_memos": raw.get("adjustment_memos", [])}
    tables = {table["id"]: table for table in spec["tables"]}
    base_table = spec["quantity_model"]["params"]["base_output"]["table"]
    daily_provenance = raw["provenance"]["daily_volume_m3"]
    base_source = daily_provenance["base_output"]
    coefficient_sources = daily_provenance["coefficients"]
    formula = " × ".join(
        [f"기준 {base_source['value']}"] + [f"{c['row']} {c['value']}" for c in coefficient_sources]
    )
    sources = [f"{base_source['table']} {base_source['source']}"]
    sources += [f"{c['table']} {c['source']}" for c in coefficient_sources]

    work_provenance = raw["provenance"]["work_days"]

    lines = []
    for trade, value in raw["person_days"].items():
        source = raw["provenance"]["person_days"][trade]
        lines.append({
            "kind": "labor",
            "name": trade,
            "value": value,
            "unit": "인·일",
            "crew": source["adjusted_crew"],
            "rules": [_rule_label(rule) for rule in source["rules"]],
            "source": _source_label(source["crew"]),
            "citations": _citations_out(source["citations"]),
        })
    for equipment_name, equipment_unit in raw["equipment_units"].items():
        equipment_source = raw["provenance"]["equipment_days"][equipment_name]
        lines.append({
            "kind": "equipment", "name": equipment_name,
            "value": raw["equipment_days"][equipment_name], "unit": equipment_unit,
            "crew": None, "rules": [],
            "source": _source_label(equipment_source["equipment"]),
            "citations": _citations_out(equipment_source["citations"]),
        })

    return {
        "daily_volume": {
            "value": raw["daily_volume_m3"],
            "unit": tables[base_table].get("unit", ""),
            "formula": formula,
            "sources": sources,
            "citations": _citations_out(daily_provenance["citations"]),
        },
        "work_days": {
            "value": raw["work_days"],
            "formula": f"{work_provenance['quantity']} ÷ {raw['daily_volume_m3']}",
        },
        "lines": lines,
        "unit_lines": [{**line, "citations": _citations_out(line["citations"])}
                       for line in raw["unit_lines"]],
        "unit_basis": raw["unit_basis"],
        "not_calculated": [{**item, "citations": _citations_out(resolve_cites(item.get("cite")))}
                           for item in raw["not_calculated"]],
        "review_status": review_status,
        "adjustment_memos": raw.get("adjustment_memos", []),
    }


def _priced_out(raw: dict | None) -> dict | None:
    if raw is None:
        return None
    return {**raw,
            "lines": [{**line, "citations": _citations_out(line["citations"])} for line in raw["lines"]],
            "equipment_lines": [{**line, "citations": _citations_out(line["citations"])}
                                for line in raw.get("equipment_lines", [])],
            "cost_lines": [{**line, "citations": _citations_out(line["citations"])}
                           for line in raw["cost_lines"]],
            "supply_lines": [{**line, "citations": _citations_out(line["citations"])}
                             for line in raw.get("supply_lines", [])],
            "unpriced": [{**item, "citations": _citations_out(item["citations"])}
                         for item in raw["unpriced"]],
            "excluded": [{**item, "citations": _citations_out(item["citations"])}
                        for item in raw.get("excluded", [])],
            "total_citations": _citations_out(raw["total_citations"])}


def _result_out(state: dict, spec: dict | None) -> dict | None:
    status = state.get("status")
    raw = state.get("result")
    if not raw:
        return None
    if status == "BLOCKED":
        return {**raw, "citations": _citations_out(raw.get("citations", []))}
    if status in ("COMPUTED", "OK", "PARTIAL") and spec:
        return _computed_result_out(raw, spec, state.get("review_status", ""))
    return None


def _search_out(state: dict) -> dict:
    search_info = state.get("search_info", {})
    method = search_info.get("method", "")
    raw = list(search_info.get("warnings", []))
    if method and method not in ("hybrid", "bm25(오프라인)") and not raw:
        raw = [f"임베딩 검색이 꺼져 단어 검색({method})으로만 찾았습니다"]
    # 오류 원문은 raw_warnings로만 내리고, 화면에는 쉬운 문장만 보인다.
    warnings = ["의미 검색이 잠시 안 돼 단어 검색으로 찾았습니다."] if raw else []
    return {"method": method, "api_calls": search_info.get("api_calls", 0), "warnings": warnings,
            "raw_warnings": raw, "fallback_reason": search_info.get("fallback_reason"),
            "queries": search_info.get("queries", [])}


def _qa_out(state: dict) -> dict | None:
    qa = state.get("qa")
    if not qa or state.get("status") != "ANSWERED":
        return None
    resolved = _citations_out(resolve_cites(qa["citations"]))
    return {**qa, "citations": [{**raw, **cite} for raw, cite in zip(qa["citations"], resolved)]}


def _build_response(thread_id: str, state: dict) -> dict:
    status = _status_out(state)
    spec_id = state.get("spec_id", "")
    spec = load_specs().get(spec_id) if spec_id else None
    response = {
        "answer_id": str(uuid4()),
        "thread_id": thread_id,
        "status": status,
        "route": state.get("route"),
        "route_confidence": state.get("route_confidence"),
        "route_reason": state.get("route_reason"),
        "route_source": state.get("route_source"),
        "message": _message_out(status, state),
        "work": _work_out(state, spec),
        "questions": _questions_out(state.get("questions", [])),
        "inputs": _inputs_out(state, spec),
        "evidence": _evidence_out(state),
        "result": _result_out(state, spec),
        "priced": _priced_out(state.get("priced")),
        "statement": state.get("statement"),
        "answer": state.get("answer") or None,
        "qa": _qa_out(state),
        "answer_source": state.get("answer_source") or None,
        "llm_info": state.get("llm_info") or None,
        "basis_date": state.get("basis_date") or date.today().isoformat(),
        "search": _search_out(state),
        "conditions": _conditions_out(state),
    }
    response["tables"] = add_tables(response)
    return response


@app.get("/api/health")
def health() -> dict:
    if _LIFESPAN_ACTIVE and not _READY_EVENT.is_set():
        return {"status": "warming"}
    return {"status": "error" if _READY_ERROR else "ok"}


@app.get('/api/ready')
def ready() -> JSONResponse:
    status = health()
    return JSONResponse(status, status_code=200 if status['status'] == 'ok' else 503)


@app.get("/api/source/{table_id}.png")
def source_image(table_id: str) -> FileResponse:
    if not re.fullmatch(r"p\d+(?:-[tx]\d+)?", table_id):
        raise HTTPException(status_code=404, detail="표 이미지를 찾을 수 없습니다")
    path = SOURCES / f"{table_id}.png"
    if not path.is_file():
        try:
            path = render_source(table_id, output_dir=SOURCES)
        except (LookupError, FileNotFoundError, ValueError):
            raise HTTPException(status_code=404, detail="표 이미지를 찾을 수 없습니다") from None
    return FileResponse(path, media_type="image/png")


def _finished_state(thread_id: str | None, graph=None) -> dict:
    """계산이 끝난 thread의 그래프 state. 계산 결과가 없으면 404."""
    if not thread_id:
        raise HTTPException(status_code=404, detail="계산 결과가 없는 대화입니다")
    snapshot = (graph or GRAPH).get_state({"configurable": {"thread_id": thread_id}})
    if snapshot.next or not snapshot.values.get("statement"):
        raise HTTPException(status_code=404, detail="계산 결과가 없는 대화입니다")
    return snapshot.values


def _change_conditions(payload: ChatRequest, graph=None) -> dict:
    """공종 입력은 두고 공사 조건만 바꿔 원가계산서와 설명 문장을 다시 만든다."""
    graph = graph or GRAPH
    values = _finished_state(payload.thread_id, graph)
    fields = {field["name"]: field for field in _common_fields()}
    changes = dict(payload.conditions)
    group = changes.pop("group", None)
    if group is not None and "work_category" not in changes:
        defaults = fields["work_category"]["group_default"]
        if group not in defaults:
            raise HTTPException(status_code=422, detail=f"알 수 없는 공사 묶음입니다: {group}")
        changes["work_category"] = defaults[group]
    for name, value in changes.items():
        if name not in fields or not _valid_for_field(value, fields[name]):
            raise HTTPException(status_code=422, detail=f"바꿀 수 없는 조건 값입니다: {name}")
    inputs = {**values["inputs"], **{name: str(value) if name == "project_scale" else value
                                     for name, value in changes.items()}}
    sources = {**values.get("input_sources", {}), **{name: "선택" for name in changes}}
    config = {"configurable": {"thread_id": payload.thread_id}}
    # price 다음 노드(statement)부터 다시 돌려 원가계산서와 설명 문장만 새로 만든다.
    graph.update_state(config, {"inputs": inputs, "input_sources": sources}, as_node="price")
    return _build_response(payload.thread_id, graph.invoke(None, config))


@app.get("/api/export/{thread_id}.xlsx")
def export_xlsx(thread_id: str, authorization: str | None = Header(default=None),
                x_guest_session: str | None = Header(default=None)) -> Response:
    user_id = chat_storage.identity(authorization)
    if user_id:
        try:
            conversation_id = str(UUID(thread_id))
        except ValueError:
            raise HTTPException(404, "대화를 찾을 수 없습니다.") from None
        with chat_storage.connection() as conn:
            chat_storage.owned(conn, conversation_id, user_id)
            response = _build_response(conversation_id, _finished_state(conversation_id, build_graph(PostgresSaver(conn))))
    else:
        guest = _guest(thread_id, x_guest_session)
        with guest["lock"]:
            _guest(thread_id, x_guest_session)
            response = _build_response(thread_id, _finished_state(thread_id))
    filename = quote(estimate_filename(response), safe="")
    return Response(build_xlsx(response),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="estimate.xlsx"; filename*=UTF-8\'\'{filename}'})


@app.post("/api/feedback")
def receive_feedback(payload: feedback.FeedbackRequest, request: Request,
                     authorization: str | None = Header(default=None)):
    user_id = chat_storage.identity(authorization)
    with accounts.guard(user_id):
        return feedback.submit(payload, user_id, client_ip(request))


@app.post('/api/answer-feedback')
def receive_answer_feedback(payload: answer_feedback.RatingRequest, request: Request,
                            authorization: str | None = Header(default=None),
                            x_guest_session: str | None = Header(default=None)):
    user_id = chat_storage.identity(authorization)
    quota_subject = usage_limits.subject(user_id, client_ip(request))
    try:
        with accounts.guard(user_id), chat_storage.connection() as conn:
            if user_id:
                with conn.transaction():
                    conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (payload.thread_id,))
                    question, response = answer_feedback.member_target(conn, payload, user_id)
                    return answer_feedback.submit(conn, payload, user_id, quota_subject, question, response)
            guest = _guest(payload.thread_id, x_guest_session)
            with guest['lock']:
                _guest(payload.thread_id, x_guest_session)
                target = next(((label, result) for label, result in guest['turns']
                               if result.get('answer_id') == str(payload.answer_id)), None)
                if not target:
                    raise HTTPException(404, '평가할 답변을 찾을 수 없습니다.')
                return answer_feedback.submit(conn, payload, None, quota_subject, *target)
    except answer_feedback.psycopg.Error:
        raise answer_feedback.unavailable() from None


@app.post('/api/account/deletion-challenge')
def account_deletion_challenge(authorization: str | None = Header(default=None)):
    return accounts.begin(authorization)


@app.delete('/api/account')
def delete_account(payload: AccountDeletionRequest, authorization: str | None = Header(default=None)):
    if payload.confirmation != '탈퇴':
        raise HTTPException(422, '확인 문구를 입력해 주세요.')
    return accounts.remove(authorization, str(payload.challenge_id))


@app.get("/api/usage")
def usage(request: Request, authorization: str | None = Header(default=None)):
    return usage_limits.read(chat_storage.identity(authorization), client_ip(request))


@app.post("/api/chat")
def chat(payload: ChatRequest, request: Request, authorization: str | None = Header(default=None),
         x_guest_session: str | None = Header(default=None)) -> dict:
    user_id = chat_storage.identity(authorization)
    if _LIFESPAN_ACTIVE:
        _READY_EVENT.wait()
        if _READY_ERROR:
            raise HTTPException(status_code=503, detail="Service preparation failed")
    started = perf_counter()
    if payload.message is not None and not 1 <= len(payload.message.strip()) <= 10000:
        raise HTTPException(422, "질문은 1~10,000자로 입력해 주세요.")
    if payload.message is None and not payload.answers and payload.conditions is None:
        raise HTTPException(422, "질문 또는 조건을 입력해 주세요.")
    if payload.restart and (not payload.message or payload.answers is not None or payload.conditions is not None):
        raise HTTPException(422, "다시 보내기에는 질문만 입력해 주세요.")
    with accounts.guard(user_id), usage_limits.processing(user_id, client_ip(request)) as quota, \
            capture_node_timings() as node_timings:
        if user_id:
            response = _member_chat(payload, user_id, quota)
        else:
            if payload.conversation_id:
                raise HTTPException(401, "회원 대화에는 로그인이 필요합니다.")
            if payload.thread_id:
                guest = _guest(payload.thread_id, x_guest_session)
                with guest["lock"]:
                    _guest(payload.thread_id, x_guest_session)
                    used = usage_limits.consume(quota)
                    response = _chat_response(payload)
                    response["usage"] = used
                    guest["turns"].append((_guest_label(payload), copy.deepcopy(response)))
            else:
                _prune_guests()
                secret = x_guest_session or token_urlsafe(32)
                if len(secret) < 32 or len(secret) > 128:
                    raise HTTPException(422, "유효하지 않은 임시 세션입니다.")
                if not payload.message or payload.answers or payload.conditions is not None:
                    raise HTTPException(422, "새 대화에는 질문이 필요합니다.")
                used = usage_limits.consume(quota)
                response = _chat_response(payload)
                response["usage"] = used
                with _GUEST_LOCK:
                    _GUESTS[response["thread_id"]] = {"secret": secret, "used": monotonic(), "lock": threading.Lock(),
                        "turns": [(_guest_label(payload), copy.deepcopy(response))]}
                response["guest_session"] = secret
    response["timing"] = {
        **{name: round(value, 1) for name, value in node_timings.items()},
        "total_ms": round((perf_counter() - started) * 1000, 1),
    }
    return response


def _prune_guests():
    with _GUEST_LOCK:
        for expired, entry in list(_GUESTS.items()):
            if monotonic() - entry["used"] > _GUEST_TTL and entry["lock"].acquire(blocking=False):
                try:
                    GRAPH.checkpointer.delete_thread(expired)
                    del _GUESTS[expired]
                finally:
                    entry["lock"].release()


def _guest_label(payload: ChatRequest) -> str:
    return payload.user_label or payload.message or ("공사 조건 변경" if payload.conditions else
                                                    ", ".join(str(value) for value in (payload.answers or {}).values()))


def _guest(thread_id: str, secret: str | None) -> dict:
    _prune_guests()
    with _GUEST_LOCK:
        guest = _GUESTS.get(thread_id)
        if not guest or not secret or not compare_digest(guest["secret"], secret):
            raise HTTPException(404, "대화를 찾을 수 없거나 임시 대화가 만료되었습니다.")
        guest["used"] = monotonic()
        return guest


@app.get("/api/conversations")
def conversations(authorization: str | None = Header(default=None)):
    return chat_storage.list_conversations(chat_storage.require_member(authorization))


@app.get("/api/conversations/{conversation_id}")
def conversation(conversation_id: UUID, authorization: str | None = Header(default=None)):
    return chat_storage.read_conversation(str(conversation_id), chat_storage.require_member(authorization))


class RenameConversationRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)

    @field_validator('title')
    @classmethod
    def clean_title(cls, value: str) -> str:
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError('대화 이름에 제어 문자를 사용할 수 없습니다.')
        title = ' '.join(value.split())
        if not title:
            raise ValueError('대화 이름을 입력해 주세요.')
        return title


@app.patch("/api/conversations/{conversation_id}")
def rename_conversation(conversation_id: UUID, payload: RenameConversationRequest,
                        authorization: str | None = Header(default=None)):
    user_id = chat_storage.require_member(authorization)
    with accounts.guard(user_id):
        chat_storage.rename_conversation(str(conversation_id), user_id, payload.title)
    return {"id": str(conversation_id), "title": payload.title}


@app.post("/api/conversations/import-guest")
def import_guest(payload: GuestImportRequest, authorization: str | None = Header(default=None),
                 x_guest_session: str | None = Header(default=None)):
    user_id = chat_storage.require_member(authorization)
    if not re.fullmatch(r"[a-f0-9]{32}", payload.thread_id) or not x_guest_session or not 32 <= len(x_guest_session) <= 128:
        raise HTTPException(404, "임시 대화를 찾을 수 없습니다.")
    secret_hash = hashlib.sha256(x_guest_session.encode()).hexdigest()
    target = str(payload.conversation_id)
    with ExitStack() as stack:
        stack.enter_context(accounts.guard(user_id))
        conn = stack.enter_context(chat_storage.connection())
        with conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ('guest-import:' + payload.thread_id,))
            receipt = conn.execute("SELECT user_id::text, conversation_id::text, secret_hash FROM agent_state.guest_imports WHERE source_id=%s",
                                   (payload.thread_id,)).fetchone()
            if receipt:
                if receipt['user_id'] != user_id or not compare_digest(receipt['secret_hash'], secret_hash):
                    raise HTTPException(404, "임시 대화를 찾을 수 없습니다.")
                chat_storage.owned(conn, receipt['conversation_id'], user_id)
                return {"id": receipt['conversation_id']}
            guest = _guest(payload.thread_id, x_guest_session)
            stack.enter_context(guest['lock'])
            _guest(payload.thread_id, x_guest_session)
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (target,))
            if conn.execute("SELECT id FROM public.conversations WHERE id=%s", (target,)).fetchone():
                raise HTTPException(409, "이미 사용 중인 대화 ID입니다.")
            title = " ".join(guest['turns'][0][0].split())[:200] or '새 대화'
            conn.execute("INSERT INTO public.conversations(id,user_id,title) VALUES (%s,%s,%s)", (target, user_id, title))
            saver = PostgresSaver(conn)
            # Copy complete checkpoints, including pending interrupt writes. Replaying
            # user prompts would rerun paid calls and could produce different estimates.
            for checkpoint in reversed(list(GRAPH.checkpointer.list({"configurable": {"thread_id": payload.thread_id}}))):
                config = {"configurable": {"thread_id": target, "checkpoint_ns": checkpoint.config['configurable'].get('checkpoint_ns', '')}}
                if checkpoint.parent_config:
                    config['configurable']['checkpoint_id'] = checkpoint.parent_config['configurable']['checkpoint_id']
                saved_config = saver.put(config, checkpoint.checkpoint, checkpoint.metadata, checkpoint.checkpoint['channel_versions'])
                writes = defaultdict(list)
                for task_id, channel, value in checkpoint.pending_writes or []:
                    writes[task_id].append((channel, value))
                for task_id, values in writes.items():
                    saver.put_writes(saved_config, values, task_id)
            for label, guest_response in guest['turns']:
                response = {**guest_response, "thread_id": target}
                chat_storage.append_pair(conn, target, str(uuid4()), label, response)
            conn.execute('UPDATE public.answer_feedback SET user_id=%s,conversation_id=%s,thread_id=%s WHERE thread_id=%s AND user_id IS NULL',
                         (user_id, target, target, payload.thread_id))
            conn.execute("INSERT INTO agent_state.guest_imports(source_id,secret_hash,user_id,conversation_id) VALUES (%s,%s,%s,%s)",
                         (payload.thread_id, secret_hash, user_id, target))
        # Commit the complete transcript and state before disposing of guest memory.
        with _GUEST_LOCK:
            _GUESTS.pop(payload.thread_id, None)
        GRAPH.checkpointer.delete_thread(payload.thread_id)
    return {"id": target}


@app.delete("/api/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: UUID, authorization: str | None = Header(default=None)):
    user_id = chat_storage.require_member(authorization)
    with accounts.guard(user_id):
        chat_storage.delete_conversation(str(conversation_id), user_id)
    return Response(status_code=204)


@app.delete("/api/guest/conversations/{thread_id}", status_code=204)
def delete_guest_conversation(thread_id: str, x_guest_session: str | None = Header(default=None)):
    guest = _guest(thread_id, x_guest_session)
    with guest["lock"]:
        _guest(thread_id, x_guest_session)
        GRAPH.checkpointer.delete_thread(thread_id)
        with _GUEST_LOCK:
            _GUESTS.pop(thread_id, None)
    return Response(status_code=204)


def _member_chat(payload: ChatRequest, user_id: str, quota) -> dict:
    if not payload.conversation_id or not payload.request_id:
        raise HTTPException(422, "대화 ID와 요청 ID가 필요합니다.")
    conversation_id, request_id = str(payload.conversation_id), str(payload.request_id)
    if payload.thread_id and payload.thread_id != conversation_id:
        raise HTTPException(422, "대화 ID가 일치하지 않습니다.")
    label = payload.user_label or payload.message or ("공사 조건 변경" if payload.conditions else "조건 선택")
    if not label.strip() or len(label) > 10000:
        raise HTTPException(422, "질문은 1~10,000자로 입력해 주세요.")
    # Checkpoints and transcript use ONE transaction/connection. Failed turns roll back
    # both; a repeated request returns its committed result without invoking the agent.
    with chat_storage.connection() as conn, conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (conversation_id,))
        row = conn.execute("SELECT user_id::text FROM public.conversations WHERE id=%s", (conversation_id,)).fetchone()
        if row:
            chat_storage.owned(conn, conversation_id, user_id)
        else:
            if payload.thread_id or not payload.message or payload.conditions or payload.answers:
                raise HTTPException(404, "대화를 찾을 수 없습니다.")
            conn.execute("INSERT INTO public.conversations(id,user_id,title) VALUES (%s,%s,%s)",
                         (conversation_id, user_id, " ".join(label.split())[:200]))
        duplicate = conn.execute("SELECT payload FROM public.messages WHERE conversation_id=%s "
                                 "AND request_id=%s AND role='assistant'", (conversation_id, request_id)).fetchone()
        if duplicate:
            return {**duplicate["payload"], "usage": usage_limits.status(*quota)}
        used = usage_limits.consume(quota)
        graph = build_graph(PostgresSaver(conn))
        member_payload = payload.model_copy(update={"thread_id": conversation_id})
        response = _chat_response(member_payload, graph, keep_thread=True)
        response["usage"] = used
        chat_storage.append_pair(conn, conversation_id, request_id, label, response)
        return response


def _chat_response(payload: ChatRequest, graph=None, keep_thread=False) -> dict:
    graph = graph or GRAPH
    if payload.conditions is not None:
        return _change_conditions(payload, graph)
    config = None
    previous = None
    if payload.thread_id:
        candidate_config = {"configurable": {"thread_id": payload.thread_id}}
        snapshot = graph.get_state(candidate_config)
        if snapshot.next and not payload.restart:
            config = candidate_config
        elif snapshot.values:
            previous = snapshot.values
    if config is not None:
        thread_id = payload.thread_id
        resume = payload.answers if payload.answers else (payload.message or "")
        state = graph.invoke(Command(resume=resume,
                                     update={"basis_date": payload.basis_date.isoformat()}
                                     if payload.basis_date else None), config)
    else:
        thread_id = payload.thread_id if previous is not None or keep_thread else uuid4().hex
        config = {"configurable": {"thread_id": thread_id}}
        initial = new_state(payload.message or "", payload.basis_date.isoformat()
                            if payload.basis_date else None)
        if previous is not None:
            spec_id = previous.get("spec_id")
            spec = load_specs().get(spec_id) if spec_id else None
            work = _work_out(previous, spec)
            amount = (previous.get("statement") or {}).get("totals", {}).get("contract_amount")
            if amount is None:
                amount = (previous.get("statement") or {}).get("totals", {}).get("전체 물량 기준 도급액(부가세 포함)")
            initial["previous_context"] = {
                "previous_route": previous.get("route"),
                "work": work["title"] if work else None,
                "result": f"도급액 {int(amount):,}원" if isinstance(amount, (int, float)) else None,
            }
            initial.update(inputs={}, input_sources={}, questions=[], reply="", result={},
                           priced=None, statement=None, answer_source="", llm_info={},
                           route_confidence=None, route_reason="", route_source="rule")
        state = graph.invoke(initial, config)
    return _build_response(thread_id, state)
