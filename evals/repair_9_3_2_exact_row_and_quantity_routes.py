"""Use explicit source rows and add the source-stated detour quantity."""
from __future__ import annotations
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pymupdf
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.tools.calc.price import price_unit, select_rate_version
from backend.agent.tools.source.citation import resolve_cites
from pipeline.validate_drafts import load_chunks, file_sha256, validate_one

SPEC = ROOT / "data/drafts/specs/토목/9-3-2.json"
OUT = ROOT / "evals/runtime_validation/per-unit-9-3-2-source-audit-2026-10-19.json"


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    draft = package["draft"]
    table = next(item for item in draft["tables"] if item["id"] == "p496-t0")
    rate = draft["quantity_model"]["params"]["unit_rate_table"]
    # Independent original-cell audit. The PDF has one longitudinal row block
    # and six cross-section width rows, each with outside/inside subrows.
    with pymupdf.open(ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf") as doc:
        source_grid = doc[495].find_tables().tables[0].extract()
    source_headers = ["".join((source_grid[1][column] or "").split())
                      for column in range(4, 10)]
    normalized_columns = {"".join(name.split()): name for name in rate["trades"]}
    assert all(header in normalized_columns for header in source_headers)
    source_cell_checks = 0
    section_kind = None
    for source_row in source_grid[2:]:
        if source_row[0]:
            label = "".join(source_row[0].split())
            section_kind = "종단측량" if label == "종단측량" else "횡단측량"
        width_text = "".join((source_row[1] or "").split())
        width = width_text if "㎞" in width_text else width_text + ("" if width_text.endswith("m") else "m")
        phases = [part.strip() for part in (source_row[2] or "").splitlines()]
        assert len(phases) == 2 and set(phases) == {"외업", "내업"}
        for phase_index, phase_name in enumerate(phases):
            source_key = "10㎞양안왕복" if section_kind == "종단측량" else width
            exact_key = f"{source_key}_{phase_name}"
            assert exact_key in table["values"], exact_key
            for source_col, header in zip(range(4, 10), source_headers):
                raw_lines = [part.strip() for part in (source_row[source_col] or "").splitlines()]
                assert len(raw_lines) == 2
                field = normalized_columns[header]
                assert table["values"][exact_key].get(field) == raw_lines[phase_index], (
                    exact_key, field, table["values"][exact_key].get(field), raw_lines[phase_index])
                source_cell_checks += 1
    assert source_cell_checks == 84
    phase = {"name": "survey_phase", "type": "enum", "allowed_values": ["외업", "내업"],
             "unit": None, "required": True,
             "ask": "측량 공정이 외업입니까, 내업입니까?",
             "source": "PDF 440쪽 9-3-2 작업별 인원편성 표"}
    if not any(field.get("name") == "survey_phase" for field in draft["inputs"]):
        draft["inputs"].insert(2, phase)
    width_field = next(field for field in draft["inputs"] if field["name"] == "cross_section_width")
    width_field["allowed_values"] = ["해당없음", *[value for value in width_field["allowed_values"]
                                                      if value != "해당없음"]]
    rate["row_input_by_table"] = {"p496-t0": "survey_phase"}
    rate["column_input_by_table"] = {"p496-t0": None}
    route_rows = []
    long_rows = {key.rsplit("_", 1)[-1]: key for key in table["values"]
                 if key.startswith("10㎞양안왕복_")}
    assert set(long_rows) == {"외업", "내업"}
    for survey_phase, source_row in long_rows.items():
        route_rows.append({"when": {"survey_type": "종단측량", "cross_section_width": "해당없음",
                                     "survey_phase": survey_phase}, "row": source_row})
    widths = [value for value in next(field for field in draft["inputs"]
                                      if field["name"] == "cross_section_width")["allowed_values"]
              if value != "해당없음"]
    for width in widths:
        for survey_phase in ("외업", "내업"):
            candidates = [key for key in table["values"] if key.startswith(f"{width}_")
                          and key.endswith(f"_{survey_phase}")]
            assert len(candidates) == 1, (width, survey_phase, candidates)
            route_rows.append({"when": {"survey_type": "횡단측량", "cross_section_width": width,
                                         "survey_phase": survey_phase}, "row": candidates[0]})
    rate["row_selector_by_table"] = {"p496-t0": {
        "inputs": ["survey_type", "cross_section_width", "survey_phase"],
        "routes": route_rows,
    }}
    rate["trades_by_row"] = {
        row: [trade for trade in rate["trades"] if values.get(trade) not in (None, "-")]
        for row, values in table["values"].items()
    }
    rate["ignored_columns_by_table"] = {"p496-t0": ["비고"]}
    params = draft["quantity_model"]["params"]
    params["excluded_resources"] = [{
        "trade": "선박 및 인부", "when": {"need_ship": False},
        "source": "PDF 440쪽 [주] ③ 선박 및 선부는 필요한 경우에만 계상한다.",
        "cite": {"chunk_id": "p496-x14", "quote": "선박 및 선부는 필요한 경우에만 계상한다."},
    }]
    params["note_adjustments"] = [item for item in params.get("note_adjustments", [])
                                  if "우회" not in item.get("change", "")]
    params["quantity_additions"] = [{
        "input": "detour_distance", "when": {"survey_type": "종단측량"},
        "cite": {"chunk_id": "p496-x14", "quote": "우회 작업할 경우에는 그 거리만큼 품을 가산한다."},
    }]
    draft["blocked"] = [item for item in draft.get("blocked", [])
                        if "cross_section_width" not in str(item.get("blocked_if_all", []))]
    for width in width_field["allowed_values"]:
        if width == "해당없음":
            draft["blocked"].append({
                "condition": "횡단측량에 해당없음 폭을 선택",
                "blocked_if_all": [{"input": "survey_type", "op": "==", "value": "횡단측량"},
                                   {"input": "cross_section_width", "op": "==", "value": width}],
                "reason": "원문은 횡단측량의 폭별 행만 제공하므로 실제 폭이 확인되어야 합니다.",
                "source": "PDF 440쪽 p496-t0 횡단측량 폭 행", "cite": {"table_id": "p496-t0"},
            })
        else:
            draft["blocked"].append({
                "condition": "종단측량에 횡단 폭을 선택",
                "blocked_if_all": [{"input": "survey_type", "op": "==", "value": "종단측량"},
                                   {"input": "cross_section_width", "op": "==", "value": width}],
                "reason": "종단측량은 원문의 10km 양안왕복 행을 사용하며 횡단측량 폭은 적용하지 않습니다.",
                "source": "PDF 440쪽 p496-t0 종단측량 행", "cite": {"table_id": "p496-t0"},
            })
    draft["quantity_model"]["steps"] = [
        "p496-t0에서 종단측량은 양안왕복 행을, 횡단측량은 선택한 폭 행을 고른다.",
        "외업·내업 중 선택한 원문 행의 직종별 품을 10km 기준으로 환산한다.",
        "종단측량은 원문 [주] ④에 따라 우회 거리를 별도 물량으로 같은 품에 더한다.",
        "선박 및 선부는 필요하지 않으면 제외한다.",
    ]
    SPEC.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Exhaust all exact row routes with both ship states and zero/nonzero
    # detour. The source basis uses 10 km; quantity components remain separate.
    computed = blocked = 0
    checked_routes = []
    for route in route_rows:
        when = route["when"]
        for need_ship in (True, False):
            for detour in ("0", "1"):
                inputs = {**when, "quantity": "10", "detour_distance": detour,
                          "need_ship": need_ship}
                result = per_unit(draft, inputs)
                assert result.get("status") == "computed", (inputs, result)
                computed += 1
                trades = {line["name"] for line in result["unit_lines"]}
                ship_available = table["values"][route["row"]].get("선박 및 인부") not in (None, "-")
                assert ("선박 및 인부" in trades) == (need_ship and ship_available), (route, need_ship, trades, ship_available)
                additional = [line for line in result["unit_lines"]
                              if line.get("quantity_input") == "detour_distance"]
                assert bool(additional) == (when["survey_type"] == "종단측량" and detour != "0")
                checked_routes.append({"row": route["row"], "need_ship": need_ship,
                                       "detour_distance": detour, "status": result["status"],
                                       "base_lines": len(result["unit_lines"]) - len(additional),
                                       "detour_lines": len(additional)})
    for width in widths:
        result = per_unit(draft, {"survey_type": "종단측량", "cross_section_width": width,
                                  "survey_phase": "외업", "quantity": "10",
                                  "detour_distance": "0", "need_ship": True})
        if width == "해당없음":
            continue
        assert result.get("status") == "blocked", (width, result)
        blocked += 1
    mismatch = per_unit(draft, {"survey_type": "횡단측량", "cross_section_width": "해당없음",
                                "survey_phase": "외업", "quantity": "10",
                                "detour_distance": "0", "need_ship": True})
    assert mismatch.get("status") == "blocked", mismatch
    blocked += 1
    citations = resolve_cites(params["excluded_resources"][0]["cite"])
    citations += resolve_cites(params["quantity_additions"][0]["cite"])
    assert len(citations) == 2
    pricing_inputs = {"survey_type": "종단측량", "cross_section_width": "해당없음",
                      "survey_phase": "외업", "quantity": "10", "detour_distance": "2",
                      "need_ship": True}
    unit_result = per_unit(draft, pricing_inputs)
    priced = price_unit(draft, unit_result["unit_lines"], select_rate_version("2026-10-01"),
                        pricing_inputs, "2026-10-01")
    assert priced.get("status") in ("COMPLETE", "PARTIAL", "computed", "partial")
    priced_base = {line["name"]: line["quantity"] for line in priced["lines"]
                   if line.get("quantity_input") != "detour_distance"}
    priced_detour = {line["name"]: line["quantity"] for line in priced["lines"]
                     if line.get("quantity_input") == "detour_distance"}
    assert set(priced_base) == set(priced_detour) and len(priced_base) == 5
    assert all(__import__("fractions").Fraction(priced_detour[name])
               == __import__("fractions").Fraction(priced_base[name]) * 2
               for name in priced_base)
    validation = validate_one(SPEC, ROOT / "data/drafts", load_chunks(ROOT / "data/processed/chunks.all.jsonl"),
                              file_sha256(ROOT / "data/processed/chunks.all.jsonl"))
    assert validation["ok"], validation
    report_path = ROOT / "data/drafts/report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    old = next(item for item in report["results"]
               if item["path"].replace("\\", "/") == "specs/토목/9-3-2.json")
    if old["ok"] != validation["ok"]:
        report["ok"] += 1 if validation["ok"] else -1
    for key in ("with_format_issues", "with_citation_issues"):
        field = key.replace("with_", "")
        report[key] += int(bool(validation[field])) - int(bool(old[field]))
    report["results"][report["results"].index(old)] = validation
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = {"source_table": "p496-t0", "source_row_routes": len(route_rows),
              "original_cell_checks": source_cell_checks,
              "calculator_routes": computed, "blocked_routes": blocked,
              "offline_price_quantity_routes": 1,
              "source_quantity_rule": "detour distance added as separate priced quantity",
              "source_citations_resolved": len(citations), "validation_ok": validation["ok"],
              "cases": checked_routes}
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "cases"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
