"""Route day, area and ton bases from the adjacent 13-7-17/18 source tables."""
from __future__ import annotations

import glob
import json
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.tools.calc.price import price_unit, select_rate_version
from pipeline.validate_drafts import file_sha256, load_chunks, validate_one

TECH_CITE = {"table_id": "p887-t0", "row": "검사및교정", "column": "직종",
             "value": "기술관리를 제외한 본 품의 10%"}
RATE_ADJUSTMENT = {"name": "검사 및 교정", "operation": "add_source_percent",
                   "percent": "10", "kinds": ["labor"], "exclude_trades": ["기계기사"],
                   "cite": TECH_CITE}


def read_spec(section: str) -> tuple[Path, dict]:
    path = Path(glob.glob(str(ROOT / f"data/drafts/specs/기계설비/{section}.json"))[0])
    package = json.loads(path.read_text(encoding="utf-8"))
    return path, package


def validate_and_promote(path: Path, package: dict) -> dict:
    chunks_path = ROOT / "data/processed/chunks.all.jsonl"
    result = validate_one(path, ROOT / "data/drafts", load_chunks(chunks_path),
                          file_sha256(chunks_path))
    assert result["ok"], result
    report_path = ROOT / "data/drafts/report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    old = next(item for item in report["results"]
               if item["path"].replace("\\", "/") == path.relative_to(ROOT / "data/drafts").as_posix())
    report["ok"] += int(result["ok"]) - int(old["ok"])
    for key in ("with_format_issues", "with_citation_issues"):
        field = key.replace("with_", "")
        report[key] += int(bool(result[field])) - int(bool(old[field]))
    report["results"][report["results"].index(old)] = result
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    index_path = ROOT / "data/drafts/executable.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    ident = package["draft"]["id"]
    index["failed"] = [item for item in index["failed"] if item["id"] != ident]
    index["executable"] = sorted(set(index["executable"]) | {ident})
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def assert_price(draft: dict, result: dict, inputs: dict, total: str) -> dict:
    priced = price_unit(draft, result["unit_lines"], select_rate_version("2026-10-01"),
                        inputs, "2026-10-01")
    assert priced.get("status") in ("COMPLETE", "PARTIAL"), priced
    assert priced["reference_amounts"]["volume"] == total, priced
    return priced


