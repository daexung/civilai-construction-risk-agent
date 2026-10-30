"""Promote 13-6-17 after independent source-cell and rule verification."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ID = "2026-정오표1차/기계설비/13-6-17/Tainter_Gate_Anchorage_제관"
INDEX = ROOT / "data/drafts/executable.json"
AUDIT = ROOT / "evals/runtime_validation/per-unit-13-6-17-inspection-share-audit-2026-10-19.json"
RECORD = ROOT / "evals/runtime_validation/executable-13-6-17-source-rates-promotion-2026-10-19.json"

audit = json.loads(AUDIT.read_text(encoding="utf-8"))
assert audit["status"] == "pass" and audit["independently_checked_numeric_source_cells"] == 25
assert audit["source_percentage_rule_checks"] == 1 and audit["draft_validation"] == "pass"
index = json.loads(INDEX.read_text(encoding="utf-8"))
assert ID not in index["executable"]
matches = [item for item in index["skipped"] if item.get("id") == ID]
assert len(matches) == 1, matches
index["skipped"] = [item for item in index["skipped"] if item.get("id") != ID]
index["executable"] = sorted([*index["executable"], ID])
index["summary"]["skipped_without_compatible_calculator"] -= 1
index["summary"]["by_calc_type"]["per_unit"]["attempted"] += 1
index["summary"]["by_calc_type"]["per_unit"]["executable"] += 1
index["summary"]["by_scope"]["기타"]["attempted"] += 1
index["summary"]["by_scope"]["기타"]["executable"] += 1
index["summary"]["executable"] = len(index["executable"])
index["summary"]["skipped_misfiled"] = sum(x.get("stage") == "misfiled" for x in index["skipped"])
index["summary"]["skipped_without_compatible_calculator"] = sum(
    x.get("calc_type") == "not_calculable" for x in index["skipped"]
)
index["summary"]["total"] = len(index["executable"]) + len(index["failed"]) + sum(
    x.get("calc_type") == "not_calculable" for x in index["skipped"]
)
INDEX.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
counts = {"executable": len(index["executable"]), "failed": len(index["failed"]),
          "unsupported": index["summary"]["skipped_without_compatible_calculator"],
          "excluded": index["summary"]["excluded_from_execution"]}
RECORD.write_text(json.dumps({
    "id": ID, "previous_status": "unsupported", "current_status": "executable",
    "root_cause": "The exact source had repeated process labels; dictionary row keys overwrote earlier exact rate cells and caused the runtime to reuse later values.",
    "verification": str(AUDIT.relative_to(ROOT)),
    "source_evidence": "Original physical p.878/printed p.822 visually checked; 25 numeric cells and a distinct 7% labor rule independently compared.",
    "runtime_changes": ["Repeated source rows keyed by exact ordinal where needed", "Separate inspection labor line computed as 7% of all 25 exact labor rates"],
    "focused_regressions": ["One and three ton routes; each rate and separate 7% share compared to independent arithmetic", "per_unit 44/44", "adjustments 20/20", "offline pricing PARTIAL", "draft validation pass"],
    "full_rule_verification": False,
    "remaining_limits": ["Consumables and D/M heavy-oil basis remain unresolved and excluded from calculation.", "Inventory-wide full-rule verification remains incomplete."],
    "counts_after_promotion": counts,
}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(counts, ensure_ascii=False))
