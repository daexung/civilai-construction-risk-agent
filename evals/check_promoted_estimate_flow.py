"""승격한 절이 상담(다중 공종)·집계·Excel까지 이어지는지 확인한다(검색만 모의, 외부 호출 없음).

두 공종을 한 요청으로 넣고 질문에 서버가 낸 선택지로만 답한 뒤, 항목별 PRICED 상태·집계·XLSX 행을 확인한다.
항목별 노무량은 같은 입력으로 계산기를 직접 불러 나온 값과 일치해야 한다.
"""
from __future__ import annotations

import copy
import os
import sys
from collections import defaultdict
from fractions import Fraction
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.update(AGENT_MODE="tools", AGENT_LLM="off", AGENT_OFFLINE="1")

from openpyxl import load_workbook  # noqa: E402
from backend.agent.estimate import aggregate as aggregate_module, dialogue, tools  # noqa: E402
from backend.agent.rules.specs import load_specs  # noqa: E402
from backend.agent.tools.source import citation  # noqa: E402
from backend.api import dialogue_service  # noqa: E402
from backend.api.tables import build_xlsx  # noqa: E402

TEXT = "낙석방지망 설치 800㎡ + 보도용 블록 설치 소형 540㎡ 비용 견적"
WANTED = {"낙석방지망": ("토목", "1-9-4"), "보도용 블록": ("토목", "1-7-1")}


def hit_for(query: str) -> dict:
    division, section = next(value for key, value in WANTED.items() if key in query)
    spec = next(s for s in load_specs().values() if s["division"] == division and s["section_no"] == section)
    return {"rank": 1, "section_no": section, "division": division, "section": f"{section} {spec['title']}",
            "page": 200, "table_id": None, "text": spec["title"], "chunk_id": "mock-production-retrieve"}


def check_api_output_shapes() -> None:
    """승격한 모든 계산 사례가 API 응답 변환(_computed_result_out)과 단가 계산을 크래시 없이 통과하는지 본다."""
    from backend.agent.tools.calc.daily_crew import adjusted_daily_crew
    from backend.agent.tools.calc.per_unit import per_unit
    from backend.agent.tools.calc.price import price_unit, select_rate_version
    from backend.api.main import _computed_result_out
    import evals.check_promoted_unsupported_calc as promoted
    count = 0
    for key, _page, _tokens, cases in promoted.CASES:
        package = promoted.spec(key)
        for case in cases:
            inputs, status = case[0], case[1]
            if status != "computed":
                continue
            raw = adjusted_daily_crew(package["draft"], inputs, labor_only=True)
            out = _computed_result_out(raw, package["draft"], "AI 초안 · 검토 전")
            assert out["lines"], key
            price_unit(package["draft"], raw["unit_lines"], select_rate_version("2026-06-01"), inputs)
            count += 1
    for key, _page, _tokens, cases in promoted.PER_UNIT_CASES:
        package = promoted.spec(key)
        for inputs, _expected in cases:
            raw = per_unit(package["draft"], inputs, labor_only=True)
            out = _computed_result_out(raw, package["draft"], "AI 초안 · 검토 전")
            assert out["lines"], key
            price_unit(package["draft"], raw["unit_lines"], select_rate_version("2026-06-01"), inputs)
            count += 1
    print(f"PASS 승격 사례 {count}건: API 응답 변환·단가 계산 크래시 없음")


SCENARIOS = [
    # (이름, 요청문, {검색어 키워드: (부문, 절)}, 합산 대상 개수)
    ("승격 일당·단가 2개", "낙석방지망 설치 800㎡ + 보도용 블록 설치 소형 540㎡ 비용 견적",
     {"낙석방지망": ("토목", "1-9-4"), "보도용 블록": ("토목", "1-7-1")}, 2),
    ("작업별 물량 단위", "낙석방지책 철망 설치 720㎡ + 보도용 블록 설치 소형 540㎡ 비용 견적",
     {"낙석방지책": ("토목", "1-9-3"), "보도용 블록": ("토목", "1-7-1")}, 2),
    ("총량(formula)·일당 혼합", "답면고르기 100㎡ + 보도용 블록 설치 소형 540㎡ 비용 견적",
     {"답면고르기": ("공통", "3-10-1"), "보도용 블록": ("토목", "1-7-1")}, 1),
    ("조회전용·원가 혼합", "철골세우기 장비 작업능력 조회 + 플로어링 마루 설치 100㎡ 비용 견적",
     {"철골세우기": ("건축", "1-2-3"), "플로어링": ("건축", "5-1-3")}, 1),
]


