"""Promote source-backed 1-6-5 assembly/dismantling routes."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ID = "2026-정오표1차/토목/1-6-5/기계포설장비조립및해체"
INDEX = ROOT / "data/drafts/executable.json"
AUDIT = ROOT / "evals/runtime_validation/per-unit-1-6-5-condition-workday-audit-2026-10-19.json"
RECORD = ROOT / "evals/runtime_validation/executable-1-6-5-condition-workday-promotion-2026-10-19.json"
audit = json.loads(AUDIT.read_text(encoding="utf-8"))
assert audit["status"] == "pass" and audit["independent_source_cells"] == 20
assert len(audit["routes"]) == 4
index = json.loads(INDEX.read_text(encoding="utf-8"))
failure = next(item for item in index["failed"] if item.get("id") == ID)
index["failed"] = [item for item in index["failed"] if item.get("id") != ID]
index["executable"] = sorted([*index["executable"], ID])
INDEX.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
RECORD.write_text(json.dumps({
    "id": ID, "previous_status": "failed", "current_status": "executable",
    "previous_reason": failure["reason"],
    "root_cause": "The source table mixes resource amount, workday count, and equipment unit rows under one compound axis; the generic rate reader could not parse its composite denominator or multiply labor amount by the selected exact day cell.",
    "source_evidence": "Original physical p.373/printed p.317 visually checked. Twenty distinct original numeric cells across two conditions, three labor trades, crane quantities, and assembly/dismantling days independently compared.",
    "runtime_changes": ["source_component_multipliers_by_trade multiplies each selected labor source amount by its exact workday cell and cites both source cells", "per-row source denominator mapping uses 1 event, while original trade-specific resource units remain in output"],
    "focused_checks": ["4 condition × work-type routes and 28 cell-level checks", "2-event offline labor pricing; equipment cost rule equals labor subtotal × 3%", "check_per_unit.py 44/44", "check_adjustments.py 20/20", "draft validation pass"],
    "full_rule_verification": False,
    "remaining_limits": ["Crane size and equipment rental price depend on job-site conditions and remain unpriced, as the source directs.", "Overall source-rule denominator is unknown."],
    "audit": str(AUDIT.relative_to(ROOT)),
}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"promoted": ID, "previous_reason": failure["reason"]}, ensure_ascii=False))
