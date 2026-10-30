"""Use the exact day/ton rates in the 13-7-16 source table."""
from __future__ import annotations

import json
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.tools.calc.price import price_unit, select_rate_version
from pipeline.validate_drafts import file_sha256, load_chunks, validate_one

SPEC = ROOT / "data/drafts/specs/기계설비/13-7-16.json"
TRADES = ["플랜트기계설치공", "철골공", "비계공", "특별인부"]


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    draft = package["draft"]
    draft["inputs"] = [item for item in draft["inputs"] if item["name"] != "quantity_unit"]
    draft["inputs"] = [item for item in draft["inputs"] if item["name"] != "quantity_day"]
    draft["inputs"].append({"name": "quantity_day", "type": "positive_rational",
        "allowed_values": "0보다 큰 수", "unit": "일", "required": True,
        "ask": "기술관리 작업일수는 며칠입니까?",
        "source": "PDF 인쇄 830쪽 기술관리 행의 인/일 기준"})
    params = draft["quantity_model"]["params"]
    params["quantity_input"] = "quantity_ton"
    params["unit_rate_table"]["trades"] = TRADES
    params["unit_rate_table"]["basis_by_row"] = {"고정 행이름": "인/ton"}
    params["additional_unit_rates"] = [{"table": "p886-t1", "quantity_input": "quantity_day",
        "trades": ["기계기사"], "row_by_trade": {"기계기사": "기계기사"},
        "column": "수량", "basis_by_trade": {"기계기사": "인/일"}}]
    params["note_adjustments"] = []
    params["input_rate_adjustments"] = [{"name": "검사 및 교정", "operation": "add_source_percent",
        "percent": "10", "kinds": ["labor"], "exclude_trades": ["기계기사"],
        "cite": {"table_id": "p886-t1", "row": "검사및교정", "column": "직종",
                 "value": "기술관리를 제외한 본 품의 10%"}}]
    draft["blocked"] = [{"blocked_if": {"input": "is_underground_10m", "op": "==", "value": False},
        "reason": "원문 표는 지하 10m 설치기준만 제시하며 다른 설치깊이의 요율이 없어 계산을 보류합니다.",
        "source": "PDF 인쇄 830쪽 표 비고", "cite": {"table_id": "p886-t1",
            "row": "플랜트기계설치공", "column": "비고", "value": "지하 10m 설치기준"}}]
    draft["quantity_model"]["steps"] = [
        "기술관리 기계기사는 원문 기준 인/일이므로 quantity_day로 별도 산출한다.",
        "플랜트기계설치공, 철골공, 비계공, 특별인부는 원문 기준 인/ton으로 quantity_ton을 적용한다.",
        "검사 및 교정은 기술관리를 제외한 본 품의 10%를 원문대로 가산한다.",
        "원문 기준인 지하 10m 설치가 아니면 다른 요율이 없어 계산을 보류한다."]
    SPEC.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    cases = []
    for days, ton in ((1, 1), (2.5, 3), (0.5, 0.25)):
        inputs = {"quantity_day": str(days), "quantity_ton": str(ton), "is_underground_10m": True}
        result = per_unit(draft, inputs)
        assert result.get("status") == "computed", result
        by_name = {line["name"]: line for line in result["unit_lines"]}
        assert Fraction(by_name["기계기사"]["exact"]) == Fraction(7, 5)
        assert by_name["기계기사"]["quantity_input"] == "quantity_day"
        for name in TRADES:
            assert Fraction(by_name[name]["exact"]) == Fraction(2846, 1000) * Fraction(11, 10)
        priced = price_unit(draft, result["unit_lines"], select_rate_version("2026-10-01"),
                            inputs, "2026-10-01")
        assert priced.get("status") in ("COMPLETE", "PARTIAL"), priced
        assert priced["reference_amounts"]["volume"] == str(ton)
        cases.append({"inputs": inputs, "lines": result["unit_lines"],
                      "price_status": priced["status"],
                      "reference_amounts": priced["reference_amounts"]})
    out_of_basis = per_unit(draft, {"quantity_day": "1", "quantity_ton": "1",
                                    "is_underground_10m": False})
    assert out_of_basis.get("status") == "blocked" and out_of_basis.get("citations"), out_of_basis

    chunks_path = ROOT / "data/processed/chunks.all.jsonl"
    validation = validate_one(SPEC, ROOT / "data/drafts", load_chunks(chunks_path),
                              file_sha256(chunks_path))
    assert validation["ok"], validation
    report_path = ROOT / "data/drafts/report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    old = next(item for item in report["results"]
               if item["path"].replace("\\", "/") == "specs/기계설비/13-7-16.json")
    report["ok"] += int(validation["ok"]) - int(old["ok"])
    for key in ("with_format_issues", "with_citation_issues"):
        field = key.replace("with_", "")
        report[key] += int(bool(validation[field])) - int(bool(old[field]))
    report["results"][report["results"].index(old)] = validation
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    index_path = ROOT / "data/drafts/executable.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    ident = draft["id"]
    index["failed"] = [item for item in index["failed"] if item["id"] != ident]
    index["executable"] = sorted(set(index["executable"]) | {ident})
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    audit = {"id": ident, "source": {"physical_page": 886, "printed_page": 830,
             "visual_checked": "tmp/13-7-16-source-p886.png", "table": "p886-t1",
             "technical_management": "1.40 인/일", "assembly_each": "2.846 인/ton",
             "inspection_calibration": "10% excluding technical management"},
             "cases": cases, "out_of_basis_case": out_of_basis,
             "focused_validation_ok": validation["ok"],
             "scope": "The table's exact day and ton rates, separate quantity scaling, the 10% exclusion and source-depth block were verified with offline price routes; no inventory-wide rule completion claimed."}
    out = ROOT / "evals/runtime_validation/per-unit-13-7-16-heterogeneous-unit-audit-2026-10-19.json"
    out.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"id": ident, "focused_validation_ok": validation["ok"],
                      "cases": len(cases), "out_of_basis": out_of_basis["status"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
