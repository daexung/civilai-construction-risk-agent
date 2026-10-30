"""Restore the two labor rows and merged size columns visible in PDF p.657."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHUNKS = ROOT / "data/processed/chunks.all.jsonl"
BACKUP = ROOT / "tmp/chunks-before-per-unit-1-6-3-source-row-repair.jsonl"


def main() -> int:
    if not BACKUP.exists():
        shutil.copy2(CHUNKS, BACKUP)
    chunks = [json.loads(line) for line in CHUNKS.read_text(encoding="utf-8").splitlines() if line.strip()]
    chunk = next(item for item in chunks if item.get("chunk_id") == "p713-t1")
    chunk["text"] = "\n".join([
        "1-6-3 가교화 폴리에틸렌관 접합 및 배관", "기준 (m당)",
        "구분 배관공 | 단위 인 | 수량(규격) ø16mm 0.029 | ø20mm 0.036",
        "구분 보통인부 | 단위 인 | 수량(규격) ø16mm 0.014 | ø20mm 0.018",
    ])
    chunks[chunks.index(next(item for item in chunks if item.get("chunk_id") == "p713-t1"))] = chunk
    CHUNKS.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in chunks) + "\n", encoding="utf-8")
    print(json.dumps({"chunk_id": "p713-t1", "rows_restored": 2, "value_cells_restored": 4,
                      "source": "printed PDF p.657 visual grid; both row labels and ø16/ø20 merged columns",
                      "backup": str(BACKUP.relative_to(ROOT))}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
