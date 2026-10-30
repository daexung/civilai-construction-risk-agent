"""Restore source-visible row labels lost from the p371-t0 extracted table."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHUNKS = ROOT / "data/processed/chunks.all.jsonl"
BACKUP = ROOT / "tmp/chunks-before-per-unit-1-6-1-source-row-repair.jsonl"


def main() -> int:
    if not BACKUP.exists():
        shutil.copy2(CHUNKS, BACKUP)
    chunks = [json.loads(line) for line in CHUNKS.read_text(encoding="utf-8").splitlines() if line.strip()]
    chunk = next(item for item in chunks if item.get("chunk_id") == "p371-t0")
    chunk["text"] = "\n".join([
        "1-6-1 린 콘크리트 기층 포설", "기준 (일당)",
        "구분 포장공 | 단위 인 | 수량 2 | 시공량(㎥) 일반포장 550 | 터널포장 500",
        "구분 보통인부 | 단위 인 | 수량 2",
        "구분 아스팔트피니셔 | 규격 3m | 단위 대 | 수량 1",
        "구분 타이어롤러 | 규격 8∼15ton | 단위 대 | 수량 1",
        "구분 진동롤러 | 규격 10ton | 단위 대 | 수량 1",
    ])
    chunks[ chunks.index(next(item for item in chunks if item.get("chunk_id") == "p371-t0")) ] = chunk
    CHUNKS.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in chunks) + "\n", encoding="utf-8")
    print(json.dumps({"chunk_id": "p371-t0", "restored_rows": 5,
                      "source": "printed PDF p.315 visual grid; 2 labor rows, 3 equipment rows; two merged output columns",
                      "backup": str(BACKUP.relative_to(ROOT)),
                      }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
