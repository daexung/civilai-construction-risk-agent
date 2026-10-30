"""Separate the two independent 1-4-6 source tables and preserve their exact labels."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "data/drafts/specs/공통/1-4-6.json"
BACKUP = ROOT / "tmp/1-4-6-spec-before-independent-table-routing.json"
WORK_TIME = "작업시간 제한"
HEAT_WAVE = "폭염시 휴게시간"


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    draft = package["draft"]
    fields = {field["name"]: field for field in draft["inputs"]}
    tables = {table["id"]: table for table in draft["tables"]}
    shutil.copy2(SPEC, BACKUP)
    work_conditions = ["2시간 이하", "3시간 〃", "4시간 〃", "5시간 〃", "6시간 〃"]
    work_rates = ["50%", "35%", "25%", "20%", "15%"]
    heat_conditions = ["2시간 이상일 경우 작업시", "4시간 〃", "6시간 〃", "8시간 〃"]
    heat_rates = ["5%", "10%", "15%", "20%"]
    tables["p85-t1"]["values"] = {"작업가능시간": dict(zip(work_conditions, work_rates))}
    tables["p85-t2"]["values"] = {"체감온도 33도 이상": dict(zip(heat_conditions, heat_rates))}
    draft["inputs"].insert(0, {
        "name": "lookup_type", "type": "enum", "allowed_values": [WORK_TIME, HEAT_WAVE],
        "unit": None, "required": True, "ask": "조회할 작업제한 기준을 선택해주세요.",
        "source": "PDF p.29: 1. 작업시간 제한 / 2. 폭염시 휴게시간 할증",
        "source_table_map": {WORK_TIME: "p85-t1", HEAT_WAVE: "p85-t2"},
    })
    fields["work_time_limit"]["allowed_values"] = work_conditions
    fields["heat_wave_work_time"]["allowed_values"] = heat_conditions
    fields["work_time_limit"]["when"] = {"input": "lookup_type", "equals": WORK_TIME}
    fields["heat_wave_work_time"]["when"] = {"input": "lookup_type", "equals": HEAT_WAVE}
    package["citations"] = [citation for citation in package.get("citations", [])
                            if citation.get("table_id") not in {"p85-t1", "p85-t2"}] + [
        {"table_id": table_id, "row": row, "column": column, "value": value}
        for table_id in ("p85-t1", "p85-t2")
        for row, columns in tables[table_id]["values"].items()
        for column, value in columns.items()
    ]
    SPEC.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = {"cause": "two separate time-policy tables were required simultaneously; ditto marks and row headers were not represented as exact lookup axes",
              "exact_routes": {WORK_TIME: "p85-t1", HEAT_WAVE: "p85-t2"},
              "source_cells_rebuilt": len(work_rates) + len(heat_rates),
              "backup": str(BACKUP.relative_to(ROOT)),
              "spec_sha256": hashlib.sha256(SPEC.read_bytes()).hexdigest()}
    out = ROOT / "evals/runtime_validation/repair-1-4-6-independent-table-routing-2026-10-19.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
