"""Connect 8-2-6's explicitly per-attempt labor and single-cone quantities."""
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
    path = ROOT / "data/drafts/specs/토목/8-2-6.json"
    package = json.loads(path.read_text(encoding="utf-8"))
    draft = package["draft"]
    table = next(t for t in draft["tables"] if t["id"] == "p456-t1")
    table["unit"] = "인, 개/회"
    params = draft["quantity_model"]["params"]
    params["unit_rate_table"] = {
        "table": "p456-t1", "row_input": None, "column_input": None,
        "trades": ["중급기술자", "초급기술자", "보통인부"],
        "basis_cites_by_row": {trade: {"table_id": "p456-t1", "row": trade,
                                      "column": "단위", "value": "인"}
                               for trade in ("중급기술자", "초급기술자", "보통인부")}
    }
    params["quantity_input"] = "quantity"
    params["surcharges"] = []
    params["note_adjustments"] = []
    params["additional_materials"] = [{
        "table": "p456-t1", "row": "단독콘", "column": "수량",
        "name": "단독콘", "unit": "개", "quantity_input": "quantity", "basis": "1/회",
        "source": "원문 p.400 표 (회당), 단독콘 행",
        "cite": {"table_id": "p456-t1", "row": "단독콘", "column": "수량", "value": "72.0"}
    }]
    draft["quantity_model"]["steps"] = [
        "원문 표의 (회당) 기준으로 중급기술자, 초급기술자, 보통인부의 수량을 조회한다.",
        "단독콘 행의 개수도 같은 표의 회당 수량으로 산출한다.",
        "주변파일 반력 이용 방식만 적용한다. 실하중 또는 Anchor 반력 방식은 별도 계상 문구에 따라 자동 계산을 차단한다.",
        "회당 인력 및 단독콘 수량에 시험 횟수를 반영한다."
    ]
    package["draft"] = draft
    path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    scenarios = [
        ({"quantity": "1", "loading_method": "주변파일 반력 이용"}, Fraction(1)),
        ({"quantity": "3", "loading_method": "주변파일 반력 이용"}, Fraction(3))
    ]
    expected_rates = {"중급기술자": Fraction("4.20"), "초급기술자": Fraction("4.41"),
                      "보통인부": Fraction("4.10"), "단독콘": Fraction("72.0")}
    records = []
    for inputs, count in scenarios:
        result = per_unit(draft, inputs)
        assert result.get("status") == "computed", (inputs, result)
        by_name = {line["name"]: Fraction(line["exact"]) for line in result["unit_lines"]}
        assert by_name == expected_rates, (inputs, by_name)
        priced = price_unit(draft, result["unit_lines"], select_rate_version("2026-10-01"),
                            inputs, "2026-10-01")
        assert priced.get("status") in ("COMPLETE", "PARTIAL"), priced
        records.append({"inputs": inputs, "per_attempt_expected": {k: str(v) for k,v in expected_rates.items()},
                        "unit_lines": result["unit_lines"],
                        "independent_expected_total": {k: str(v * int(inputs["quantity"])) for k,v in expected_rates.items()},
                        "offline_price_status": priced["status"]})
    unsupported_method = per_unit(draft, {"quantity": "1", "loading_method": "실하중 재하"})
    assert unsupported_method.get("status") == "blocked", unsupported_method
    records.append({"inputs": {"quantity": "1", "loading_method": "실하중 재하"},
                    "status": unsupported_method["status"], "reason": unsupported_method.get("reason")})

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
    audit = {
        "section": "8-2-6", "physical_pages": [456], "printed_page": 400,
        "source_images": ["tmp/focus-456.png"], "source_cells_checked": 4,
        "scenarios": records,
        "scope": "Visually compared the original (회당) heading, three labor cells, the separate unit '개' for 단독콘, its 72.0 rate, and the method limitation. Independently checked exact per-attempt output at counts 1 and 3, offline price routing, and the source-backed block for other loading methods."
    }
    out = ROOT / "evals/runtime_validation/per-unit-8-2-6-per-attempt-audit-2026-10-19.json"
    out.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"section": "8-2-6", "focused_validation_ok": validation["ok"],
                      "source_cells": 4, "cases": len(records)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
