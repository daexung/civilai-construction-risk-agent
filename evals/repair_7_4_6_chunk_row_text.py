"""Restore the left/right paired table rows for civil 7-4-6 from its PDF."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
CHUNKS = ROOT / "data/processed/chunks.all.jsonl"
BACKUP = ROOT / "tmp/chunk-p452-t0-pre-source-row-repair.json"
REPORT = ROOT / "evals/runtime_validation/chunk-p452-t0-source-row-repair-2026-10-19.json"
PAIRS = [
    ("1.2이상", "없음"), ("1.2∼0.5", "5∼8"), ("0.6∼0.3", "10∼15"),
    ("0.3∼0.15", "20∼27"), ("0.15∼0.075", "30∼35"), ("0.075이하", "30∼100"),
]


def main() -> int:
    page = pymupdf.open(PDF)[451]
    source = page.get_text()
    for left, right in PAIRS:
        assert left in source and right in source, ("source pair incomplete", left, right)
    rows = ["입경(㎜) | 유실율(%)"] + [f"{left} | {right}" for left, right in PAIRS]
    replacement = "7-4-6 펌프준설 매립시의 유실률\n" + "\n".join(rows)
    lines = CHUNKS.read_text(encoding="utf-8").splitlines()
    updated = 0
    for i, line in enumerate(lines):
        chunk = json.loads(line)
        if chunk.get("chunk_id") != "p452-t0":
            continue
        BACKUP.write_text(line + "\n", encoding="utf-8")
        chunk["text"] = replacement
        lines[i] = json.dumps(chunk, ensure_ascii=False, separators=(",", ":"))
        updated += 1
    assert updated == 1
    CHUNKS.write_text("\n".join(lines) + "\n", encoding="utf-8")
    REPORT.write_text(json.dumps({"table_id": "p452-t0", "pdf_page": 452,
                                  "printed_page": 396, "source_pairs": len(PAIRS),
                                  "method": "Original page text cross-checked against the two paired table-column groups",
                                  "backup": str(BACKUP.relative_to(ROOT)),
                                  "chunks_sha256": hashlib.sha256(CHUNKS.read_bytes()).hexdigest()},
                                 ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"table_id": "p452-t0", "source_pairs": len(PAIRS),
                      "backup": str(BACKUP.relative_to(ROOT))}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
