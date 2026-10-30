"""Restore the four visible rock rows in the 3-2-2 source table."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "data/drafts/specs/공통/3-2-2.json"
CHUNKS = ROOT / "data/processed/chunks.all.jsonl"
SPEC_BACKUP = ROOT / "tmp/3-2-2-spec-before-rock-row-reconstruction.json"
CHUNKS_BACKUP = ROOT / "tmp/chunks-before-3-2-2-rock-row-reconstruction.jsonl"
TABLE_TEXT = """3-2-2 굴착(인력/암반)('20년 보완)
기준 (㎥당)
풍 화 암 | 착 암 공 (인) 0.33 | 보통인부 (인) 0.16 | 공기압축기 (시간) 0.30 | 소형브레이커 (시간) 1.26
연 암 | 착 암 공 (인) 0.41 | 보통인부 (인) 0.21 | 공기압축기 (시간) 0.48 | 소형브레이커 (시간) 1.68
보 통 암 | 착 암 공 (인) 0.58 | 보통인부 (인) 0.29 | 공기압축기 (시간) 0.60 | 소형브레이커 (시간) 2.40
경 암 | 착 암 공 (인) 0.94 | 보통인부 (인) 0.48 | 공기압축기 (시간) 0.96 | 소형브레이커 (시간) 3.90
비고: 공기압축기 7.1㎥/min; 소형브레이커 1.3㎥/min, 4대 기준"""
VALUES = {
    "풍 화 암": {"착암공\n(인)": "0.33", "보통인부\n(인)": "0.16", "공기압축기\n(시간)": "0.30", "소형브레이커\n(시간)": "1.26"},
    "연 암": {"착암공\n(인)": "0.41", "보통인부\n(인)": "0.21", "공기압축기\n(시간)": "0.48", "소형브레이커\n(시간)": "1.68"},
    "보 통 암": {"착암공\n(인)": "0.58", "보통인부\n(인)": "0.29", "공기압축기\n(시간)": "0.60", "소형브레이커\n(시간)": "2.40"},
    "경 암": {"착암공\n(인)": "0.94", "보통인부\n(인)": "0.48", "공기압축기\n(시간)": "0.96", "소형브레이커\n(시간)": "3.90"},
}


def main() -> int:
    if not SPEC_BACKUP.exists():
        shutil.copy2(SPEC, SPEC_BACKUP)
    if not CHUNKS_BACKUP.exists():
        shutil.copy2(CHUNKS, CHUNKS_BACKUP)
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    draft = package["draft"]
    draft["id"] = "2026-정오표1차/공통/3-2-2/굴착_인력_암반"
    rock = next(field for field in draft["inputs"] if field["name"] == "rock_type")
    rock["allowed_values"] = ["풍화암", "연암", "보통암", "경암"]
    rate = draft["quantity_model"]["params"]["unit_rate_table"]
    rate["row_value_map"] = {"풍화암": "풍 화 암", "연암": "연 암", "보통암": "보 통 암", "경암": "경 암"}
    rate["trades"] = list(VALUES[next(iter(VALUES))])
    rate["resource_units"] = {"공기압축기\n(시간)": "hr", "소형브레이커\n(시간)": "hr"}
    draft["tables"][0]["values"] = VALUES
    draft["tables"][0]["unit"] = "인/㎥, 시간/㎥"
    note_citations = [cite for cite in package.get("citations", []) if "chunk_id" in cite]
    table_citations = [
        {"table_id": "p124-t0", "row": row, "column": column, "value": value}
        for row, cells in VALUES.items() for column, value in cells.items()]
    package["citations"] = table_citations + note_citations
    draft["not_calculated"] = [{
        "item": "공기압축기 및 소형브레이커의 기계경비 금액",
        "source": "원문 운전시간 수량은 산출함. 장비 단가가 연결되지 않아 금액은 별도 산출하지 않음.",
        "cite": {"table_id": "p124-t0"},
    }]
    SPEC.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    chunks = [json.loads(line) for line in CHUNKS.read_text(encoding="utf-8").splitlines() if line.strip()]
    chunk = next(item for item in chunks if item.get("chunk_id") == "p124-t0")
    chunk["text"] = TABLE_TEXT
    chunk["structure"] = "ok"
    chunk["issues"] = []
    chunk.pop("uncertain_record_ids", None)
    CHUNKS.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in chunks) + "\n", encoding="utf-8")
    print(json.dumps({"spec": str(SPEC), "source_table": "p124-t0", "restored_rows": len(VALUES),
                      "restored_cells": sum(map(len, VALUES.values())), "id": draft["id"],
                      "equipment_hours": "resource_units maps source time columns to equipment-hour output"},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
