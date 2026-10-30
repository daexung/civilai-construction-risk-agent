"""Repair the misaligned 13-11-4 chunk text from its source PDF grid cells."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
CHUNKS = ROOT / "data/processed/chunks.all.jsonl"
BACKUP = ROOT / "tmp/chunk-p909-t0-pre-source-row-repair.json"
RECORD = ROOT / "evals/runtime_validation/chunk-p909-t0-source-row-repair-2026-10-19.json"


def main() -> int:
    table = pymupdf.open(PDF)[908].find_tables().tables[0].extract()
    assert table[0] == ["번호", "구 분", "손료율(%/월)", "비고"], table[0]
    numbers = [x.strip() for x in table[1][0].splitlines() if x.strip()]
    categories = [x.strip() for x in table[1][1].splitlines() if x.strip()]
    rates = [x.strip() for x in table[1][2].splitlines() if x.strip()]
    notes = [x.strip() for x in table[1][3].splitlines() if x.strip()]
    assert len(numbers) == 6 and len(categories) == 8 and len(rates) == len(notes) == 7
    rows = []
    data_index = 0
    for index, category in enumerate(categories):
        if index == 5:  # the printed heading for the two nested power-supply rows
            rows.append("6 | 구분 공사용 가설전원")
            continue
        rows.append(f"{numbers[min(index, 5)] if index < 5 else ''} | 구분 {category} "
                    f"| 손료율(%/월) {rates[data_index]} | 비고 {notes[data_index]}")
        data_index += 1
    assert data_index == 7
    replacement = "13-11-4 가설자재 손료율\n" + "\n".join(rows)

    lines = CHUNKS.read_text(encoding="utf-8").splitlines()
    changed, old = 0, None
    for i, line in enumerate(lines):
        chunk = json.loads(line)
        if chunk.get("chunk_id") != "p909-t0":
            continue
        old = line
        chunk["text"] = replacement
        lines[i] = json.dumps(chunk, ensure_ascii=False, separators=(",", ":"))
        changed += 1
    assert changed == 1
    BACKUP.write_text(old + "\n", encoding="utf-8")
    CHUNKS.write_text("\n".join(lines) + "\n", encoding="utf-8")
    RECORD.write_text(json.dumps({"chunk_id": "p909-t0", "source_pdf_page": 909,
                                  "printed_page": 853, "reconstructed_source_rows": len(rows),
                                  "method": "PyMuPDF grid extraction of four printed columns; nested power-supply rows retained separately",
                                  "backup": str(BACKUP.relative_to(ROOT)),
                                  "chunks_sha256": hashlib.sha256(CHUNKS.read_bytes()).hexdigest()},
                                 ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"chunk_id": "p909-t0", "rows": len(rows), "updated": changed,
                      "backup": str(BACKUP.relative_to(ROOT))}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
