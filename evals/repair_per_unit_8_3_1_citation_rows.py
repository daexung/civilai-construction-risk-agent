"""Reconstruct the six omitted source rows that blocked 8-3-1 citations."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHUNKS = ROOT / "data/processed/chunks.all.jsonl"
BACKUP = ROOT / "tmp/chunks-before-8-3-1-refraction-table-reconstruction.jsonl"
ROWS = [
    ("기 술 사", "3.8"), ("특 급 기 술 자", "5.1"), ("고 급 기 술 자", "10.8"),
    ("중 급 기 술 자", "14.6"), ("특 별 인 부", "3.8"), ("보 통 인 부", "13.3"),
]


def main() -> int:
    if not BACKUP.exists():
        shutil.copy2(CHUNKS, BACKUP)
    chunks = [json.loads(line) for line in CHUNKS.read_text(encoding="utf-8").splitlines() if line.strip()]
    chunk = next(item for item in chunks if item.get("chunk_id") == "p457-t0")
    chunk["text"] = "\n".join([
        "8-3-1 굴절법 탄성파 탐사('08년 보완)", "기준 (측선 1km당)", "종 별 | 단 위 | 수 량",
        *(f"{trade} | 인 | {value}" for trade, value in ROWS),
    ])
    chunk["structure"] = "ok"
    chunk["issues"] = []
    chunk.pop("uncertain_record_ids", None)
    CHUNKS.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in chunks) + "\n", encoding="utf-8")
    print(json.dumps({"chunk": "p457-t0", "restored_rows": len(ROWS), "restored_value_cells": len(ROWS),
                      "source": "printed PDF p.401; row label and values transcribed from visible grid",
                      "backup": str(BACKUP.relative_to(ROOT))}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
