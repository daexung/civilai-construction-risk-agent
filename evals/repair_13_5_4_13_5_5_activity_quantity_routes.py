"""Connect exact task rows to their distinct quantity inputs in 13-5-4/5."""
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

INSPECTION = {"name": "검사 및 교정", "operation": "add_source_percent", "percent": "10",
              "kinds": ["labor"], "exclude_quantity_inputs": ["duration", "wood_volume"]}


def load_spec(section: str) -> tuple[Path, dict]:
    path = Path(glob.glob(str(ROOT / f"data/drafts/specs/기계설비/{section}.json"))[0])
    return path, json.loads(path.read_text(encoding="utf-8"))


def activity(table: str, row: str, quantity_input: str, basis: str,
             trades: list[str], *, basis_by_trade: dict | None = None,
             resource_units: dict | None = None) -> dict:
    return {"table": table, "quantity_input": quantity_input, "trades": trades,
            "row_by_trade": {trade: row for trade in trades},
            "column_by_trade": {trade: trade for trade in trades},
            "basis_by_trade": basis_by_trade or {trade: basis for trade in trades},
            "resource_units": resource_units or {}}


def promote(path: Path, package: dict) -> dict:
    chunks = ROOT / "data/processed/chunks.all.jsonl"
    validation = validate_one(path, ROOT / "data/drafts", load_chunks(chunks), file_sha256(chunks))
    assert validation["ok"], validation
    report_path = ROOT / "data/drafts/report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    rel = path.relative_to(ROOT / "data/drafts").as_posix()
    old = next(item for item in report["results"] if item["path"].replace("\\", "/") == rel)
    report["ok"] += int(validation["ok"]) - int(old["ok"])
    for key in ("with_format_issues", "with_citation_issues"):
        field = key.replace("with_", "")
        report[key] += int(bool(validation[field])) - int(bool(old[field]))
    report["results"][report["results"].index(old)] = validation
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    index_path = ROOT / "data/drafts/executable.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    ident = package["draft"]["id"]
    index["failed"] = [item for item in index["failed"] if item["id"] != ident]
    index["executable"] = sorted(set(index["executable"]) | {ident})
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return validation


def calc_and_price(draft: dict, inputs: dict) -> tuple[dict, dict]:
    result = per_unit(draft, inputs)
    assert result.get("status") == "computed", result
    priced = price_unit(draft, result["unit_lines"], select_rate_version("2026-10-01"),
                        inputs, "2026-10-01")
    assert priced.get("status") in ("COMPLETE", "PARTIAL"), priced
    return result, priced


