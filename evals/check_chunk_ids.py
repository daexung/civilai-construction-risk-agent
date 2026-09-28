"""Check page-local chunk IDs against both parsed ranges, without API calls."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.chunk import make_chunks  # noqa: E402

DATA = ROOT / "data/processed"
PAGES = set(range(185, 215))


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    checks = []
    narrow = read_jsonl(DATA / "chunks.jsonl")
    whole = read_jsonl(DATA / "chunks.all.jsonl")
    for name, parsed, saved in (("6장", "parsed.jsonl", narrow),
                                ("전체", "parsed.all.jsonl", whole)):
        generated = make_chunks(read_jsonl(DATA / parsed))
        checks.append((f"{name} 청크 재생성 일치", generated == saved))

    narrow_scope = {c["chunk_id"]: c["text"] for c in narrow if c["source"]["page"] in PAGES}
    whole_scope = {c["chunk_id"]: c["text"] for c in whole if c["source"]["page"] in PAGES}
    checks.append(("185~214쪽 ID·텍스트 동일", narrow_scope == whole_scope and len(narrow_scope) == 175))
    for name, chunks in (("6장", narrow), ("전체", whole)):
        counts = Counter(c["chunk_id"] for c in chunks)
        checks.append((f"{name} ID 중복 없음", len(counts) == len(chunks)))

    for label, passed in checks:
        print(f"{'PASS' if passed else 'FAIL'} {label}")
    print(f"통과 {sum(passed for _, passed in checks)} / 전체 {len(checks)}")
    return 0 if all(passed for _, passed in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
