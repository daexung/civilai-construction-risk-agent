"""Route the source-defined process quantities in 13-8-4/6/7."""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.tools.calc.price import price_unit, select_rate_version
from pipeline.validate_drafts import file_sha256, load_chunks, validate_one


def load_spec(section: str):
    path = Path(glob.glob(str(ROOT / f"data/drafts/specs/기계설비/{section}.json"))[0])
    return path, json.loads(path.read_text(encoding="utf-8"))


def activity(table: str, row: str, quantity: str, basis: str, trades: list[str], *, crews=()):
    basis_by_trade = {trade: ("조/ton" if trade in crews else basis) for trade in trades}
    return {"table": table, "quantity_input": quantity, "trades": trades,
            "row_by_trade": {trade: row for trade in trades},
            "column_by_trade": {trade: trade for trade in trades},
            "basis_by_trade": basis_by_trade,
            "resource_units": {trade: "조" for trade in crews}}


def promote(path: Path, package: dict):
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
    ident = package["draft"]["id"]
    index["failed"] = [x for x in index["failed"] if x["id"] != ident]
    index["executable"] = sorted(set(index["executable"]) | {ident})
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return validation


def run(draft, inputs):
    result = per_unit(draft, inputs)
    assert result.get("status") == "computed", result
    priced = price_unit(draft, result["unit_lines"], select_rate_version("2026-10-01"), inputs, "2026-10-01")
    assert priced.get("status") in ("COMPLETE", "PARTIAL"), priced
    return result, priced


def configure(section: str, main_table: str, main_row: str, tech_trade: str,
              tech_input: str, packaging_input: str, routes: list[dict], checks: list[dict],
              page: int, inspection: tuple[str, str, str, str]):
    path, package = load_spec(section)
    draft = package["draft"]
    params = draft["quantity_model"]["params"]
    params["unit_rate_table"] = {"table": main_table, "row_input": main_row,
        "column_input": None, "trades": [tech_trade], "basis_by_row": {main_row: "인/일"}}
    params["quantity_input"] = tech_input
    params["additional_unit_rates"] = routes
    inspection_table, inspection_row, inspection_column, inspection_value = inspection
    table = next(t for t in draft["tables"] if t["id"] == inspection_table)
    table["values"].setdefault(inspection_row, {})[inspection_column] = inspection_value
    params["input_rate_adjustments"] = [{
        "name": "검사 및 교정", "operation": "add_source_percent", "percent": "10",
        "kinds": ["labor"], "exclude_quantity_inputs": [tech_input, packaging_input],
        "exclude_trades": ["건설기계운전조"],
        "cite": {"table_id": inspection_table, "row": inspection_row,
                 "column": inspection_column, "value": inspection_value}}]
    params.pop("input_rate_adjustments", None)
    params["note_adjustments"] = []
    draft["quantity_model"]["steps"] = [
        "기술관리(인/일), 포장해체(인/㎥), 표면손질(인/㎡), ton 또는 휠터수 기준 공정을 원문 행별 입력 물량으로 따로 계산한다.",
        "각 공정·직종의 원문 단위당 품에 해당 물량을 곱한다. 건설기계운전조는 원문 조/ton 단위를 보존한다.",
        "검사 및 교정은 기술관리·포장해체를 제외한 인부 품에 10%를 적용한다. 별도 운전조의 포함 여부가 원문에서 분명하지 않아 운전조에는 추가율을 적용하지 않으며 미확정 정책으로 남긴다.",
        "사용장비 표는 장비 대수·규격만 제공하며 작업시간과 투입단가가 없어 노무 계산과 분리한다."]
    open_q = draft.setdefault("open_questions", [])
    q = "검사 및 교정의 '전공량 10%' 기준에 별도 단위 조/ton의 건설기계운전조가 포함되는지 원문만으로 미확정."
    if q not in open_q:
        open_q.append(q)
    package["draft"] = draft
    path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    cases = []
    for sample in checks:
        result, priced = run(draft, sample)
        for route in routes:
            assert any(line.get("quantity_input") == route["quantity_input"] and
                       line["name"] in route["trades"]
                       for line in result["unit_lines"]), (section, route, result["unit_lines"])
        cases.append({"inputs": sample, "unit_lines": result["unit_lines"],
                      "price_status": priced["status"], "reference_amounts": priced["reference_amounts"]})
    validation = promote(path, package)
    return {"physical_page": page, "source_image": f"tmp/p{page}-process-unit-source.png",
            "table_ids": sorted({r["table"] for r in routes} | {main_table}),
            "numeric_source_cells": sum(len(r["trades"]) for r in routes) + 1,
            "quantity_routes": len(routes) + 1, "cases": cases,
            "inspection_10_percent": "recorded but not automated pending operator-crew scope resolution",
            "focused_validation_ok": validation["ok"]}


