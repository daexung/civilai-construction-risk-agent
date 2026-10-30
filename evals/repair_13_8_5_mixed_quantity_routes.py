"""Route every 13-8-5 work row through its own source table and quantity."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "data/drafts/specs/기계설비/13-8-5.json"


def activity(table, row, quantity, trades, unit, *, crew_trades=()):
    return {
        "table": table, "row_by_trade": {trade: row for trade in trades},
        "column_by_trade": {trade: trade for trade in trades},
        "trades": list(trades), "quantity_input": quantity, "basis": f"인/{unit}",
        "basis_by_trade": {trade: f"조/{unit}" for trade in crew_trades},
        "resource_units": {trade: "조" for trade in crew_trades},
    }


def main():
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    draft = package["draft"]
    tables = {table["id"]: table for table in draft["tables"]}
    rows = {
        ("p895-t2", "◦ 기술관리 - 설치공사 기간중"): {"기계기사": "0.96"},
        ("p895-t2", "◦ 포장해체 - 수송을 위해 포장된 목재를 해체하고 목재를 정리함"): {"목공": "0.06", "특별인부": "0.14"},
        ("p895-t2", "◦ 표면손질"): {"특별인부": "0.24"},
        ("p895-t2", "◦ 소운반"): {"특별인부": "0.66"},
        ("p895-t2", "- 작업위치까지 필요한 자재를 운반"): {"건설기계운전조": "0.21"},
        ("p895-t2", "◦ 기초작업 - Chipping 및 Grouting"): {"플랜트기계설치공": "0.01", "특별인부": "0.01"},
        ("p896-t0", "◦ 현장교정 - 수송도중 변형된 것을 바로 잡기"): {"특별인부": "2.07", "플랜트기계설치공": "0.04"},
        ("p896-t0", "◦ 본체조립 - 분리 운반된 Body 조립 포함"): {"플랜트제관공": "1.91", "플랜트용접공": "2.04", "특별인부": "3.93", "건설기계운전조": "1.32"},
        ("p896-t0", "◦ Inner Plate 및 Hanger 조립 - Suspention Device 조립 포함"): {"플랜트제관공": "1.14", "플랜트용접공": "3.36", "특별인부": "3.37"},
        ("p896-t0", "◦ 용접손질 - 용접 Joint부위 용접효율을 높이기 위함"): {"플랜트제관공": "2.19", "특별인부": "0.07"},
        ("p896-t0", "◦ 본체 설치 - Reactor 설치 포함"): {"플랜트기계설치공": "4.28", "플랜트제관공": "0.54", "비계공": "1.66", "특별인부": "2.28", "플랜트용접공": "3.97", "건설기계운전조": "4.07"},
        ("p896-t0", "◦ Sealing 용접 - 용접용 Support설치 및 운반포함"): {"플랜트용접공": "14.74", "플랜트제관공": "4.99", "특별인부": "1.07"},
    }
    for (table_id, row), expected in rows.items():
        assert table_id in tables and tables[table_id]["values"].get(row) == expected, (table_id, row)

    params = draft["quantity_model"]["params"]
    params["quantity_input"] = "tech_management_days"
    params["unit_rate_table"] = {
        "table": "p895-t2", "row_input": "◦ 기술관리 - 설치공사 기간중",
        "column_input": None, "row_by_trade": {"기계기사": "◦ 기술관리 - 설치공사 기간중"},
        "trades": ["기계기사"],
        "basis_by_row": {"◦ 기술관리 - 설치공사 기간중": "인/일"},
    }
    params["additional_unit_rates"] = [
        activity("p895-t2", "◦ 포장해체 - 수송을 위해 포장된 목재를 해체하고 목재를 정리함", "unpacking_vol", ["목공", "특별인부"], "㎥"),
        activity("p895-t2", "◦ 표면손질", "surface_prep_area", ["특별인부"], "㎡"),
        activity("p895-t2", "◦ 소운반", "transport_weight", ["특별인부"], "ton"),
        activity("p895-t2", "- 작업위치까지 필요한 자재를 운반", "transport_weight", ["건설기계운전조"], "ton", crew_trades=["건설기계운전조"]),
        activity("p895-t2", "◦ 기초작업 - Chipping 및 Grouting", "foundation_weight", ["플랜트기계설치공", "특별인부"], "ton"),
        activity("p896-t0", "◦ 현장교정 - 수송도중 변형된 것을 바로 잡기", "calibration_weight", ["특별인부", "플랜트기계설치공"], "ton"),
        activity("p896-t0", "◦ 본체조립 - 분리 운반된 Body 조립 포함", "body_assembly_weight", ["플랜트제관공", "플랜트용접공", "특별인부", "건설기계운전조"], "ton", crew_trades=["건설기계운전조"]),
        activity("p896-t0", "◦ Inner Plate 및 Hanger 조립 - Suspention Device 조립 포함", "inner_plate_weight", ["플랜트제관공", "플랜트용접공", "특별인부"], "ton"),
        activity("p896-t0", "◦ 용접손질 - 용접 Joint부위 용접효율을 높이기 위함", "weld_prep_weight", ["플랜트제관공", "특별인부"], "ton"),
        activity("p896-t0", "◦ 본체 설치 - Reactor 설치 포함", "body_install_weight", ["플랜트기계설치공", "플랜트제관공", "비계공", "특별인부", "플랜트용접공", "건설기계운전조"], "ton", crew_trades=["건설기계운전조"]),
        activity("p896-t0", "◦ Sealing 용접 - 용접용 Support설치 및 운반포함", "sealing_weld_weight", ["플랜트용접공", "플랜트제관공", "특별인부"], "ton"),
    ]
    params["input_rate_adjustments"] = [{
        "operation": "add_source_percent", "name": "검사 및 교정", "percent": "10",
        "kinds": ["labor"], "exclude_trades": ["기계기사"],
        "exclude_quantity_inputs": ["unpacking_vol"],
        "cite": {"table_id": "p896-t0",
                 "row": "◦ 검사 및 교정 - Gas Leak Test 포함",
                 "column": "기술관리, 포장해체를 제외한 전공량의 10%"},
    }]
    params["note_adjustments"] = []
    draft["quantity_model"]["steps"] = [
        "각 작업별로 입력한 물량에 대응하는 원문의 작업 행 및 단위(일·㎥·㎡·ton)를 적용한다.",
        "건설기계운전조 행은 조/ton 단위를 그대로 보존한다.",
        "검사 및 교정은 기술관리와 포장해체를 제외한 전공량의 10%를 더한다.",
        "보온 및 도장작업과 추가 장비는 별도 계상한다. 건설기계운전조 편성은 현장 작업조건과 설치물량을 고려해야 한다.",
    ]
    draft["not_calculated"].append({
        "item": "건설기계운전조 편성의 현장조건 조정", "source": "PDF 840쪽 1. 공정별 설치 [주] ④",
        "cite": {"chunk_id": "p896-x21", "quote": "④ 건설기계운전조는 작업조건 및 설치물량 등을 감안하여 편성한다."},
    })
    draft["not_calculated"].append({
        "item": "기본 사용장비 경비 및 선택", "source": "PDF 840쪽 2. 사용장비",
        "cite": [
            {"table_id": "p896-t1", "row": "크레인", "column": "200톤", "value": "1"},
            {"table_id": "p896-t1", "row": "지게차", "column": "5톤", "value": "1"},
            {"table_id": "p896-t1", "row": "용접기", "column": "15KVA", "value": "2"},
        ],
    })
    SPEC.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"restored {len(params['additional_unit_rates'])} exact work-row routes across two tables: {SPEC.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
