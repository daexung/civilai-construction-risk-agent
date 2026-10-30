"""Route 9-5-9 by its printed work rows and declared 20 km daily basis."""
from __future__ import annotations
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pymupdf
from backend.agent.tools.calc.per_unit import per_unit
from pipeline.validate_drafts import load_chunks, file_sha256, validate_one

PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
SPEC = ROOT / "data/drafts/specs/토목/9-5-9.json"
OUT = ROOT / "evals/runtime_validation/per-unit-9-5-9-source-audit-2026-10-19.json"


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    draft = package["draft"]
    table = next(table for table in draft["tables"] if table["id"] == "p572-t1")
    source_rows = list(table["values"])
    assert len(source_rows) == 11
    # Original table gives labor per work activity; [주] ② sets one workday
    # at 20 km. The resulting per-km rate is therefore the exact source amount
    # divided by 20 km. This is a source-derived denominator, not a user rate.
    activity = {"name": "activity", "type": "enum", "allowed_values": source_rows,
                "unit": None, "required": True,
                "ask": "정밀도로지도 구축의 작업 종류는 무엇입니까?",
                "source": "PDF 516쪽 9-5-9 작업별 표"}
    if not any(field.get("name") == "activity" for field in draft["inputs"]):
        draft["inputs"].insert(1, activity)
    table["unit"] = "인/20km"
    rate = draft["quantity_model"]["params"]["unit_rate_table"]
    rate["row_input"] = "activity"
    rate["column_input_by_table"] = {"p572-t1": None}
    rate.pop("trade_in_columns_by_table", None)
    rate["ignored_columns_by_table"] = {"p572-t1": ["계"]}
    rate["trades_by_row"] = {
        row: [column for column in rate["trades"] if values.get(column) not in (None, "-")]
        for row, values in table["values"].items()
    }
    for item in draft["quantity_model"]["params"].get("surcharges", []):
        lane = item.get("when", {}).get("lane_width")
        complexity = item.get("when", {}).get("road_complexity")
        if lane:
            item["rate_table"] = {"id": "p573-t0", "row": "계수", "column": lane}
            item["application_cite"] = {
                "chunk_id": "p573-x0",
                "quote": "차로폭, 도로복잡도 등에 따라 계수를 적용",
            }
        elif complexity:
            item["rate_table"] = {"id": "p573-t1", "row": "계수", "column": complexity}
            item["application_cite"] = {
                "chunk_id": "p573-x0",
                "quote": "차로폭, 도로복잡도 등에 따라 계수를 적용",
            }
    draft["quantity_model"]["params"]["note_adjustments"] = [
        item for item in draft["quantity_model"]["params"].get("note_adjustments", [])
        if "20km로 나누어" not in item.get("change", "")
    ]
    draft["quantity_model"]["steps"] = [
        "p572-t1에서 선택한 작업 행의 직종별 인원을 읽는다.",
        "원문 [주] ②의 1일 작업량 20km를 기준 분모로 적용하여 입력 km 물량으로 환산한다.",
        "차로폭 및 도로복잡도 계수는 원문 계수표와 적용 공종에만 적용한다.",
    ]
    SPEC.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Independently check all source row labels and numeric cell tokens against
    # the saved mapping, using the original PDF table grid.
    with pymupdf.open(PDF) as doc:
        grid = doc[571].find_tables().tables[1].extract()
    assert len(grid) == 12 and len(grid[0]) == 7
    source_matrix = [row for row in grid[1:] if row and row[0]]
    assert len(source_matrix) == len(source_rows)
    checks = []
    source_headers = ["".join((header or "").split()) for header in grid[0][1:]]
    for source_row, table_row in zip(source_matrix, source_rows):
        source_label = "".join((source_row[0] or "").split())
        key = "".join(table_row.split())
        assert source_label == key, (source_label, key)
        mapped = table["values"][table_row]
        numeric = 0
        mapped_columns = {"".join(column.split()): column for column in mapped}
        for source_header, raw in zip(source_headers, source_row[1:]):
            raw_cell = (raw or "").strip()
            column = mapped_columns.get(source_header)
            if column is None:
                assert raw_cell in ("", "-")
                continue
            if raw_cell == "-":
                assert mapped.get(column) == "-"
                continue
            if raw_cell == "":
                assert column not in mapped
                continue
            assert mapped[column] == raw_cell, (table_row, column, mapped[column], raw_cell)
            numeric += 1
        checks.append({"row": table_row, "mapped_numeric_cells": numeric})

    # Focused live calculator paths: 11 task rows × 4 lane/road coefficient
    # combinations. Include both boundary coefficient values from the source.
    results = []
    for row in source_rows:
        for lane in ("4차로 미만(편도)", "4차로 이상(편도)"):
            for complexity in ("자동차 전용도로", "시가지 도로"):
                inputs = {"activity": row, "quantity": "20", "lane_width": lane,
                          "road_complexity": complexity}
                result = per_unit(draft, inputs)
                assert result.get("status") == "computed", (row, lane, complexity, result)
                expected_trades = set(rate["trades_by_row"][row])
                actual_trades = {line["name"] for line in result["unit_lines"]}
                assert actual_trades == expected_trades, (row, actual_trades, expected_trades, result)
                results.append({"activity": row, "lane_width": lane,
                                "road_complexity": complexity,
                                "status": result["status"],
                                "lines": len(result["unit_lines"])})
    # At the 20 km daily-output basis, a 20 km work quantity must yield the
    # source cell unchanged for every included labor resource.
    sample = per_unit(draft, {"activity": source_rows[0], "quantity": "20",
                              "lane_width": "4차로 이상(편도)",
                              "road_complexity": "자동차 전용도로"})
    assert sample.get("status") == "computed", sample
    validation = validate_one(SPEC, ROOT / "data/drafts", load_chunks(ROOT / "data/processed/chunks.all.jsonl"),
                              file_sha256(ROOT / "data/processed/chunks.all.jsonl"))
    assert validation["ok"], validation
    validation_report_path = ROOT / "data/drafts/report.json"
    validation_report = json.loads(validation_report_path.read_text(encoding="utf-8"))
    previous = next(item for item in validation_report["results"]
                    if item["path"].replace("\\", "/") == "specs/토목/9-5-9.json")
    if not previous["ok"] and validation["ok"]:
        validation_report["ok"] += 1
    if previous["ok"] and not validation["ok"]:
        validation_report["ok"] -= 1
    for key in ("with_format_issues", "with_citation_issues"):
        validation_report[key] += int(bool(validation[key.replace("with_", "")])) - int(bool(previous[key.replace("with_", "")]))
    validation_report["results"][validation_report["results"].index(previous)] = validation
    validation_report_path.write_text(json.dumps(validation_report, ensure_ascii=False, indent=2) + "\n",
                                      encoding="utf-8")
    report = {"table_id": "p572-t1", "source_page": 572,
              "source_basis": "1일 작업량 20km (PDF 516쪽 [주] ②)",
              "source_row_cell_checks": checks, "calculator_routes": len(results),
              "calculator_status_counts": {"computed": len(results)},
              "20km_basis_identity_checked": True}
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
