"""route부터 fill까지의 그래프를 부르는 채팅 API."""

from __future__ import annotations

import re
from datetime import date
from typing import Optional
from uuid import uuid4
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from langgraph.types import Command
from pydantic import BaseModel

from agent.graph import build_graph
from agent.rules.specs import load_specs
from pipeline.render_sources import render_source
from agent.state import new_state
from agent.nodes.fill import _common_fields, _valid_for_field
from api.tables import add_tables, build_xlsx, estimate_filename
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
    basis_date: Optional[date] = None
    conditions: Optional[dict] = None


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
        "title": selection.get("section") or spec["title"],
        "confirmed": bool(selection.get("confirmed")),
    }


def _status_out(state: dict) -> str:
    return state.get("status", "RUNNING")


def _message_out(status: str, state: dict) -> str:
    if status == "PARTIAL":
        return state.get("reason") or "일위대가의 산정 가능한 금액을 계산했습니다. 미산정 항목은 부분 합계에서 제외했습니다."
    if status == "OK":
        return "일위대가 금액 계산이 끝났습니다."
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
                           if re.fullmatch(r"p\d+(?:-[tx]\d+)?", citation["internal_id"]) else {})}
            for citation in citations]


def _computed_result_out(raw: dict, spec: dict, review_status: str) -> dict:
    if "daily_volume_m3" not in raw:
        from fractions import Fraction
        from agent.tools.calc.daily_crew import _exact_text

        quantity = Fraction(raw["provenance"]["quantity"])
        lines = [{"kind": line["kind"], "name": line["name"],
                  "value": _exact_text(Fraction(line["exact"]) * quantity),
                  "unit": "인·일" if line["kind"] == "labor" else "대·일",
                  "crew": None, "rules": [], "source": line["source"],
                  "citations": _citations_out(line["citations"])}
                 for line in raw["unit_lines"]]
        return {"daily_volume": None, "work_days": None, "lines": lines,
                "unit_lines": [{**line, "citations": _citations_out(line["citations"])}
                               for line in raw["unit_lines"]],
                "unit_basis": raw["unit_basis"],
                "not_calculated": [{**item, "citations": _citations_out(resolve_cites(item.get("cite")))}
                                   for item in raw["not_calculated"]],
                "review_status": review_status}
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
            "raw_warnings": raw, "fallback_reason": search_info.get("fallback_reason")}


def _build_response(thread_id: str, state: dict) -> dict:
    status = _status_out(state)
    spec_id = state.get("spec_id", "")
    spec = load_specs().get(spec_id) if spec_id else None
    response = {
        "thread_id": thread_id,
        "status": status,
        "message": _message_out(status, state),
        "work": _work_out(state, spec),
        "questions": _questions_out(state.get("questions", [])),
        "inputs": _inputs_out(state, spec),
        "evidence": _evidence_out(state),
        "result": _result_out(state, spec),
        "priced": _priced_out(state.get("priced")),
        "statement": state.get("statement"),
        "answer": state.get("answer") or None,
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
    return {"status": "ok"}


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


def _finished_state(thread_id: str | None) -> dict:
    """계산이 끝난 thread의 그래프 state. 계산 결과가 없으면 404."""
    if not thread_id:
        raise HTTPException(status_code=404, detail="계산 결과가 없는 대화입니다")
    snapshot = GRAPH.get_state({"configurable": {"thread_id": thread_id}})
    if snapshot.next or not snapshot.values.get("statement"):
        raise HTTPException(status_code=404, detail="계산 결과가 없는 대화입니다")
    return snapshot.values


def _change_conditions(payload: ChatRequest) -> dict:
    """공종 입력은 두고 공사 조건만 바꿔 원가계산서와 설명 문장을 다시 만든다."""
    values = _finished_state(payload.thread_id)
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
    GRAPH.update_state(config, {"inputs": inputs, "input_sources": sources}, as_node="price")
    return _build_response(payload.thread_id, GRAPH.invoke(None, config))


@app.get("/api/export/{thread_id}.xlsx")
def export_xlsx(thread_id: str) -> Response:
    response = _build_response(thread_id, _finished_state(thread_id))
    filename = quote(estimate_filename(response), safe="")
    return Response(build_xlsx(response),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="estimate.xlsx"; filename*=UTF-8\'\'{filename}'})


@app.post("/api/chat")
def chat(payload: ChatRequest) -> dict:
    if payload.conditions is not None:
        return _change_conditions(payload)
    config = None
    if payload.thread_id:
        candidate_config = {"configurable": {"thread_id": payload.thread_id}}
        if GRAPH.get_state(candidate_config).next:
            config = candidate_config
    if config is not None:
        thread_id = payload.thread_id
        resume = payload.answers if payload.answers else (payload.message or "")
        state = GRAPH.invoke(Command(resume=resume,
                                     update={"basis_date": payload.basis_date.isoformat()}
                                     if payload.basis_date else None), config)
    else:
        thread_id = uuid4().hex
        config = {"configurable": {"thread_id": thread_id}}
        state = GRAPH.invoke(new_state(payload.message or "", payload.basis_date.isoformat()
                                       if payload.basis_date else None), config)
    return _build_response(thread_id, state)
