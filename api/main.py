"""route부터 fill까지의 그래프를 부르는 채팅 API."""

from __future__ import annotations

import re
from typing import Optional
from uuid import uuid4
from pathlib import Path

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from langgraph.types import Command
from pydantic import BaseModel

from agent.graph import build_graph
from agent.rules.specs import load_specs
from agent.state import new_state
from agent.tools.source.citation import resolve_cites

GRAPH = build_graph()

DEV_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

app = FastAPI(title="civilai-construction-risk-agent chat api")
SOURCES = Path(__file__).resolve().parents[1] / "data/processed/sources"
app.add_middleware(
    CORSMiddleware,
    allow_origins=DEV_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    thread_id: Optional[str] = None
    message: Optional[str] = None
    answers: Optional[dict] = None


_FIELD_LABELS = {
    "structure": "구조물",
    "placement": "타설방식",
    "vibrator_used": "진동기 사용",
}


def _label(field: dict) -> str:
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
            "hint": question.get("hint"),
            "default": question.get("default"),
            "decision_table": question.get("decision_table"),
            "reason": question.get("reason"),
        }
        for question in questions
    ]


def _inputs_out(state: dict, spec: dict | None) -> list[dict]:
    field_by_name = {field["name"]: field for field in spec["inputs"]} if spec else {}
    sources = state.get("input_sources", {})
    out = []
    for name, value in state.get("inputs", {}).items():
        field = field_by_name.get(name)
        label = _label(field) if field else name
        out.append({"name": name, "label": label, "value": value, "source": sources.get(name, "")})
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
        "title": selection.get("section") or spec["title"],
        "confirmed": bool(selection.get("confirmed")),
    }


def _status_out(state: dict) -> str:
    return state.get("status", "RUNNING")


def _message_out(status: str, state: dict) -> str:
    if status == "COMPUTED":
        return "계산이 끝났습니다. 금액은 다음 단계에서 계산됩니다."
    if status == "BLOCKED":
        return state.get("reason") or "원문 근거가 불명확해 계산을 보류합니다."
    if status == "EVIDENCE_ONLY":
        return state.get("reason") or "아직 계산을 지원하지 않는 공종입니다. 근거만 안내합니다."
    if status == "ERROR":
        return state.get("reason") or "처리 중 오류가 발생했습니다."
    return state.get("reason") or ""


def _source_label(cell: dict) -> str:
    return f"{cell['table']} {cell['row']}·{cell['column']} {cell['value']}"


def _rule_label(rule: dict) -> str:
    when = ", ".join(f"{name}={value}" for name, value in rule["when"].items())
    return f"{when} → {rule['change']} ({rule['source']})"


def _citations_out(citations: list[dict]) -> list[dict]:
    return [{**citation, **({"image_url": f"/api/source/{citation['internal_id']}.png"}
                           if citation["item"] == "표" else {})} for citation in citations]


def _computed_result_out(raw: dict, spec: dict, review_status: str) -> dict:
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
    equipment_name, equipment_unit = next(iter(raw["equipment_units"].items()))
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
    equipment_source = raw["provenance"]["equipment_days"][equipment_name]
    lines.append({
        "kind": "equipment",
        "name": equipment_name,
        "value": raw["equipment_days"][equipment_name],
        "unit": equipment_unit,
        "crew": None,
        "rules": [],
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
    }


def _result_out(state: dict, spec: dict | None) -> dict | None:
    status = state.get("status")
    raw = state.get("result")
    if not raw:
        return None
    if status == "BLOCKED":
        return {**raw, "citations": _citations_out(raw.get("citations", []))}
    if status == "COMPUTED" and spec:
        return _computed_result_out(raw, spec, state.get("review_status", ""))
    return None


def _search_out(state: dict) -> dict:
    search_info = state.get("search_info", {})
    method = search_info.get("method", "")
    warnings = list(search_info.get("warnings", []))
    if method and method not in ("hybrid", "bm25(오프라인)") and not warnings:
        warnings = [f"임베딩 검색이 꺼져 단어 검색({method})으로만 찾았습니다"]
    return {"method": method, "api_calls": search_info.get("api_calls", 0), "warnings": warnings}


def _build_response(thread_id: str, state: dict) -> dict:
    status = _status_out(state)
    spec_id = state.get("spec_id", "")
    spec = load_specs().get(spec_id) if spec_id else None
    return {
        "thread_id": thread_id,
        "status": status,
        "message": _message_out(status, state),
        "work": _work_out(state, spec),
        "questions": _questions_out(state.get("questions", [])),
        "inputs": _inputs_out(state, spec),
        "evidence": _evidence_out(state),
        "result": _result_out(state, spec),
        "search": _search_out(state),
    }


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/source/{table_id}.png")
def source_image(table_id: str) -> FileResponse:
    if not re.fullmatch(r"p\d+-t\d+", table_id):
        raise HTTPException(status_code=404, detail="표 이미지를 찾을 수 없습니다")
    path = SOURCES / f"{table_id}.png"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="표 이미지를 찾을 수 없습니다")
    return FileResponse(path, media_type="image/png")


@app.post("/api/chat")
def chat(payload: ChatRequest) -> dict:
    config = None
    if payload.thread_id:
        candidate_config = {"configurable": {"thread_id": payload.thread_id}}
        if GRAPH.get_state(candidate_config).next:
            config = candidate_config
    if config is not None:
        thread_id = payload.thread_id
        resume = payload.answers if payload.answers else (payload.message or "")
        state = GRAPH.invoke(Command(resume=resume), config)
    else:
        thread_id = uuid4().hex
        config = {"configurable": {"thread_id": thread_id}}
        state = GRAPH.invoke(new_state(payload.message or ""), config)
    return _build_response(thread_id, state)
