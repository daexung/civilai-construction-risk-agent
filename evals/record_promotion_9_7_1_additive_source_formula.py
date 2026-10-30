"""Promote 9-7-1's source-backed additive survey coefficients."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ID = "2026-정오표1차/토목/9-7-1/신규등록측량(도해)"
INDEX = ROOT / "data/drafts/executable.json"
AUDIT = ROOT / "evals/runtime_validation/per-unit-9-7-1-additive-survey-coefficients-audit-2026-10-19.json"
RECORD = ROOT / "evals/runtime_validation/executable-9-7-1-additive-survey-coefficients-promotion-2026-10-19.json"
audit = json.loads(AUDIT.read_text(encoding="utf-8"))
assert audit["status"] == "pass" and audit["independent_numeric_source_cells"] == 12
assert audit["exact_coefficient_routes"] == 32 and audit["draft_validation"] == "pass"
index = json.loads(INDEX.read_text(encoding="utf-8"))
failure = next(item for item in index["failed"] if item.get("id") == ID)
index["failed"] = [item for item in index["failed"] if item.get("id") != ID]
index["executable"] = sorted([*index["executable"], ID])
INDEX.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
RECORD.write_text(json.dumps({
    "id": ID, "previous_status": "failed", "current_status": "executable",
    "previous_reason": failure["reason"],
    "root_cause": "The calculation-example rule was retained only as a free-text note, so the adjustment layer blocked execution despite an existing exact additive_deltas coefficient engine.",
    "source_evidence": "Original physical p.581/582 (printed 525/526) visually checked. Twelve source numeric coefficient/rate cells, the explicit n formula, and the additive worked example were independently checked.",
    "runtime_change": "Optional coefficient_combination_cite attaches the exact source arithmetic example to every computed coefficient route; no default calculation changed.",
    "focused_checks": ["32 exact routes across land type, region, and 0/1/2/4 area increments", "Worked example: 7,000m2 land / 구지역 yields coefficient 2.00 and labor totals 1.12/1.30/0.60 per parcel", "two-parcel offline pricing", "per_unit regression 44/44", "draft validation pass"],
    "full_rule_verification": False,
    "remaining_limits": ["Machine expenses, consumables, control-point installation, boat hire, and travel are source-directed separate items and remain unpriced."],
    "audit": str(AUDIT.relative_to(ROOT)),
}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"promoted": ID, "previous_reason": failure["reason"]}, ensure_ascii=False))
