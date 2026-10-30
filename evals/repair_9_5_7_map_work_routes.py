"""Connect 9-5-7's exact work tables and terrain multipliers."""
from __future__ import annotations
import json, sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.tools.calc.price import price_unit, select_rate_version
from pipeline.validate_drafts import file_sha256, load_chunks, validate_one


def main():
    path = ROOT / "data/drafts/specs/토목/9-5-7.json"
    package = json.loads(path.read_text(encoding="utf-8"))
    draft = package["draft"]
    terrain = {"시가지": "1.5", "교외지": "1.3", "농경지": "1.0",
               "구릉지": "0.9", "산악지": "0.85"}
    local_trades = ["고급기술자", "초급기술자", "중급기능사(지도제작)"]
    production_trades = {
        "편집": ["중급기술자", "초급기술자", "중급기능사(지도제작)", "사진제판공"],
        "제도": ["중급기술자", "초급기술자", "중급기능사(지도제작)",
                 "초급기능사(지도제작)", "사진제판공", "사진식자공", "옵셋인쇄공"]
    }
    params = draft["quantity_model"]["params"]
    params["unit_rate_table"] = {
        "table": "p571-t0", "row_input": "work_type", "column_input": None,
        "trades": local_trades, "trade_in_columns": True,
        "table_selector": {"input": "work_type", "values": {
            "현지조사": "p571-t0", "편집": "p571-t2", "제도": "p571-t2"}},
        "row_input_by_table": {"p571-t0": "work_type", "p571-t2": "work_type"},
        "trades_by_table": {"p571-t0": local_trades,
                             "p571-t2": sorted(set(production_trades["편집"] + production_trades["제도"]))},
        "trades_by_row": {"편집": production_trades["편집"], "제도": production_trades["제도"]},
        "trade_in_columns_by_table": {"p571-t0": True, "p571-t2": True}
    }
    params["quantity_input"] = "quantity"
    params["surcharges"] = []
    params["note_adjustments"] = [{
        "when": {"work_type": "현지조사", "terrain": label},
        "rate": rate, "operation": "multiply",
        "rate_table": {"id": "p571-t1", "row": "계수", "column": label},
        "application_cite": {"chunk_id": "p571-x7",
                              "quote": "지형이 다를 때에는 다음 계수를 곱하여 계상한다."},
        "source": "PDF 515쪽 1. 지리조사 [주] ③"
    } for label, rate in terrain.items()]
    draft["quantity_model"]["steps"] = [
        "work_type에 따라 현지조사(p571-t0), 편집 또는 제도(p571-t2) 표를 정확히 선택한다.",
        "현지조사에만 지형별 계수(p571-t1)를 원문에 따라 곱한다. 편집 및 제도는 이 계수를 적용하지 않는다.",
        "선택한 1:25,000 도엽당 직종별 품에 입력 도엽 수를 곱한다.",
        "축척이 1:25,000과 다른 편집·제작은 원문이 참조하는 9-5-6 계수가 필요하므로 계산을 차단한다."
    ]
    package["draft"] = draft
    path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    source_values = {
        "현지조사": {"고급기술자": Fraction("10.22"), "초급기술자": Fraction("9.17"),
                     "중급기능사(지도제작)": Fraction("9.17")},
        "편집": {"중급기술자": Fraction("1.5"), "초급기술자": Fraction("10"),
                 "중급기능사(지도제작)": Fraction("3"), "사진제판공": Fraction("1")},
        "제도": {"중급기술자": Fraction("1.5"), "초급기술자": Fraction("6"),
                 "중급기능사(지도제작)": Fraction("30"), "초급기능사(지도제작)": Fraction("22.5"),
                 "사진제판공": Fraction("5"), "사진식자공": Fraction("1"), "옵셋인쇄공": Fraction("2")}
    }
    cases = []
    for label, factor in terrain.items():
        cases.append(({"work_type": "현지조사", "quantity": "1", "terrain": label,
                       "scale_differs": False}, "현지조사", Fraction(factor)))
    cases.extend([
        ({"work_type": "편집", "quantity": "2", "terrain": "농경지", "scale_differs": False}, "편집", Fraction(1)),
        ({"work_type": "제도", "quantity": "1", "terrain": "산악지", "scale_differs": False}, "제도", Fraction(1))
    ])
    records = []
    for inputs, route, factor in cases:
        result = per_unit(draft, inputs)
        assert result.get("status") == "computed", (inputs, result)
        expected = {name: value * factor for name, value in source_values[route].items()}
        actual = {line["name"]: Fraction(line["exact"]) for line in result["unit_lines"]}
        assert actual == expected, (inputs, actual, expected)
        priced = price_unit(draft, result["unit_lines"], select_rate_version("2026-10-01"),
                            inputs, "2026-10-01")
        assert priced.get("status") in ("COMPLETE", "PARTIAL"), priced
        records.append({"inputs": inputs, "expected": {k: str(v) for k,v in expected.items()},
                        "unit_lines": result["unit_lines"], "offline_price_status": priced["status"]})
    blocked = per_unit(draft, {"work_type": "편집", "quantity": "1", "terrain": "농경지",
                               "scale_differs": True})
    assert blocked.get("status") == "blocked", blocked
    records.append({"inputs": {"work_type": "편집", "quantity": "1", "terrain": "농경지",
                                "scale_differs": True}, "status": blocked["status"]})

    chunks = ROOT / "data/processed/chunks.all.jsonl"
    validation = validate_one(path, ROOT / "data/drafts", load_chunks(chunks), file_sha256(chunks))
    assert validation["ok"], validation
    report_path = ROOT / "data/drafts/report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    rel = path.relative_to(ROOT / "data/drafts").as_posix()
    old = next(x for x in report["results"] if x["path"].replace("\\", "/") == rel)
    report["ok"] += int(validation["ok"]) - int(old["ok"])
    for key in ("with_format_issues", "with_citation_issues"):
        field = key.removeprefix("with_")
        report[key] += int(bool(validation[field])) - int(bool(old[field]))
    report["results"][report["results"].index(old)] = validation
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    index_path = ROOT / "data/drafts/executable.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    ident = draft["id"]
    index["failed"] = [x for x in index["failed"] if x["id"] != ident]
    index["executable"] = sorted(set(index["executable"]) | {ident})
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    audit = {"section": "9-5-7", "physical_pages": [571], "printed_page": 515,
             "source_images": ["tmp/focus-571.png"], "source_cells_checked": 19,
             "scenarios": records,
             "scope": "Visually compared the original local-survey, editing and drafting matrices (3+4+7 rates), all five terrain factors and the 1:25,000 도엽당 denominator. The source explicitly multiplies the terrain factor only for 현지조사. Checked all five terrain routes, editing and drafting rates, offline prices, and blocked the cross-section scale adjustment when scale differs."}
    out = ROOT / "evals/runtime_validation/per-unit-9-5-7-work-route-terrain-audit-2026-10-19.json"
    out.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"section": "9-5-7", "focused_validation_ok": validation["ok"],
                      "source_cells": 19, "cases": len(records)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