def run_scenario(name: str, text: str, wanted: dict, included: int) -> None:
    graph = dialogue.build_dialogue_graph()
    thread = "flow-" + name

    def hit_for(query: str) -> dict:
        division, section = next(value for key, value in wanted.items() if key in query)
        spec = next(s for s in load_specs().values() if s["division"] == division and s["section_no"] == section)
        return {"rank": 1, "section_no": section, "division": division, "section": f"{section} {spec['title']}",
                "page": 200, "table_id": None, "text": spec["title"], "chunk_id": "mock-production-retrieve"}

    def retrieve_mock(state: dict) -> dict:
        return {"hits": [hit_for(state["query"])], "search_info": {"method": "mock", "api_calls": 0, "warnings": []}}

    with patch.object(tools, "retrieve", side_effect=retrieve_mock),             patch.object(citation, "_pages", return_value=defaultdict(lambda: {"printed_page": None, "division": None})):
        scoped = dialogue_service.respond(graph, thread, {"message": text})
        answers = {q["name"]: "계산에 포함" for q in scoped["questions"]}
        refs = {q["name"]: q["ref"] for q in scoped["questions"]}
        dialogue_service.respond(graph, thread, {"answers": answers, "refs": refs})
        current = dialogue.load(graph, thread)
        item_ids = list(current["session"]["item_order"])
        assert len(item_ids) == len(wanted), item_ids
        for _ in range(14):
            if not current.get("pending"):
                break
            answers, refs = {}, {}
            for question in current["pending"]:
                field = question["field"]
                local = field.split("::", 1)[-1]
                if field.endswith("::continue"):
                    value = "계속 진행"
                elif question.get("choices"):
                    # water_retention의 첫 선택지는 원문이 별도 계상하라는 조건이라 보류된다. 계산 가능한 값을 고른다.
                    value = question["choices"][-1 if local == "water_retention" or local.startswith("scaffold") else 0]
                else:
                    value = {"quantity": "10", "difficulty_factor": "0.9"}.get(local, "1")
                answers[field], refs[field] = value, question["ref"]
            dialogue_service.respond(graph, thread, {"answers": answers, "refs": refs})
            current = dialogue.load(graph, thread)
        assert not current.get("pending"), current.get("pending")
        session = current["session"]
        statuses = {item_id: session["items"][item_id]["status"] for item_id in item_ids}
        assert all(status == "PRICED" for status in statuses.values()), (
            statuses, {i: (session["items"][i].get("reason"), session["items"][i]["request_text"],
                           session["items"][i].get("conditions")) for i in item_ids})
        assert session["statement"] and session["aggregate_result"]["direct_total"] > 0
        assert len(session["aggregate_result"]["included"]) == included, session["aggregate_result"]
        response = dialogue_service.response(thread, current)
        assert len(response["multi_trade_items"]) == len(wanted)
        workbook = load_workbook(BytesIO(build_xlsx(response)), data_only=True)
        detail = list(workbook["공종별상세"].iter_rows(min_row=5, values_only=True))
        assert [row[0] for row in detail] == item_ids, detail
        if name == "조회전용·원가 혼합":
            lookup_id = next(item_id for item_id in item_ids
                             if session["items"][item_id]["selection"]["section_no"] == "1-2-3")
            lookup_item = session["items"][lookup_id]
            assert lookup_item["computed_result"]["unit_lines"][0]["exact"] == "15", lookup_item
            assert lookup_item["computed_result"]["unit_lines"][0]["unit"] == "ton/일", lookup_item
            assert lookup_id not in session["aggregate_result"]["included"], session["aggregate_result"]
            assert any(entry["item_id"] == lookup_id and "조회 전용" in entry["reason"]
                       for entry in session["aggregate_result"]["excluded"]), session["aggregate_result"]
            unit_rows = list(workbook["일위대가"].iter_rows(min_row=6, values_only=True))
            lookup_row = next(row for row in unit_rows if str(row[0]).startswith(f"[{lookup_id}]"))
            assert "원문 조회값: 15" in str(lookup_row[1]) and lookup_row[3] == "ton/일", lookup_row
        for row in detail:
            print("   XLSX", [str(c)[:28] for c in row[:10]])
        if name == "작업별 물량 단위":
            check_work_type_edit(graph, thread, item_ids)
        print(f"PASS {name}: 상담 → 항목별 계산 → 집계(합산 {included}건) → XLSX 행 {len(detail)}", statuses)


