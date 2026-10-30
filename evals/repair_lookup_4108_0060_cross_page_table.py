"""Restore the 8-4-5 concrete plant table split across printed pages 280-281."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "data/drafts/specs/공통/4108-0060.json"
CHUNKS = ROOT / "data/processed/chunks.all.jsonl"
SPEC_BACKUP = ROOT / "tmp/4108-0060-spec-before-cross-page-table-repair.json"
CHUNKS_BACKUP = ROOT / "tmp/chunks-before-4108-0060-cross-page-table-repair.jsonl"
COLUMNS = ["기계명", "규격", "주연료\n(ℓ/hr)", "잡재료\n(주연료의%)", "조종원\n(인/일)"]
ROWS = {
    "p336-t1": {
        "0060": ["콘크리트배치플랜트", "60㎥/hr(96㎾)", "-", "-", "1"],
        "0090": ["콘크리트배치플랜트", "90 (144)", "-", "-", "1"],
        "0120": ["콘크리트배치플랜트", "120 (160)", "-", "-", "1"],
        "0150": ["콘크리트배치플랜트", "150 (177)", "-", "-", "1"],
        "0180": ["콘크리트배치플랜트", "180 (213)", "-", "-", "1"],
    },
    "p337-t0": {"0210": ["콘크리트배치플랜트", "210 (233)", "-", "-", "1"]},
}


def main() -> int:
    if not SPEC_BACKUP.exists():
        shutil.copy2(SPEC, SPEC_BACKUP)
    if not CHUNKS_BACKUP.exists():
        shutil.copy2(CHUNKS, CHUNKS_BACKUP)
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    draft = package["draft"]
    field = next(item for item in draft["inputs"] if item["name"] == "machine_spec")
    label_to_code = {"60㎥/hr": "0060", "90㎥/hr": "0090", "120㎥/hr": "0120",
                     "150㎥/hr": "0150", "180㎥/hr": "0180", "210 (233)": "0210"}
    field["allowed_values"] = list(label_to_code)
    field["machine_codes"] = label_to_code
    field["source"] = "PDF 인쇄 280~281쪽 8-4-5 [40] 콘크리트기계; p336-t1에서 p337-t0로 이어짐"
    field["ask"] = "콘크리트배치플랜트의 규격은 무엇입니까?"
    draft["source_pages"] = [280, 281]
    draft["tables"] = [
        {"id": table_id, "role": "콘크리트배치플랜트 규격별 경비자료",
         "source": "8-4-5 [40] 콘크리트기계 (인쇄 280~281쪽)",
         "values": {row: dict(zip(COLUMNS, values)) for row, values in rows.items()},
         "cite": {"table_id": table_id}}
        for table_id, rows in ROWS.items()
    ]
    package["citations"] = [
        {"table_id": table_id, "row": row, "column": column, "value": value}
        for table_id, rows in ROWS.items() for row, values in rows.items()
        for column, value in zip(COLUMNS, values)
    ]
    draft["open_questions"] = []
    package["open_questions"] = []
    package["questions"] = [
        "콘크리트배치플랜트 120㎥/hr 규격의 조종원 수는 몇 명인가요?",
        "콘크리트배치플랜트 210 (233) 규격의 주연료와 잡재료는 무엇인가요?",
    ]

    chunks = [json.loads(line) for line in CHUNKS.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_id = {item["chunk_id"]: item for item in chunks}
    p336 = by_id["p336-t1"]
    p336["text"] = "8-4-5 [40]콘크리트기계\n" + "\n".join(
        f"4108-{row} | 기계명 콘크리트배치플랜트 | 규격 {values[1]} | 주연료 (ℓ/hr) - | "
        f"잡재료 (주연료의%) - | 조종원 (인/일) 1"
        for row, values in ROWS["p336-t1"].items())
    p337 = by_id["p337-t0"]
    old_text = p337["text"]
    split_marker = "\n0210 4205-0010"
    split_at = old_text.find(split_marker)
    assert split_at >= 0
    remainder = old_text[split_at + 1:]
    p337["text"] = (
        "8-4-5 [40]콘크리트기계\n"
        "0210 | 기계명 콘크리트배치플랜트 | 규격 210 (233) | 주연료 (ℓ/hr) - | "
        "잡재료 (주연료의%) - | 조종원 (인/일) 1\n" + remainder
    )
    p337["section"] = "8-4-5 [40]콘크리트기계"
    p337["section_no"] = "8-4-5"
    p337["division"] = "공통"
    CHUNKS.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in chunks) + "\n", encoding="utf-8")
    SPEC.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"spec": str(SPEC), "routes": {key: list(rows) for key, rows in ROWS.items()},
                      "independent_rows": sum(len(rows) for rows in ROWS.values()),
                      "cells": sum(len(values) for rows in ROWS.values() for values in rows.values()),
                      "source_section": "8-4-5 [40]콘크리트기계", "printed_pages": [280, 281]},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
