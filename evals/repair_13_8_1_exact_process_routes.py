"""Restore exact 13-8-1 process rows, source table continuation, and units."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "data/drafts/specs/기계설비/13-8-1.json"

PROCESS = {
    "기술관리": ("p891-t0", "◦ 기술관리 - 소각로 본체 설치 공사", "일"),
    "포장해체": ("p891-t0", "◦ 포장해체 - 수송용 포장목재 해체 및 정리", "㎥"),
    "표면손질": ("p891-t0", "◦ 표면손질", "㎡"),
    "급진기설치": ("p891-t0", "◦ 급진기(Fuel Fedder)설치 - 투입홉퍼, Flap Damper 및 Hanger 설치 포함", "ton"),
    "소각로모듈설치": ("p891-t0", "◦ 소각로 모듈(Grate Module) 설치 - 하부 홉퍼 설치 포함", "ton"),
    "화격자설치": ("p891-t0", "◦ 화격자(Fire-Bar) 설치", "ton"),
    "내화물": ("p891-t0", "◦ 내화물", "ton"),
    "재축출기설치": ("p891-t1", "◦ 재 축출기 설치 - Wet Scrapper 설치 포함", "ton"),
    "원치설치및철거": ("p891-t1", "◦ 원치 설치 및 철거 - 조양을 위한 원치플리･로프 등의 설치와 사용후 철거까지 포함", "대"),
    # Inspection is intentionally absent: its source is a 10% rule over other
    # labor quantities, not a per-unit cell or a quantity with its own basis.
}


def main():
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    draft = package["draft"]
    model = draft["quantity_model"]["params"]
    rate = model["unit_rate_table"]
    inputs = {field["name"]: field for field in draft["inputs"]}
    tables = {table["id"]: table for table in draft["tables"]}
    assert set(PROCESS).issubset(inputs["process"]["allowed_values"])

    # Bind each named task to exactly one literal source row, rejecting any
    # ambiguous/missing mapping rather than using similarity at runtime.
    for process, (table_id, row, unit) in PROCESS.items():
        assert table_id in tables and row in tables[table_id]["values"], (process, table_id, row)
        assert tables[table_id].get("unit") is None
        assert unit in ("일", "㎥", "㎡", "ton", "대")

    inputs["quantity"]["unit"] = None
    inputs["quantity"]["ask"] = "선택한 공정의 원문 단위에 따른 물량은 얼마입니까?"
    rate["table"] = "p891-t0"
    rate["table_selector"] = {
        "input": "process",
        "values": {process: route[0] for process, route in PROCESS.items()},
    }
    rate["row_input"] = "process"
    rate["row_value_map"] = {process: route[1] for process, route in PROCESS.items()}
    rate["trades_by_row"] = {
        row: list(tables[table_id]["values"][row])
        for table_id, row, _unit in PROCESS.values()
    }
    # Trade is encoded directly in the selected source row's columns.
    rate["column_input"] = None
    rate["quantity_unit_selector"] = {
        "input": "process",
        "values": {process: route[2] for process, route in PROCESS.items()},
        "basis_by_selected_unit": True,
    }
    SPEC.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"restored {len(PROCESS)} exact process/table/row/unit routes in {SPEC.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