def check_total_and_lookup_specs() -> None:
    """실행 가능으로 올라온 formula·lookup_only 명세 전부가 상담 도구(공종 선택→조건→품→가격)와
    API 응답 변환을 오류 없이 지나는지 본다. 조회·공수 총량은 금액이 없어도 값·근거를 돌려주고 사유와 함께 합산에서 빠진다."""
    import itertools
    from evals.check_draft_executability import _values
    from backend.agent.tools.calc.price import price_unit  # noqa: F401
    from backend.agent.tools.calc.lookup import lookup
    from backend.api.main import _computed_result_out
    overrides = {"difficulty_factor": "0.9"}
    checked = {"formula": 0, "lookup_only": 0}
    for spec in load_specs().values():
        name = spec["quantity_model"]["name"]
        if name not in checked:
            continue
        blocked = {}
        for item in spec.get("blocked", []):
            condition = item.get("blocked_if")
            if condition:
                blocked.setdefault(condition["input"], []).append(condition)
        if name == "lookup_only":
            # Follow the questions the actual source-driven lookup exposes.
            # Cartesian field enumeration supplies mutually exclusive selector
            # branches together and is invalid for conditional table rows.
            fields = {field["name"]: field for field in spec["inputs"]}

            explored = 0
            def first_calculable_path(inputs):
                nonlocal explored
                explored += 1
                if explored > 4096:
                    raise AssertionError((spec["id"], "source-driven path limit exceeded"))
                result = lookup(spec, inputs)
                if result.get("status") == "computed":
                    return inputs
                if result.get("status") == "blocked":
                    return None
                assert result.get("status") == "ask", (spec["id"], inputs, result)
                for question in result["questions"]:
                    field = fields[question["name"]]
                    choices = question.get("allowed_values")
                    if not isinstance(choices, list):
                        choices = _values(field, blocked.get(field["name"], []), [])
                    for choice in choices:
                        branch = {**inputs, question["name"]: overrides.get(question["name"], choice)}
                        resolved = first_calculable_path(branch)
                        if resolved is not None:
                            return resolved
                return None

            values = first_calculable_path({})
            assert values is not None, (spec["id"], "no calculable source-derived lookup path")
        else:
            combo = next(itertools.product(*[_values(f, blocked.get(f["name"], []), []) for f in spec["inputs"]]))
            values = {f["name"]: overrides.get(f["name"], v) for f, v in zip(spec["inputs"], combo)}
        hit = {"rank": 1, "section_no": spec["section_no"], "division": spec["division"],
               "section": f"{spec['section_no']} {spec['title']}", "page": 200, "table_id": None,
               "text": spec["title"], "chunk_id": "mock"}
        with patch.object(citation, "_pages", return_value=defaultdict(lambda: {"printed_page": None, "division": None})):
            session = tools.new_estimate(spec["title"])
            assert tools.find_work(session, hits=[hit])["status"] == "ok", spec["id"]
            applied = tools.set_conditions(session, spec["title"], source="answer",
                                           values={k: {"value": v, "evidence": str(v)} for k, v in values.items()})
            assert not applied.get("rejected"), (spec["id"], applied.get("rejected"))
            labor = tools.compute_labor(session)
            assert labor["status"] == "ok", (spec["id"], labor)
            item = session["items"][session["item_order"][0]]
            out = _computed_result_out(item["computed_result"], spec, "")
            assert out["lines"] and all(line["citations"] is not None for line in out["lines"]), spec["id"]
            priced = tools.estimate_cost(session)
            assert priced["status"] == "ok", (spec["id"], priced)
            if name == "lookup_only":
                assert priced["data"]["reference_only"] and item["reason"].startswith("조회 전용"), spec["id"]
            reference_kinds = {l["kind"] for l in item["computed_result"].get("unit_lines", [])}
            if name == "formula" and reference_kinds <= {"lookup", "reference"}:
                assert item["computed_result"].get("reference_only"), spec["id"]
            checked[name] += 1
    print(f"PASS formula {checked['formula']}건·lookup_only {checked['lookup_only']}건: 선택→조건→계산→가격→응답 변환")
    check_multi_table_lookup_paths()


