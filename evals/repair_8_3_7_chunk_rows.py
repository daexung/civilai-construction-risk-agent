"""Reconstruct the two p311-t0 rows from the PDF's merged-cell table grid."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
CHUNKS = ROOT / "data/processed/chunks.all.jsonl"
BACKUP = ROOT / "tmp/chunk-p311-t0-pre-source-row-repair.json"
REPORT = ROOT / "evals/runtime_validation/chunk-p311-t0-source-row-repair-2026-10-19.json"


def main() -> int:
    extracted = pymupdf.open(PDF)[310].find_tables().tables[0].extract()
    assert len(extracted) == 3 and len(extracted[0]) == 11
    code_lines = [line.strip() for line in extracted[2][0].splitlines() if line.strip()]
    assert code_lines == ["6105-0190", "0390"]
    spec_lines = [line.strip() for line in extracted[2][1].splitlines() if line.strip()]
    specs = [" ".join(spec_lines[i:i + 2]) for i in range(0, len(spec_lines), 2)]
    assert specs == ["190×2 (2㎾)", "390×2 (5㎾)"]
    columns = [[line.strip() for line in extracted[2][index].splitlines() if line.strip()]
               for index in range(2, 11)]
    assert all(len(column) == 2 for column in columns)
    table_labels = ["내용 시간", "연간표준 가동시간", "상각 비율", "정비 비율", "연간 관리 비율",
                    "시 간 당(10-7) 상각비 계수", "시 간 당(10-7) 정비비 계수",
                    "시 간 당(10-7) 관리비 계수", "시 간 당(10-7) 계"]
    rendered = ["8-3-7 [60]기초공사용 기계", "(6105) 고성능 착정기"]
    for i, code in enumerate(code_lines):
        row_code = code if "-" in code else "6105-" + code
        values = [column[i] for column in columns]
        rendered.append(" | ".join([f"분류 번호 {row_code}", f"규격 {specs[i]}",
                                   *[f"{label} {value}" for label, value in zip(table_labels, values)]]))

    lines = CHUNKS.read_text(encoding="utf-8").splitlines()
    updated = 0
    for i, line in enumerate(lines):
        chunk = json.loads(line)
        if chunk.get("chunk_id") != "p311-t0":
            continue
        BACKUP.write_text(line + "\n", encoding="utf-8")
        chunk["text"] = "\n".join(rendered)
        lines[i] = json.dumps(chunk, ensure_ascii=False, separators=(",", ":"))
        updated += 1
    assert updated == 1
    CHUNKS.write_text("\n".join(lines) + "\n", encoding="utf-8")
    REPORT.write_text(json.dumps({"table_id": "p311-t0", "pdf_page": 311,
                                  "printed_page": 255, "source_rows": 2,
                                  "source_cells": 22,
                                  "method": "PyMuPDF source grid; grouped the two physical spec lines into their original merged row cells",
                                  "backup": str(BACKUP.relative_to(ROOT)),
                                  "chunks_sha256": hashlib.sha256(CHUNKS.read_bytes()).hexdigest()},
                                 ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"table_id": "p311-t0", "source_rows": 2, "source_cells": 22,
                      "backup": str(BACKUP.relative_to(ROOT))}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
