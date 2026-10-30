"""Promote two exact source material-table routes after focused checks."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "data/drafts/executable.json"
AUDIT = ROOT / "evals/runtime_validation/per-unit-2-10-2-2-8-9-material-rates-audit-2026-10-19.json"
RECORD = ROOT / "evals/runtime_validation/executable-2-10-2-2-8-9-included-material-allowance-promotion-2026-10-19.json"
IDS = ["2026-정오표1차/공통/2-10-2/방진망설치및해체",
       "2026-정오표1차/공통/2-8-9/갱폼주위보호망설치및해체"]
audit = json.loads(AUDIT.read_text(encoding="utf-8"))
assert audit["status"] == "pass" and set(audit["sections"]) == {"2-10-2", "2-8-9"}
assert sum(item["independent_numeric_source_cells"] for item in audit["sections"].values()) == 3
index = json.loads(INDEX.read_text(encoding="utf-8"))
assert all(any(item.get("id") == ident for item in index["failed"]) for ident in IDS)
assert not (set(IDS) & set(index["executable"]))
previous = []
for ident in IDS:
    entry = next(item for item in index["failed"] if item.get("id") == ident)
    previous.append({"id": ident, "reason": entry["reason"]})
index["failed"] = [item for item in index["failed"] if item.get("id") not in IDS]
index["executable"] = sorted([*index["executable"], *IDS])
INDEX.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
RECORD.write_text(json.dumps({
    "previous_status": "failed", "current_status": "executable", "transitions": previous,
    "common_root_cause": "A note stating the source material amounts already include allowance was parsed as a numeric adjustment; this incorrectly blocked the labor calculation. Separate material-rate tables were not routed to the calculation output.",
    "source_verification": "Original physical p.59 and p.53 visually checked. Three exact material cells, units, and both note quotations were independently checked.",
    "runtime_change": "Recognize the narrowly declared included-material-allowance note only when its verbatim source quote and all linked additional_materials tables are present; emit cited table coefficients unchanged to avoid double application.",
    "focused_checks": ["10m2 and 25m2 routes for both sections; independent per-unit labor and material multiplication", "offline price path PARTIAL because material prices are unavailable locally", "draft validation pass", "check_per_unit.py 44/44", "check_adjustments.py 20/20"],
    "full_rule_verification": False,
    "remaining_limits": ["One-use material loss policy is retained in the source memo; reuse-cycle quantity planning and offline material prices are outside this focused check.", "Inventory-wide source-rule coverage remains incomplete."],
    "audit": str(AUDIT.relative_to(ROOT)),
}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"promoted": IDS, "failed_remaining": len(index["failed"]), "executable": len(index["executable"])}, ensure_ascii=False))