def main() -> int:
    path17, pkg17 = read_spec("13-7-17")
    d17 = pkg17["draft"]
    inputs17 = d17["inputs"]
    day_field = next(item for item in inputs17
                     if item["name"] in ("quantity_unit", "quantity_day"))
    day_field.update({"name": "quantity_day", "unit": "일",
                      "ask": "기술관리 작업일수는 며칠입니까?",
                      "source": "PDF 인쇄 831쪽 표 기술관리 행 단위 인/일"})
    p17 = d17["quantity_model"]["params"]
    p17["unit_rate_table"]["trades"] = ["플랜트기계설치공", "철골공", "비계공", "특별인부"]
    p17["additional_unit_rates"] = [{"table": "p887-t0", "quantity_input": "quantity_day",
        "trades": ["기계기사"], "row_by_trade": {"기계기사": "기계기사"},
        "column": "수량", "basis_by_trade": {"기계기사": "인/일"}}]
    p17["note_adjustments"] = []
    p17["input_rate_adjustments"] = [dict(RATE_ADJUSTMENT)]
    d17["inputs"] = [item for item in d17["inputs"] if item["name"] != "within_source_depth"]
    d17["inputs"].append({"name": "within_source_depth", "type": "boolean",
        "allowed_values": [True, False], "unit": None, "required": True,
        "ask": "설치깊이가 원문 기준인 지하 5m입니까?",
        "source": "PDF 인쇄 831쪽 표 비고, 지하 5m 설치기준"})
    d17["blocked"] = [{"blocked_if": {"input": "within_source_depth", "op": "==", "value": False},
        "reason": "원문 표는 지하 5m 설치기준만 제시하며 다른 설치깊이의 요율이 없어 계산을 보류합니다.",
        "source": "PDF 인쇄 831쪽 표 비고", "cite": {"table_id": "p887-t0",
            "row": "기계기사", "column": "비고", "value": "지하 5m 설치기준"}}]
    d17["quantity_model"]["steps"] = [
        "기술관리 기계기사는 원문 기준 인/일이므로 quantity_day로 별도 산출한다.",
        "조립설치 네 직종은 원문 기준 인/ton이므로 quantity_weight로 산출한다.",
        "검사 및 교정은 기술관리를 제외한 본 품의 10%를 원문대로 가산한다."]
    SPEC17 = path17
    SPEC17.write_text(json.dumps(pkg17, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    audit17 = []
    for day, ton in ((1, 1), (3, 2), (0.5, 0.25)):
        inp = {"quantity_day": str(day), "quantity_weight": str(ton), "within_source_depth": True}
        result = per_unit(d17, inp)
        assert result.get("status") == "computed", result
        by_name = {line["name"]: line for line in result["unit_lines"]}
        assert Fraction(by_name["기계기사"]["exact"]) == Fraction(7, 10)
        assert by_name["기계기사"]["quantity_input"] == "quantity_day"
        for name in ("플랜트기계설치공", "철골공", "비계공", "특별인부"):
            assert Fraction(by_name[name]["exact"]) == Fraction(2587, 1000) * Fraction(11, 10)
        priced = assert_price(d17, result, inp, str(ton))
        audit17.append({"inputs": inp, "lines": result["unit_lines"],
                        "price_status": priced["status"], "reference_amounts": priced["reference_amounts"]})
    blocked17 = per_unit(d17, {"quantity_day": "1", "quantity_weight": "1",
                               "within_source_depth": False})
    assert blocked17.get("status") == "blocked" and blocked17.get("citations"), blocked17
    val17 = validate_and_promote(path17, pkg17)

    path18, pkg18 = read_spec("13-7-18")
    d18 = pkg18["draft"]
    p18 = d18["quantity_model"]["params"]
    p18["unit_rate_table"]["trades"] = ["플랜트기계설치공", "비계공", "플랜트용접공"]
    p18["additional_unit_rates"] = [
        {"table": "p887-t1", "quantity_input": "quantity_day", "trades": ["기계기사"],
         "row_by_trade": {"기계기사": "기계기사"}, "column": "인/일",
         "basis_by_trade": {"기계기사": "인/일"}},
        {"table": "p887-t1", "quantity_input": "quantity_sqm", "trades": ["특별인부"],
         "row_by_trade": {"특별인부": "특별인부"}, "column": "인/㎡",
         "basis_by_trade": {"특별인부": "인/㎡"}},
        {"table": "p887-t1", "quantity_input": "quantity_ton", "trades": ["특별인부"],
         "row_by_trade": {"특별인부": "특별인부"}, "column": "〃",
         "basis_by_trade": {"특별인부": "인/ton"}},
    ]
    d18["inputs"] = [item for item in d18["inputs"] if item["name"] != "apply_inspection"]
    p18["note_adjustments"] = []
    p18["input_rate_adjustments"] = [dict(RATE_ADJUSTMENT, cite={
        "table_id": "p887-t1", "row": "검사및교정", "column": "직종",
        "value": "기술관리를 제외한 본 품의 10%"})]
    d18["quantity_model"]["steps"] = [
        "기술관리 기계기사는 인/일, 표면손질 특별인부는 인/㎡, 조립설치는 인/ton 기준을 각각 사용한다.",
        "표에서 직종과 기준 단위가 일치하는 원문 수량을 선택하고 해당 작업 물량을 곱한다.",
        "검사 및 교정은 기술관리를 제외한 본 품의 10%를 원문대로 가산한다."]
    path18.write_text(json.dumps(pkg18, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    audit18 = []
    for day, sqm, ton in ((1, 1, 1), (2, 12, 3), (0.5, 2.5, 0.25)):
        inp = {"quantity_day": str(day), "quantity_sqm": str(sqm), "quantity_ton": str(ton)}
        result = per_unit(d18, inp)
        assert result.get("status") == "computed", result
        by_name_input = {(line["name"], line.get("quantity_input")): line for line in result["unit_lines"]}
        assert Fraction(by_name_input[("기계기사", "quantity_day")]["exact"]) == Fraction(7, 10)
        assert Fraction(by_name_input[("특별인부", "quantity_sqm")]["exact"]) == Fraction(1, 10) * Fraction(11, 10)
        assert Fraction(by_name_input[("특별인부", "quantity_ton")]["exact"]) == Fraction(1803, 1000) * Fraction(11, 10)
        for name, rate in (("플랜트기계설치공", "3.245"), ("비계공", "1.622"), ("플랜트용접공", "0.541")):
            assert Fraction(by_name_input[(name, None)]["exact"]) == Fraction(rate) * Fraction(11, 10)
        priced = assert_price(d18, result, inp, str(ton))
        audit18.append({"inputs": inp, "lines": result["unit_lines"],
                        "price_status": priced["status"], "reference_amounts": priced["reference_amounts"]})
    val18 = validate_and_promote(path18, pkg18)

    out = ROOT / "evals/runtime_validation/per-unit-13-7-17-18-heterogeneous-unit-audit-2026-10-19.json"
    out.write_text(json.dumps({"sections": {
        "13-7-17": {"source": "PDF physical p.887 / printed p.831", "visual_checked": "tmp/13-7-17-source-p887.png",
                     "verified_rates": {"technical_management_in_per_day": "0.70", "assembly_in_per_ton": "2.587",
                                        "inspection_calibration": "10% excluding technical management"},
                     "cases": audit17, "out_of_basis_case": blocked17,
                     "focused_validation_ok": val17["ok"]},
        "13-7-18": {"source": "PDF physical p.887 / printed p.831", "visual_checked": "tmp/13-7-17-source-p887.png",
                     "verified_rates": {"technical_management_in_per_day": "0.70", "surface_prep_in_per_sqm": "0.10",
                                        "assembly_special_labor_in_per_ton": "1.803",
                                        "inspection_calibration": "10% excluding technical management"},
                     "cases": audit18, "focused_validation_ok": val18["ok"]}},
        "scope": "Both exact original tables and all declared independent day/sqm/ton quantities were checked with three combinations each and offline pricing; no inventory-wide rule completion is claimed."},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"13-7-17": val17["ok"], "13-7-18": val18["ok"],
                      "source_tables": 2, "heterogeneous_quantity_cases": len(audit17)+len(audit18)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
