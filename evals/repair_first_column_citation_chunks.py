"""Restore six source-visible table row labels lost from the text chunks.

The row/value transcription was checked against the original PDF page images:
689 (printed 633), 725 (669), 737 (681), 755 (699), 778 (722), and 976
(920). This intentionally repairs only these exact table IDs and preserves
all unrelated JSONL lines byte-for-byte.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHUNKS = ROOT / "data/processed/chunks.all.jsonl"
SPECS = ROOT / "data/drafts/specs"

# Explicit source transcriptions; every matrix must also equal the current
# draft table before a chunk is touched. `None` denotes a printed dash.
TRANSCRIPTIONS = {
    "p689-t0": ("건축", "10-3-2", {
        "유리공": {"12㎜이하": "0.120", "16㎜이하": "0.131", "18㎜이하": "0.137",
                   "22㎜이하": "0.139", "24㎜이하": "0.145", "28㎜이하": "0.155"},
        "보통인부": {"12㎜이하": "0.020", "16㎜이하": "0.021", "18㎜이하": "0.022",
                    "22㎜이하": "0.023", "24㎜이하": "0.024", "28㎜이하": "0.025"}}),
    "p725-t1": ("기계설비", "3-4-2", {
        "기계설비공": {"수량": "0.271"}, "보통인부": {"수량": "0.135"}}),
    "p737-t0": ("기계설비", "6-2-3", {
        "플랜트배관공": {"ø32mm": "0.71", "ø50mm": "0.75", "ø100mm": "0.85", "ø150mm": "0.95"},
        "특별인부": {"ø32mm": "0.71", "ø50mm": "0.75", "ø100mm": "0.85", "ø150mm": "0.95"},
        "계장공": {"ø32mm": "0.71", "ø50mm": "0.75", "ø100mm": "0.85", "ø150mm": "0.95"}}),
    "p755-t0": ("기계설비", "8-4-2", {
        "보일러공": {"15L": "0.17", "30L": "0.18", "50L": "0.23"},
        "보통인부": {"15L": "0.07", "30L": "0.08", "50L": "0.09"}}),
    "p778-t3": ("기계설비", "12-3-3", {
        "조립 및 설치": {"기사": "-", "계장공": "6.8"},
        "시험 및 조정": {"기사": "1.9", "계장공": "-"}}),
    "p976-t1": ("유지관리", "3-4-5", {
        "타일공": {"인원": "2"},
        "시공량": {"떠붙이기(벽)": "7", "압착붙이기(바닥)": "8"}}),
}


def row_line(label: str, values: dict[str, str]) -> str:
    return label + " | " + " | ".join(f"{column} {value}" for column, value in values.items())


def main() -> int:
    records = {}
    for table_id, (division, section, expected) in TRANSCRIPTIONS.items():
        package = json.loads((SPECS / division / f"{section}.json").read_text(encoding="utf-8"))
        tables = [table for table in package["draft"]["tables"] if table["id"] == table_id]
        assert len(tables) == 1, table_id
        assert tables[0]["values"] == expected, {"table": table_id, "spec": tables[0]["values"]}
        records[table_id] = expected

    lines = CHUNKS.read_text(encoding="utf-8").splitlines()
    updated, seen = [], set()
    for line in lines:
        chunk = json.loads(line)
        table_id = chunk.get("chunk_id")
        if table_id not in records:
            updated.append(line)
            continue
        assert table_id not in seen
        seen.add(table_id)
        original = chunk["text"].splitlines()
        assert len(original) >= 2
        rows = [row_line(label, values) for label, values in records[table_id].items()]
        chunk["text"] = "\n".join([*original[:2], *rows])
        updated.append(json.dumps(chunk, ensure_ascii=False, separators=(",", ":")))
    assert seen == set(records), {"seen": sorted(seen), "expected": sorted(records)}
    CHUNKS.write_text("\n".join(updated) + "\n", encoding="utf-8")
    print(json.dumps({"updated_chunks": sorted(seen), "count": len(seen),
                      "method": "source-transcribed full cell matrices; exact spec matrix match required",
                      "unrelated_lines_rewritten": False}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
