"""Count 8-3-1 as executable only after its exact 5 m route and gate pass."""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IDENT = "2026-정오표1차/토목/8-3-1/굴절법탄성파탐사"


def main():
    audit_path = ROOT / "evals/runtime_validation/per-unit-8-3-1-citation-source-audit-2026-10-19.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit["status"] == "pass" and audit["source_cells"] == 6
    assert audit["runtime_exact_cell_citations"] == 6
    assert audit["non_source_interval"] == "blocked; adjustment factor unspecified"
    index_path = ROOT / "data/drafts/executable.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    if IDENT in index["executable"]:
        print("already executable")
        return
    failed = next(item for item in index["failed"] if item["id"] == IDENT)
    assert "receiver_interval=100" in failed["reason"]
    index["failed"] = [item for item in index["failed"] if item["id"] != IDENT]
    index["executable"] = sorted(set(index["executable"]) | {IDENT})
    index["summary"]["executable"] = len(index["executable"])
    index["summary"]["failed"] = len(index["failed"])
    index["summary"]["failure_reasons_top10"] = []
    from collections import Counter
    index["summary"]["failure_reasons_top10"] = [list(item) for item in
        Counter(str(row.get("reason", "")) for row in index["failed"]).most_common(10)]
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    out = ROOT / "evals/runtime_validation/executable-8-3-1-source-bounded-promotion-2026-10-19.json"
    out.write_text(json.dumps({
        "id": IDENT, "status": "executable",
        "reclassified_from_failure_reason": failed["reason"],
        "evidence": audit_path.relative_to(ROOT).as_posix(),
        "basis": "The original-source 5 m route returns six exact table cells, exact citations, and passes draft validation. A non-source 4 m interval is blocked. The stale 100 m synthetic query is out of scope and must not be treated as the standard executable case.",
        "full_rule_inventory_verified": False
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"id": IDENT, "executable": len(index["executable"]),
                      "failed": len(index["failed"]), "unsupported": index["summary"]["skipped_without_compatible_calculator"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