def main() -> int:
    audits = {}
    # Duct work: all rates are selected by exact source row/resource and a distinct measured quantity.
    path, package = load_spec("13-5-4")
    draft = package["draft"]
    params = draft["quantity_model"]["params"]
    main_row = "기술관리 공사기간중"
    params["unit_rate_table"] = {"table": "p831-t0", "row_input": main_row,
        "column_input": None, "trades": ["기계산업기사"],
        "basis_by_row": {main_row: "인/일"}}
    params["quantity_input"] = "duration"
    params["additional_unit_rates"] = [
        activity("p831-t0", "표면손질", "surface_area", "인/㎡", ["특별인부"]),
        activity("p831-t0", "포장해체 수송을 위한 포장된 목재를 해체하고 해체된 목재를 소정의 위치에 정돈함",
                 "wood_volume", "인/㎥", ["목공", "특별인부"]),
        activity("p831-t0", "현장교정", "duct_weight", "인/ton", ["제관공"]),
        activity("p831-t0", "수송도중 변형된 것을 바로 잡기", "duct_weight", "인/ton", ["특별인부"]),
        activity("p831-t0", "DUCT 조립 조각으로 분리된 DUCT의 소재를 성형 용접함", "duct_weight", "인/ton",
                 ["플랜트제관공", "플랜트용접공", "특별인부", "건설기계운전조"],
                 basis_by_trade={"플랜트제관공": "인/ton", "플랜트용접공": "인/ton",
                                 "특별인부": "인/ton", "건설기계운전조": "조/ton"},
                 resource_units={"건설기계운전조": "조"}),
        activity("p831-t0", "DUCT 설치 성형된 duct를 운반조양 alignment후 bolting 및 hangering",
                 "duct_weight", "인/ton", ["일반기계운전사", "(윈치운전)", "비계공", "특별인부",
                                           "플랜트용접공", "플랜트제관공"]),
    ]
    params["note_adjustments"] = []
    params["input_rate_adjustments"] = [dict(INSPECTION, cite={"table_id": "p831-t0",
        "row": "검사 및 교정 외관검사 및 Leak test", "column": "직종",
        "value": "기술관리, 포장해체를 제외한 모든 품의 10%",
        "exclude_trades": ["기계산업기사"]})]
    draft["quantity_model"]["steps"] = [
        "기술관리는 인/일, 표면손질은 인/㎡, 포장해체는 인/㎥, 현장교정과 덕트 조립·설치는 인/ton(해당 원문 행의 조/ton 포함) 기준으로 따로 산출한다.",
        "각 원문 작업 행의 직종별 품을 대응하는 현장 물량에 곱한다.",
        "검사 및 교정은 기술관리와 포장해체를 제외한 모든 품의 10%로 더한다.",
        "사용장비는 원문 참고표의 대수로 별도 확인한다."]
    package["draft"] = draft
    path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    routes_54 = []
    for day, area, volume, ton in ((2, 100, 10, 3), (1, 20, 1, 0.5), (0.5, 5, 5, 1)):
        inp = {"duration": str(day), "surface_area": str(area), "wood_volume": str(volume),
               "duct_weight": str(ton)}
        result, priced = calc_and_price(draft, inp)
        lines = result["unit_lines"]
        assert any(line["name"] == "기계산업기사" and line.get("quantity_input") is None for line in lines)
        assert any(line["name"] == "목공" and line.get("quantity_input") == "wood_volume" for line in lines)
        assert any(line["name"] == "특별인부" and line.get("quantity_input") == "surface_area" for line in lines)
        assert all("기술관리" not in str(line.get("adjustments", [])) for line in lines
                   if line["name"] == "기계산업기사")
        routes_54.append({"inputs": inp, "unit_lines": lines, "price_status": priced["status"],
                          "reference_amounts": priced["reference_amounts"]})
    val54 = promote(path, package)
    audits["13-5-4"] = {"physical_page": 831, "printed_page": 775,
        "visual_checked": "tmp/p831-duct-airstack-source.png", "table": "p831-t0",
        "source_activity_rows": 8, "numeric_source_cells": 17,
        "distinct_quantity_routes": 4,
        "cases": routes_54, "focused_validation_ok": val54["ok"]}

    # Air preheater: the table continues across p831/p832 and has seven source quantity axes.
    path, package = load_spec("13-5-5")
    draft = package["draft"]
    params = draft["quantity_model"]["params"]
    main_row = "기술관리 공사기간중"
    params["unit_rate_table"] = {"table": "p831-t2", "row_input": main_row,
        "column_input": None, "trades": ["기계산업기사"], "basis_by_row": {main_row: "인/일"}}
    params["quantity_input"] = "duration"
    params["additional_unit_rates"] = [
        activity("p831-t2", "포장해체 수송을 위해 포장된 목재를 해체하고 정위치에 정리",
                 "volume_wood", "인/㎥", ["목공", "특별인부"]),
        activity("p831-t2", "소운반 및 조양", "weight_transport", "인/ton", ["건설기계운전조"]),
        activity("p831-t2", "적재장에서부터 설치장소까지 운반,", "weight_transport", "인/ton", ["비계공"]),
        activity("p831-t2", "조양함", "weight_transport", "인/ton", ["특별인부"]),
        activity("p832-t0", "표면손질", "area_surface", "인/㎡", ["특별인부"]),
        activity("p832-t0", "casing 조립 설치 Support Structure, Rotor inner casing, Outer Casing 등 Heating Element를 제외한 모든 부분의 조립설치",
                 "weight_casing", "인/ton", ["플랜트기계설치공", "플랜트용접공", "플랜트제관공",
                    "특별인부", "비계공", "Crane운전조"],
                 basis_by_trade={"플랜트기계설치공": "인/ton", "플랜트용접공": "인/ton",
                                 "플랜트제관공": "인/ton", "특별인부": "인/ton",
                                 "비계공": "인/ton", "Crane운전조": "조/ton"},
                 resource_units={"Crane운전조": "조"}),
        activity("p832-t0", "Heating Element 삽입 Hot busket, Interbusker, Cold busket의 삽입",
                 "weight_heating_element", "인/ton", ["플랜트기계설치공", "특별인부"]),
        activity("p832-t0", "Sealing Plate 및 Packing ring", "weight_sealing", "인/ton",
                 ["플랜트기계설치공"]),
        activity("p832-t0", "조립 설치", "weight_sealing", "인/ton", ["특별인부"]),
    ]
    params["note_adjustments"] = []
    params["input_rate_adjustments"] = [dict(INSPECTION, cite={"table_id": "p832-t0",
        "row": "검사 및 교정", "column": "기술관리, 포장해체를 제외한 모든 품의 10%", "value": "",
        "exclude_trades": ["기계산업기사"]})]
    draft["quantity_model"]["steps"] = [
        "기술관리는 인/일, 포장해체는 인/㎥, 표면손질은 인/㎡, 운반·설치 공정은 원문에 표기된 ton 기준으로 각각 산출한다.",
        "각 공정의 직종별 품을 해당하는 물량 입력에 곱하고, 동 단위 조립운전조는 조/ton으로 보존한다.",
        "검사 및 교정은 기술관리와 포장해체를 제외한 모든 품의 10%로 더한다.",
        "참고 사용장비 표는 장비 규격과 대수를 보여 주며, 장비 사용시간·단가 자료가 필요한 가격 합계와 분리한다."]
    package["draft"] = draft
    path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    routes_55 = []
    for vals in ((1, 5, 2, 3, 4, 2, 1), (2, 2, 1, 1, 1, 3, 2),
                 (0.5, 2, 1, 0.5, 1.5, 0.25, 0.75)):
        day, volume, transport, area, casing, element, sealing = vals
        inp = {"duration": str(day), "volume_wood": str(volume), "weight_transport": str(transport),
               "area_surface": str(area), "weight_casing": str(casing),
               "weight_heating_element": str(element), "weight_sealing": str(sealing)}
        result, priced = calc_and_price(draft, inp)
        assert any(line["name"] == "기계산업기사" for line in result["unit_lines"])
        assert any(line["name"] == "목공" and line.get("quantity_input") == "volume_wood"
                   for line in result["unit_lines"])
        assert any(line["name"] == "특별인부" and line.get("quantity_input") == "area_surface"
                   for line in result["unit_lines"])
        assert any(line.get("quantity_input") == "weight_heating_element" for line in result["unit_lines"])
        routes_55.append({"inputs": inp, "unit_lines": result["unit_lines"],
                          "price_status": priced["status"], "reference_amounts": priced["reference_amounts"]})
    val55 = promote(path, package)
    audits["13-5-5"] = {"physical_pages": [831, 832], "printed_pages": [775, 776],
        "visual_checked": ["tmp/p831-duct-airstack-source.png", "tmp/p832-duct-airstack-source.png"],
        "tables": ["p831-t2", "p832-t0"], "source_activity_rows": 10,
        "numeric_source_cells": 18,
        "distinct_quantity_routes": 7, "cases": routes_55, "focused_validation_ok": val55["ok"]}
    audit = {"sections": audits,
        "scope": "Physical source tables and every declared task quantity axis were checked through exact row/column citations, three mixed-quantity combinations per section, and offline price calculation. Mechanical equipment reference tables remain separate because they provide equipment counts but no use-duration basis. Whole-rule inventory completion is not claimed."}
    out = ROOT / "evals/runtime_validation/per-unit-13-5-4-13-5-5-activity-quantity-audit-2026-10-19.json"
    out.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"13-5-4": val54["ok"], "13-5-5": val55["ok"],
                      "source_sections": 2, "mixed_quantity_cases": len(routes_54)+len(routes_55)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
