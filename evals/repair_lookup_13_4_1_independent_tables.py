"""Represent the two independent 13-4-1 source tables with exact conditional routes."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "data/drafts/specs/기계설비/13-4-1.json"
BACKUP = ROOT / "tmp/13-4-1-spec-before-independent-table-routing.json"
CHUNKS = ROOT / "data/processed/chunks.all.jsonl"
CHUNK_BACKUP = ROOT / "tmp/chunks-before-13-4-1-independent-table-routing.jsonl"
LOOKUP_TYPE = "조회할 기준표"
WEIGHT = "철골재의 무게산출 표준"
ACCESSORY = "부속재의 비율"


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    draft = package["draft"]
    fields = {field["name"]: field for field in draft["inputs"]}
    tables = {table["id"]: table for table in draft["tables"]}
    if not BACKUP.exists():
        shutil.copy2(SPEC, BACKUP)
    weight_rows = {
        "철골조건물": {"연면적에 대하여": "0.10∼0.15", "목재중도리": "0.04∼0.06"},
        "철골조지붕틀": {"철골중도리": "0.06∼0.08", "철근을 구조계산에 가산할 경우": "0.08∼0.10"},
        "철골철근콘크리트조": {"철근을 구조계산에 가산하지 않을 경우": "0.10∼0.15"},
    }
    assert set(tables) == {"p820-t1", "p820-t2"}
    tables["p820-t1"]["values"] = weight_rows
    fields["structure_type"]["allowed_values"] = list(dict.fromkeys(
        column for row in weight_rows.values() for column in row))
    draft["inputs"].insert(0, {
        "name": "lookup_type", "type": "enum", "allowed_values": [WEIGHT, ACCESSORY],
        "unit": None, "required": True, "ask": "조회할 기준표를 선택해주세요.",
        "source": "PDF p.764: 1. 철골재의 무게산출 표준 / 2. 부속재의 비율",
        "source_table_map": {WEIGHT: "p820-t1", ACCESSORY: "p820-t2"},
    })
    fields["building_type"]["when"] = {"input": "lookup_type", "equals": WEIGHT}
    fields["structure_type"]["when"] = {"input": "lookup_type", "equals": WEIGHT}
    fields["main_material"]["when"] = {"input": "lookup_type", "equals": ACCESSORY}
    package["citations"] = [citation for citation in package.get("citations", [])
                            if citation.get("table_id") != "p820-t1"] + [
        {"table_id": "p820-t1", "row": row, "column": column, "value": value}
        for row, columns in weight_rows.items() for column, value in columns.items()
    ]
    package["citations"] = [citation for citation in package.get("citations", [])
                            if citation.get("table_id") != "p820-t1"] + [
        {"table_id": "p820-t1", "row": row, "column": column, "value": value}
        for row, columns in weight_rows.items() for column, value in columns.items()
    ]
    if not CHUNK_BACKUP.exists():
        shutil.copy2(CHUNKS, CHUNK_BACKUP)
    lines = CHUNKS.read_text(encoding="utf-8").splitlines()
    updated = 0
    for index, line in enumerate(lines):
        chunk = json.loads(line)
        if chunk.get("chunk_id") != "p820-t1":
            continue
        chunk["text"] = "\n".join([
            "13-4-1 보통 철골재", "1. 철골재의 무게산출 표준", "기준 (m당)",
            *[f"건물종별 {row} | 구조별 {structure} | 철골무게 (ton) {value}"
              for row, columns in weight_rows.items() for structure, value in columns.items()],
        ])
        chunk["structure"] = "ok"
        chunk["uncertain_record_ids"] = []
        chunk["issues"] = []
        lines[index] = json.dumps(chunk, ensure_ascii=False, separators=(",", ":"))
        updated += 1
    assert updated == 1
    CHUNKS.write_text("\n".join(lines) + "\n", encoding="utf-8")
    SPEC.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = {
        "cause": "one lookup spec required axes from two independent source tables simultaneously; table 1 structure labels were flattened with repeated header text",
        "source_tables": {WEIGHT: "p820-t1", ACCESSORY: "p820-t2"},
        "source_value_cells_rebuilt": sum(len(row) for row in weight_rows.values()),
        "p820_t2_cells_preserved": sum(len(row) for row in tables["p820-t2"]["values"].values()),
        "backup": str(BACKUP.relative_to(ROOT)),
        "spec_sha256": hashlib.sha256(SPEC.read_bytes()).hexdigest(),
        "chunk_backup": str(CHUNK_BACKUP.relative_to(ROOT)),
        "chunks_sha256": hashlib.sha256(CHUNKS.read_bytes()).hexdigest(),
    }
    out = ROOT / "evals/runtime_validation/repair-13-4-1-independent-table-routing-2026-10-19.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