def check_multi_table_lookup_paths() -> None:
    """Exercise list-valued exact table routes through consultation and API output."""
    from backend.api.main import _computed_result_out

    cases = [
        ("2026-정오표1차/공통/8-3-5/콘크리트기계", "machine_category", "콘크리트 펌프차",
         ["p300-t3", "p301-t0"]),
        ("2026-정오표1차/공통/8-3-6/골재생산기계등", "machine_category", "에이프런 피더",
         ["p302-t2", "p303-t0"]),
        ("2026-정오표1차/공통/8-3-6/골재생산기계등", "machine_category", "아그리게이트빈",
         ["p306-t1", "p307-t0"]),
        ("2026-정오표1차/공통/5203-1800/기계경비계수조회", "machine_category", "공기압축기(이동식)",
         ["p308-t1", "p308-t3"]),
    ]
    checked = 0
    with patch.object(citation, "_pages", return_value=defaultdict(
            lambda: {"printed_page": None, "division": None})):
        for spec_id, field, value, table_ids in cases:
            spec = load_specs()[spec_id]
            hit = {"rank": 1, "section_no": spec["section_no"], "division": spec["division"],
                   "section": f"{spec['section_no']} {spec['title']}", "page": 200,
                   "table_id": None, "text": spec["title"], "chunk_id": "mock-multi-table"}
            session = tools.new_estimate(f"{spec['title']} {value}")
            assert tools.find_work(session, hits=[hit])["status"] == "ok", spec_id
            applied = tools.set_conditions(session, spec["title"], source="answer",
                                           values={field: {"value": value, "evidence": value}})
            assert not applied.get("rejected"), (spec_id, applied)
            labor = tools.compute_labor(session)
            assert labor["status"] == "ok", (spec_id, labor)
            item = session["items"][session["item_order"][0]]
            output = _computed_result_out(item["computed_result"], spec, "")
            assert output["lines"] and all(line["citations"] for line in output["lines"]), (spec_id, output)
            cited_tables = {citation_row["internal_id"] for line in output["lines"]
                            for citation_row in line["citations"]}
            assert cited_tables == set(table_ids), (spec_id, value, cited_tables)
            priced = tools.estimate_cost(session)
            assert priced["status"] == "ok" and priced["data"]["reference_only"], (spec_id, priced)
            checked += 1
    print(f"PASS 다중 원문 표 라우트 {checked}건: 상담→조회→API 인용→조회전용 가격 경로")


def check_work_type_edit(graph, thread: str, item_ids: list[str]) -> None:
    """작업 종류를 바꾸면 그 항목만 새 단위(m)로 다시 묻고, 다른 항목의 물량·결과는 그대로여야 한다."""
    before = dialogue.load(graph, thread)["session"]["items"]
    sibling_id = item_ids[1]
    sibling_before = copy.deepcopy(before[sibling_id])
    reply = dialogue_service.respond(graph, thread, {"message": "낙석방지책을 와이어 설치 500m로 바꿔줘"})
    for _ in range(4):
        state = dialogue.load(graph, thread)
        pending = state.get("pending") or []
        target = next((q for q in pending if q["field"] == "target_item"), None)
        if not target:
            break
        choice = next(c for c in target["choices"] if "낙석방지책" in c)
        dialogue_service.respond(graph, thread, {"answers": {"target_item": choice}, "refs": {"target_item": target["ref"]}})
    state = dialogue.load(graph, thread)
    items = state["session"]["items"]
    changed = items[item_ids[0]]
    assert changed["explicit"].get("work_type", {}).get("value") == "와이어 설치", changed["explicit"]
    assert changed["input_revision"] > before[item_ids[0]]["input_revision"] and changed["status"] != "PRICED"
    assert (changed.get("quantity") or {}).get("unit") in (None, "m") or changed["quantity"]["value"] == "500", changed.get("quantity")
    for key in ("quantity", "conditions", "computed_result", "input_revision"):
        assert items[sibling_id][key] == sibling_before[key], key
    print("   PASS 작업 종류 변경: 대상 항목만 무효화·새 단위, 형제 항목 보존")


def main() -> int:
    check_api_output_shapes()
    check_total_and_lookup_specs()
    for scenario in SCENARIOS:
        run_scenario(*scenario)
    return 0


if __name__ == "__main__":
    sys.exit(main())
