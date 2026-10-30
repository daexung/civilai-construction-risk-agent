"""Restore the 2-2-4 two-row header/data labels from the PDF page text."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
CHUNKS = ROOT / "data/processed/chunks.all.jsonl"
BACKUP = ROOT / "tmp/chunk-p96-t0-pre-source-row-repair.json"
RECORD = ROOT / "evals/runtime_validation/chunk-p96-t0-source-row-repair-2026-10-19.json"


def main() -> int:
    page = pymupdf.open(PDF)[95]
    body = page.get_text()
    for token in ["기 간", "구 분", "1개월", "3개월", "6개월", "12개월", "손율(%)", "4", "7", "11", "21"]:
        assert token in body, ("source table token missing", token)
    lines = CHUNKS.read_text(encoding="utf-8").splitlines()
    updated = 0
    for i, line in enumerate(lines):
        chunk = json.loads(line)
        if chunk.get("chunk_id") != "p96-t0":
            continue
        BACKUP.write_text(line + "\n", encoding="utf-8")
        chunk["text"] = ("2-2-4 구조물 동바리('22, '26년 보완)\n"
                         "기간 구분 | 1개월 | 3개월 | 6개월 | 12개월\n"
                         "손율(%) | 4 | 7 | 11 | 21")
        lines[i] = json.dumps(chunk, ensure_ascii=False, separators=(",", ":"))
        updated += 1
    assert updated == 1
    CHUNKS.write_text("\n".join(lines) + "\n", encoding="utf-8")
    RECORD.write_text(json.dumps({"chunk_id": "p96-t0", "source_pdf_page": 96,
                                  "printed_page": 40, "source_tokens_checked": 11,
                                  "method": "Rendered PDF page text and visual table cross-check; explicit header and rate row",
                                  "backup": str(BACKUP.relative_to(ROOT)),
                                  "chunks_sha256": hashlib.sha256(CHUNKS.read_bytes()).hexdigest()},
                                 ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"chunk_id": "p96-t0", "updated": updated,
                      "backup": str(BACKUP.relative_to(ROOT))}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
