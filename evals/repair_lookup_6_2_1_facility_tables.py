"""Select civil or building classification matrices before asking exact type rows."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "data/drafts/specs/공통/6-2-1.json"


def main() -> None:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    if not (ROOT / "tmp/6-2-1-spec-before-facility-table-route.json").exists():
        (ROOT / "tmp/6-2-1-spec-before-facility-table-route.json").write_bytes(SPEC.read_bytes())
    spec = package["draft"]
    category = next(field for field in spec["inputs"] if field["name"] == "facility_category")
    category["source_table_map"] = {"토목": "p189-t0", "건축": "p189-t1"}
    type_field = next(field for field in spec["inputs"] if field["name"] == "facility_type")
    type_field["source_row_key"] = True
    civil = next(table for table in spec["tables"] if table["id"] == "p189-t0")
    # OCR/table extraction repeated the spanning column header "유형" inside
    # wrapped cells. Remove only those inserted header tokens; wording stays
    # aligned with the printed source grid.
    for row, columns in civil["values"].items():
        for column, value in columns.items():
            value = value.replace("\n유형 ", "\n")
            value = value.replace("\n유형 - ", "\n- ")
            value = value.replace("유형 - ", "- ")
            columns[column] = value
    SPEC.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("facility category routes to its exact classification table; available Type rows come from that matrix")


if __name__ == "__main__":
    main()
