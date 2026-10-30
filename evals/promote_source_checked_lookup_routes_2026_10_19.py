"""Promote only the four exact-table routes with completed PDF audits."""
from __future__ import annotations

import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "data/drafts/executable.json"
KEYS = {
    "2026-정오표1차/공통/1-4-3/작업지연",
    "2026-정오표1차/공통/1-4-4/지세_지형",
    "2026-정오표1차/토목/7-1-3/준설선선단조합",
    "2026-정오표1차/토목/3-2-4/장비조합",
    "2026-정오표1차/공통/6-2-1/적용범위",
    "2026-정오표1차/토목/7-1-2/예인선조합",
    "2026-정오표1차/공통/2-2-3/가설시설물_손율",
    "2026-정오표1차/토목/3-2-3/천공속도_및_소형터널기준",
    "2026-정오표1차/공통/1-2-3/체적환산계수",
    "2026-정오표1차/공통/4108-0060/콘크리트배치플랜트",
}
AUDITS = {
    "공통/1-4-3": "lookup-1-4-3-1-4-4-source-audit-2026-10-19.json",
    "공통/1-4-4": "lookup-1-4-3-1-4-4-source-audit-2026-10-19.json",
    "토목/7-1-3": "lookup-7-1-3-source-audit-2026-10-19.json",
    "토목/3-2-4": "lookup-3-2-4-source-audit-2026-10-19.json",
    "공통/6-2-1": "lookup-6-2-1-source-audit-2026-10-19.json",
    "토목/7-1-2": "lookup-7-1-2-source-audit-2026-10-19.json",
    "공통/2-2-3": "lookup-2-2-3-source-audit-2026-10-19.json",
    "토목/3-2-3": "lookup-3-2-3-source-audit-2026-10-19.json",
    "공통/1-2-3": "lookup-1-2-3-source-audit-2026-10-19.json",
    "공통/4108-0060": "lookup-4108-0060-cross-page-source-audit-2026-10-19.json",
}


def main() -> int:
    data = json.loads(INDEX.read_text(encoding="utf-8"))
    pending = KEYS - set(data["executable"])
    assert pending, "all configured source-checked routes are already promoted"
    failures = {row["id"]: row for row in data["failed"]}
    assert pending <= failures.keys(), pending - failures.keys()
    assert all(failures[key]["stage"] in {"calculator_execution_or_rule_gate", "source_preflight"}
               for key in pending)
    for name in set(AUDITS.values()):
        audit = json.loads((ROOT / "evals/runtime_validation" / name).read_text(encoding="utf-8"))
        assert audit.get("status") == "pass", (name, audit)
    backup = ROOT / "tmp/executable-before-exact-table-route-promotion-2026-10-19.json"
    if not backup.exists():
        shutil.copy2(INDEX, backup)
    data["failed"] = [row for row in data["failed"] if row["id"] not in pending]
    data["executable"] = sorted([*data["executable"], *pending])
    data["summary"]["executable"] = len(data["executable"])
    data["summary"]["failed"] = len(data["failed"])
    by_type = Counter()
    for path in (ROOT / "data/drafts/specs").rglob("*.json"):
        package = json.loads(path.read_text(encoding="utf-8"))
        if package["draft"]["id"] in data["executable"]:
            by_type[package.get("calc_type")] += 1
    for calc_type, count in by_type.items():
        if calc_type in data["summary"]["by_calc_type"]:
            data["summary"]["by_calc_type"][calc_type]["executable"] = count
    data["summary"]["failure_reasons_top10"] = [list(pair) for pair in
        Counter(str(row.get("reason", "")) for row in data["failed"]).most_common(10)]
    INDEX.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = {
        "promoted": sorted(pending), "source_audits": AUDITS,
        "reason": "Exact table routes and source values/citations independently checked; 1-4-3 open-ended floor increases and 3-2-4 custom combinations remain blocked; no combined adjustment policy inferred.",
        "previous_stage": "calculator_execution_or_rule_gate", "backup": str(backup.relative_to(ROOT)),
        "executable": len(data["executable"]), "failed": len(data["failed"]),
        "skipped": len(data["skipped"]), "index_sha256": hashlib.sha256(INDEX.read_bytes()).hexdigest(),
    }
    target = ROOT / "evals/runtime_validation/executable-exact-table-routes-promotion-2026-10-19.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