def main():
    results = {}
    results["13-8-4"] = configure("13-8-4", "p894-t1", "◦ 기술관리 - 설치공사 기간중", "기계기사",
        "duration_tech_mgmt", "volume_unpacking", [
            activity("p894-t1", "◦ 포장해체 - 수송을 위해 포장된 목재를 해체하고 목재를 정리함", "volume_unpacking", "인/㎥", ["목공", "특별인부"]),
            activity("p894-t1", "◦ 표면손질", "area_surface_prep", "인/㎡", ["특별인부"]),
            activity("p894-t1", "◦ 현장교정 - 수송도중 변형된 것을 바로잡기", "weight_field_correction", "인/ton", ["플랜트제관공", "특별인부"]),
            activity("p894-t1", "◦ 기초작업 - Chipping 및 Grouting", "weight_foundation", "인/ton", ["플랜트기계설치공", "특별인부"]),
            activity("p894-t1", "◦ 소운반", "weight_transport", "인/ton", ["특별인부"]),
            activity("p894-t1", "- 작업 위치까지 필요한 자재를 운반", "weight_transport", "인/ton", ["건설기계운전조"], crews=("건설기계운전조",)),
            activity("p894-t1", "◦ 본체조립 - 분리 운반된 Body 조립 포함", "weight_body_assembly", "인/ton", ["플랜트제관공", "플랜트용접공", "특별인부", "건설기계운전조"], crews=("건설기계운전조",)),
            activity("p895-t0", "◦ Inner Plate 및 Hanger 조립 - Suspention Device 조립 포함", "weight_inner_plate", "인/ton", ["플랜트제관공", "플랜트용접공", "특별인부"]),
            activity("p895-t0", "◦ 본체 설치 - 반응물 배출장치(Lump Crusher) 및 Rotary Valve 설치 포함 ※ 소석회 분무장치 제외", "weight_body_install", "인/ton", ["플랜트기계설치공", "플랜트제관공", "플랜트용접공", "특별인부", "비계공", "건설기계운전조"], crews=("건설기계운전조",)),
        ], [dict(duration_tech_mgmt="2", volume_unpacking="1", area_surface_prep="25", weight_field_correction="3", weight_foundation="2", weight_transport="4", weight_body_assembly="8", weight_inner_plate="3", weight_body_install="6"),
            dict(duration_tech_mgmt="1", volume_unpacking="0.5", area_surface_prep="10", weight_field_correction="1", weight_foundation="1", weight_transport="1.5", weight_body_assembly="2", weight_inner_plate="1", weight_body_install="2")], 894,
        ("p895-t0", "◦ 검사 및 교정 - Gas Leak Test 포함", "직종", "기술관리, 포장해체를 제외한 전공량의 10%"))
    results["13-8-6"] = configure("13-8-6", "p897-t0", "◦ 기술관리 - 설치공사 기간중", "기계기사",
        "duration_installation", "volume_packaging", [
            activity("p897-t0", "◦ 포장해체", "volume_packaging", "인/㎥", ["목공", "특별인부"]),
            activity("p897-t0", "◦ 기초작업 및 표면손질 - Chipping 및 Grouting 등", "weight_foundation", "인/ton", ["플랜트 기계 설치 공", "특별인부"]),
            activity("p897-t0", "◦ 본체조립･설치 - Frame, Shell Plate 등 설치포함 - 펄스유닛 조립･설치", "weight_main_body", "인/ton", ["철골공", "비계공", "플랜트 기계 설치 공", "플랜트용접공", "특별인부", "건설기계운전조"], crews=("건설기계운전조",)),
            activity("p897-t0", "◦ 비산재 배출장치 조립･장치 - 비산재 사일로, 시멘트 사일로 설치 포함", "weight_ash_discharge", "인/ton", ["플랜트 기계 설치 공", "비계공", "플랜트용접공", "특별인부"]),
            activity("p897-t0", "◦ 휠터백 및 백케이지 조립･설치 - 지상교정, 조양･기기 설치포함 - Leveling 재교정후 Setting 포함", "count_filter_bag", "인/휠터수", ["플랜트제관공", "비계공", "특별인부", "플랜트용접공"]),
        ], [dict(duration_installation="2", volume_packaging="1", weight_foundation="3", weight_main_body="10", weight_ash_discharge="2", count_filter_bag="120"),
            dict(duration_installation="1", volume_packaging="0.5", weight_foundation="1", weight_main_body="2", weight_ash_discharge="1", count_filter_bag="30")], 897,
        ("p897-t0", "◦ 검사 및 교정 - Gas Leak Test 포함", "직종", "기술관리, 포장해체를 제외한 공량의 10%"))
    results["13-8-7"] = configure("13-8-7", "p898-t0", "◦기술관리 - 설치공사 기간중", "기계기사",
        "duration", "volume_package", [
            activity("p898-t0", "◦포장해체 - 수송을 위해 포장된 목재를 해체하고 목재를 정리함", "volume_package", "인/㎥", ["목공", "특별인부"]),
            activity("p898-t0", "◦기초작업 및 표면손질 - Chipping 및 Grouting 등", "weight_foundation", "인/ton", ["플랜트기계설치공", "특별인부"]),
            activity("p898-t0", "◦반응조제 및 탱크류 조립･설치", "weight_reaction", "인/ton", ["플랜트제관공", "플랜트용접공", "플랜트기계설치공", "비계공", "특별인부", "건설기계운전조"], crews=("건설기계운전조",)),
            activity("p898-t0", "◦소석회, 활성탄 공급설비 조립･설치", "weight_lime", "인/ton", ["플랜트기계설치공", "비계공", "플랜트용접공", "특별인부", "건설기계운전조"], crews=("건설기계운전조",)),
            activity("p898-t0", "◦혼합기, 이젝터, 로타리밸브 설치", "weight_mixer", "인/ton", ["플랜트기계설치공", "비계공", "플랜트용접공", "특별인부"]),
        ], [dict(duration="2", volume_package="1", weight_foundation="3", weight_reaction="8", weight_lime="4", weight_mixer="2"),
            dict(duration="1", volume_package="0.5", weight_foundation="1", weight_reaction="2", weight_lime="1", weight_mixer="1")], 898,
        ("p898-t0", "◦검사 및 교정 - Gas Leak Test 포함", "기술관리, 포장해체를 제외한 공량의 10%", "10%"))

    out = ROOT / "evals/runtime_validation/per-unit-13-8-4-6-7-process-quantity-audit-2026-10-19.json"
    out.write_text(json.dumps({"sections": results, "scope": "Original PDF pages 894, 895, 897 and 898 visually checked. Distinct day, volume, area, ton, crew-ton and filter-count bases are routed through exact source rows. Two mixed quantity cases per section were calculated and priced offline. Inspection 10% crew scope remains unresolved; no full-rule coverage is claimed."}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: {"ok": v["focused_validation_ok"], "cases": len(v["cases"]), "routes": v["quantity_routes"]} for k, v in results.items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
