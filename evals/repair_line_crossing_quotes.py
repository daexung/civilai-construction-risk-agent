"""청크의 줄바꿈 표지('설명 |')가 문장 중간에 끼어 실패하는 본문 인용을 청크에 그대로 있는 앞부분으로 줄인다.

문장을 바꾸거나 다른 곳에서 찾아오지 않는다(원문에 그대로 있는 부분만 남김). 표(row/column/value) 인용은 건드리지 않는다.
기본은 점검만(dry-run). --apply 일 때 원본을 백업 JSONL로 남기고 명세를 고친다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.validate_drafts import check_text_citation, chunks_by_id_from_list  # noqa: E402

CHUNKS = ROOT / "data/processed/chunks.all.jsonl"
SPECS = ROOT / "data/drafts/specs"
BACKUP = ROOT / "tmp/citation-quote-trim-pre-2026-10-19.jsonl"
REPORT = ROOT / "evals/runtime_validation/citation-quote-trim-2026-10-19.json"
MIN_CHARS = 12  # 이보다 짧게 줄어드는 인용은 고치지 않는다(근거로서 의미가 없다)


def walk(value):
    if isinstance(value, dict):
        if isinstance(value.get("chunk_id"), str) and isinstance(value.get("quote"), str):
            yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def shorten(index: dict, cite: dict) -> str | None:
    pieces = sorted((p.strip() for p in cite["quote"].splitlines() if p.strip()), key=len, reverse=True)
    for piece in pieces:
        if len(piece) >= MIN_CHARS and not check_text_citation(index, {**cite, "quote": piece}):
            return piece
    words = " ".join(cite["quote"].split()).split(" ")
    while len(words) > 3:
        words.pop()
        candidate = " ".join(words)
        if len(candidate) >= MIN_CHARS and not check_text_citation(index, {**cite, "quote": candidate}):
            return candidate
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    index = chunks_by_id_from_list([json.loads(l) for l in CHUNKS.read_text(encoding="utf-8").splitlines() if l.strip()])
    changes, unrepaired, files = [], [], 0
    backups = []
    for path in sorted(SPECS.rglob("*.json")):
        package = json.loads(path.read_text(encoding="utf-8"))
        original = path.read_text(encoding="utf-8")
        touched = False
        for cite in list(walk(package["citations"])) + list(walk(package["draft"])):
            if not check_text_citation(index, cite):
                continue
            new = shorten(index, cite)
            rel = str(path.relative_to(ROOT)).replace("\\", "/")
            if new is None:
                unrepaired.append({"path": rel, "chunk_id": cite["chunk_id"], "quote": cite["quote"][:80]})
                continue
            changes.append({"path": rel, "chunk_id": cite["chunk_id"], "before": cite["quote"], "after": new})
            cite["quote"] = new
            touched = True
        if touched:
            files += 1
            backups.append({"path": str(path.relative_to(ROOT)).replace("\\", "/"), "content": original})
            if args.apply:
                path.write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"고칠 인용 {len(changes)}건 / 명세 {files}개, 고치지 못한 본문 인용 {len(unrepaired)}건 ({'적용' if args.apply else 'dry-run'})")
    if args.apply:
        BACKUP.write_text("\n".join(json.dumps(b, ensure_ascii=False) for b in backups) + "\n", encoding="utf-8")
        REPORT.write_text(json.dumps({"changed": changes, "unrepaired": unrepaired}, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
