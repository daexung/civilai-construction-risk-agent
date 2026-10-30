"""Promote 1-1-3 after fixing its invalid generic source-axis sample."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ID = "2026-정오표1차/건축/1-1-3/기본용접공수"
INDEX = ROOT / "data/drafts/executable.json"
AUDIT = ROOT / "evals/runtime_validation/per-unit-1-1-3-source-axis-factor-audit-2026-10-19.json"
RECORD = ROOT / "evals/runtime_validation/executable-1-1-3-source-axis-promotion-2026-10-19.json"
audit = json.loads(AUDIT.read_text(encoding="utf-8"))
assert audit["status"] == "pass" and audit["independently_checked_factor_cells"] == 46
assert audit["exact_factor_routes"] == 92 and audit["source_valid_input_sample"] == ["5"]
index = json.loads(INDEX.read_text(encoding="utf-8"))
failure = next(item for item in index["failed"] if item.get("id") == ID)
index["failed"] = [item for item in index["failed"] if item.get("id") != ID]
index["executable"] = sorted([*index["executable"], ID])
INDEX.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
RECORD.write_text(json.dumps({
    "id": ID, "previous_status": "failed", "current_status": "executable",
    "previous_reason": failure["reason"],
    "root_cause": "The generic positive-rational evaluator sample 100 was outside the thickness coefficient table's source domain; this was a false failure for valid source-supported inputs.",
    "source_evidence": "Physical PDF pages 625/626 (printed 569/570) visually checked; all 46 conversion-factor cells and 20 base labor thresholds compared to independent transcription.",
    "evaluator_change": "Numeric inputs explicitly used as a calculated selector's factor-table column now receive a valid value sampled from that exact declared source axis. This affects one saved spec ID; runtime still rejects values absent from source tables.",
    "focused_checks": ["46 factor cells × two member types = 92 exact route/rate/citation checks", "draft validation pass", "out-of-domain rejection retained"],
    "full_rule_verification": False,
    "remaining_limits": ["Other specification notes and offline wage prices are not included in the 46-cell factor audit."],
    "audit": str(AUDIT.relative_to(ROOT)),
}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"promoted": ID, "previous_reason": failure["reason"]}, ensure_ascii=False))
