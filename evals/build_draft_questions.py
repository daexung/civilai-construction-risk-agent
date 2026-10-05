"""Turn spec draft question lists (civilai-drafts) into a retrieval eval question set."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DRAFTS_DIR = Path(r"C:\Users\daeseong\Desktop\PROJECTS\civilai-drafts\data\drafts\specs")
OUT = ROOT / "evals/draft_questions.jsonl"


def collect(drafts_dir: Path) -> list[dict]:
    rows = []
    seen: set[str] = set()
    for path in sorted(drafts_dir.rglob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        draft = data.get("draft") or {}
        division, section_no = draft.get("division"), draft.get("section_no")
        if not division or not section_no:
            continue
        for order, question in enumerate(data.get("questions") or [], start=1):
            question = (question or "").strip()
            if not question or question in seen:
                continue
            seen.add(question)
            rows.append({"id": f"draft-{len(rows) + 1:04d}", "division": division,
                         "section_no": section_no, "question": question, "order": order})
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--drafts-dir", type=Path, default=DEFAULT_DRAFTS_DIR)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    if not args.drafts_dir.exists():
        raise SystemExit(f"초안 폴더 없음: {args.drafts_dir}")
    rows = collect(args.drafts_dir)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    print(f"질문 {len(rows)}개 -> {args.out}")
    for division, count in sorted(Counter(row["division"] for row in rows).items()):
        print(f"  {division}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
