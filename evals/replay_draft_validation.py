"""초안 검증 보고서를 지정 경로에 만들고(data/drafts/report.json은 건드리지 않음) 실행 가능 목록을 갱신한다.

사용: python evals/replay_draft_validation.py tmp/replay-draft-validation-current.json
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.validate_drafts import build_report, chunks_by_id_from_list, file_sha256  # noqa: E402


def main() -> int:
    target = ROOT / (sys.argv[1] if len(sys.argv) > 1 else "tmp/replay-draft-validation-current.json")
    chunk_path = ROOT / "data/processed/chunks.all.jsonl"
    chunks = chunks_by_id_from_list([json.loads(l) for l in chunk_path.read_text(encoding="utf-8").splitlines() if l.strip()])
    report = build_report(ROOT / "data/drafts", chunks, file_sha256(chunk_path))
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"검증 {report['ok']}/{report['total']} 형식 {report['with_format_issues']} 인용 {report['with_citation_issues']}")
    return subprocess.call([sys.executable, str(ROOT / "evals/check_draft_executability.py"), "--report", str(target)],
                           cwd=ROOT)


if __name__ == "__main__":
    sys.exit(main())
