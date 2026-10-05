"""Check corrected page divisions and quarantine of misfiled drafts."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.agent.rules.misfiled import misfiled_ids  # noqa: E402
from backend.agent.rules.scope import enabled_divisions  # noqa: E402
from backend.agent.rules.specs import load_specs  # noqa: E402
from backend.agent.tools.search.vector import VectorIndex  # noqa: E402
from pipeline.page_map import correct_isolated_divisions, isolated_divisions  # noqa: E402


def main() -> int:
    checks = []
    numbered = {str(i): {"division": value, "printed_page": i, "division_reason": None}
                for i, value in enumerate(("유지관리부문", "공통부문", "유지관리부문"), 1)}
    checks.append(("numbered isolated correction", correct_isolated_divisions(numbered) == [2]
                   and numbered["2"]["division"] == "유지관리부문"
                   and "PDF 1·3쪽" in numbered["2"]["division_reason"]))
    title = {str(i): {"division": value, "printed_page": None if i == 2 else i,
                      "division_reason": None}
             for i, value in enumerate(("건축부문", "기계설비부문", "건축부문"), 1)}
    checks.append(("unnumbered title preserved", isolated_divisions(title) == [2]
                   and correct_isolated_divisions(title) == []
                   and title["2"]["division"] == "기계설비부문"))

    pages = json.loads((ROOT / "data/processed/page_map.json").read_text(encoding="utf-8"))["pages"]
    checks.append(("PDF 947 maintenance", pages["947"]["division"] == "유지관리부문"
                   and "단일 쪽 부문 이상치" in pages["947"]["division_reason"]))
    checks.append(("PDF 699 title preserved", pages["699"]["division"] == "기계설비부문"
                   and pages["699"]["printed_page"] is None))
    chunks = [json.loads(line) for line in (ROOT / "data/processed/chunks.all.jsonl").read_text(encoding="utf-8").splitlines()
              if line.strip()]
    on_page = [chunk for chunk in chunks if chunk["source"]["page"] == 947]
    checks.append(("six page-947 chunks", len(on_page) == 6
                   and all(chunk["division"] == "유지관리" for chunk in on_page)))
    excluded = misfiled_ids()
    checks.append(("two misfiled drafts", len(excluded) == 2
                   and {identifier.split("/")[2] for identifier in excluded} == {"2-1-30", "2-1-31"}
                   and excluded.isdisjoint(load_specs())))
    executable = json.loads((ROOT / "data/drafts/executable.json").read_text(encoding="utf-8"))
    checks.append(("executability excludes misfiled", excluded.isdisjoint(executable["executable"])
                   and all(row["id"] not in excluded for row in executable["failed"])
                   and executable["summary"]["total"] == 1056))
    index = VectorIndex()
    checks.append(("maintenance division enabled", "유지관리" in enabled_divisions()))
    checks.append(("enabled divisions have vectors", not index.missing and not index.stale
                   and len(index.chunks) == len(index.ids) == 4779))
    for name, ok in checks:
        print(f"{'PASS' if ok else 'FAIL'} {name}")
    print(f"통과 {sum(ok for _, ok in checks)} / 전체 {len(checks)}")
    return 0 if all(ok for _, ok in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
