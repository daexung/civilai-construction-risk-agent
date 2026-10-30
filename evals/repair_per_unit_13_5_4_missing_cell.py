"""Restore the visually confirmed 2.87 cell omitted from p831-t0 text."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHUNKS = ROOT / "data/processed/chunks.all.jsonl"
BACKUP = ROOT / "tmp/chunks-before-per-unit-13-5-4-2_87-repair.jsonl"
JOB = "DUCT 설치 성형된 duct를 운반조양 alignment후 bolting 및 hangering"


def main() -> int:
    if not BACKUP.exists():
        shutil.copy2(CHUNKS, BACKUP)
    chunks = [json.loads(line) for line in CHUNKS.read_text(encoding="utf-8").splitlines() if line.strip()]
    chunk = next(item for item in chunks if item.get("chunk_id") == "p831-t0")
    line = f"{JOB} | 직종 비계공 | 단위 인/ton | 수량 2.87"
    if line not in chunk["text"]:
        assert "수량 2.87" not in chunk["text"]
        chunk["text"] += "\n" + line
    CHUNKS.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in chunks) + "\n", encoding="utf-8")
    print(json.dumps({"chunk_id": "p831-t0", "restored_cell": {"job": JOB, "trade": "비계공",
                      "unit": "인/ton", "value": "2.87"},
                      "structure_status_preserved": chunk.get("structure"),
                      "backup": str(BACKUP.relative_to(ROOT))}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
