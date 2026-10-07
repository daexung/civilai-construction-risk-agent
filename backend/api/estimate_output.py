"""집계된 견적 세션을 기존 응답 형식으로 바꾸고, 같은 결과로 Excel을 만든다(단계 C1).

화면용 출력과 Excel은 모두 이 build_output 결과(같은 집계·같은 원가계산서)를 쓴다.
기존 응답 형식 함수(_work_out·_inputs_out·_computed_result_out·_priced_out·_conditions_out)와
tables.add_tables·build_xlsx를 그대로 재사용한다. 운영 라우트에는 아직 연결하지 않는다.
"""

from __future__ import annotations

from datetime import date

from backend.agent.estimate.state import EstimateSession
from backend.agent.rules.specs import load_specs
from backend.api.main import _computed_result_out, _conditions_out, _inputs_out, _priced_out, _work_out
from backend.api.tables import add_tables, build_xlsx, estimate_filename

# 세션 출처 → 기존 화면의 출처 표기
_SOURCE_LABEL = {"request": "질문", "plan": "질문", "answer": "선택", "default": "기본값", "default_division": "기본값(부문)"}


class EstimateNotReady(ValueError):
    """확정된 견적이 없어 견적서·Excel을 만들 수 없다(질문 대기·공통 조건 확인·계산 결과 없음)."""


def _common_state(session: EstimateSession) -> dict:
    return {"inputs": {name: entry["value"] for name, entry in session["common_conditions"].items()},
            "input_sources": {name: _SOURCE_LABEL.get(entry["source"], entry["source"])
                              for name, entry in session["common_conditions"].items()}}


def _item_state(item: dict, common: dict) -> dict:
    """기존 출력 함수가 읽는 단일 공종 상태 모양. 공종 조건 + 세션 공통 조건."""
    inputs = {name: entry["value"] for name, entry in item["conditions"].items()}
    sources = {name: _SOURCE_LABEL.get(entry["source"], entry["source"]) for name, entry in item["conditions"].items()}
    return {"spec_id": item.get("selected_spec_id", ""), "selection": item.get("selection") or {},
            "inputs": {**inputs, **common["inputs"]}, "input_sources": {**sources, **common["input_sources"]}}


def _item_out(item: dict, common: dict, included: bool) -> dict:
    spec = load_specs().get(item.get("selected_spec_id") or "")
    state = _item_state(item, common)
    priced = item.get("priced_result") if included else None
    return {"item_id": item["item_id"], "query": item["request_text"], "status": item["status"],
            "reason": item.get("reason") or "", "included": included,
            "work": _work_out(state, spec), "inputs": _inputs_out(state, spec) if spec else [],
            "result": _computed_result_out(item["computed_result"], spec, item.get("review_status", ""))
            if included and spec else None,
            "priced": _priced_out(priced)}


def build_output(session: EstimateSession) -> dict:
    """견적 상태와 통합 결과. 항목 하나면 기존 단일 공종 응답과 같은 모양이다."""
    result = session.get("aggregate_result") or {"status": "PENDING"}
    status = result["status"]
    common = _common_state(session)
    included = set(result.get("included", []))
    items = [_item_out(session["items"][item_id], common, item_id in included) for item_id in session["item_order"]]
    output = {"estimate_id": session["estimate_id"], "estimate_status": status,
              "status": {"COMPLETE": "OK", "PARTIAL": "PARTIAL"}.get(status, "MISSING_INFO" if status in ("PENDING", "NEEDS_COMMON") else "NO_RESULT"),
              "basis_date": session.get("basis_date") or date.today().isoformat(),
              "questions": list(session["pending_questions"].values()), "notices": session.get("notices", []),
              "excluded": result.get("excluded", []), "statement": session.get("statement"),
              "conditions": _conditions_out(common) if status in ("COMPLETE", "PARTIAL") else []}
    if len(items) == 1 and items[0]["included"]:
        single = items[0]
        output.update(work=single["work"], inputs=single["inputs"], result=single["result"], priced=single["priced"],
                      items=[])  # 기존 단일 공종 응답과 같은 모양(tables가 응답 자신을 공종으로 본다)
    else:
        output.update(work=None, inputs=[], result=None, priced=None, items=items)
    output["tables"] = add_tables(output)
    return output


def build_estimate_xlsx(session: EstimateSession) -> tuple[bytes, str, dict]:
    """확정된 견적만 Excel로 만든다. 질문 대기·계산 결과 없음이면 EstimateNotReady."""
    output = build_output(session)
    if output["estimate_status"] not in ("COMPLETE", "PARTIAL") or not output["statement"]:
        raise EstimateNotReady(f"견적서를 만들 수 없어요: {output['estimate_status']}")
    return build_xlsx(output), estimate_filename(output), output
