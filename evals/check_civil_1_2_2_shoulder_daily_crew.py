"""Independent source and calculation audit for civil 1-2-2 shoulder spreading."""
from __future__ import annotations
import json
from fractions import Fraction
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.daily_crew import adjusted_daily_crew
from backend.agent.nodes.compute import compute
from backend.agent.rules.specs import load_specs
from pipeline.validate_drafts import load_chunks, validate_one

SPEC_PATH = ROOT / "data/drafts/specs/토목/1-2-2.json"
AUDIT_PATH = ROOT / "evals/runtime_validation/civil-1-2-2-shoulder-source-audit-2026-10-19.json"
PKG = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
SPEC = PKG["draft"]
EXPECTED = {
    "포설공": {"단위": "인", "수량": "2"},
    "보통인부": {"단위": "인", "수량": "2"},
    "굴착기": {"규격": "1.0㎥", "단위": "대", "수량": "1"},
    "진동롤러": {"규격": "12ton", "단위": "대", "수량": "1"},
    "살수차": {"규격": "16,000ℓ", "단위": "대", "수량": "0.5"},
    "시공량": {"시공량(㎥)": "250"},
    "비고": {"순수 인력 살수 추가 인원": "100㎡당 1인"},
}
TABLE = next(t for t in SPEC["tables"] if t["id"] == "p364-t0")
assert TABLE["values"] == EXPECTED, TABLE["values"]
assert len(PKG["citations"]) == 6
for cite in PKG["citations"]:
    assert cite["table_id"] == "p364-t0"
    assert cite["value"] == EXPECTED[cite["row"]][cite["column"]]
routes = 0
for volume in (125, 250, 625):
    result = adjusted_daily_crew(SPEC, {"volume": str(volume), "manual_watering": False})
    assert result["status"] == "computed", result
    days = Fraction(volume, 250)
    assert Fraction(result["work_days"]) == days
    assert {k: Fraction(v) for k, v in result["person_days"].items()} == {"포설공": 2 * days, "보통인부": 2 * days}
    assert {k: Fraction(v) for k, v in result["equipment_days"].items()} == {"굴착기 1.0㎥": days, "진동롤러 12ton": days, "살수차 16,000ℓ": days / 2}
    routes += 1
blocked = adjusted_daily_crew(SPEC, {"volume": "250", "manual_watering": True})
assert blocked["status"] == "blocked", blocked
chunks = load_chunks(ROOT / "data/processed/chunks.all.jsonl")
validation = validate_one(SPEC_PATH, ROOT / "data/drafts/specs", chunks, None)
assert validation["ok"], validation
node_status = "not_registered_in_active_execution_index"
if SPEC["id"] in load_specs():
    node = compute({"spec_id": SPEC["id"], "inputs": {"volume": "250", "manual_watering": False}})
    assert node["status"] == "COMPUTED", node
    node_status = node["status"]
audit = {
    "id": SPEC["id"], "status": "pass", "source_numeric_cells_independently_checked": 6,
    "source_table_reconstructed": EXPECTED,
    "source_page": {"physical_pdf": 364, "printed": 308, "render": "evals/runtime_validation/source-followup-physical-364.png"},
    "computed_routes": routes, "blocked_policy_routes": 1,
    "independent_expected": "work_days=volume/250; both labor counts=2*work_days; excavator and roller=work_days; water truck=0.5*work_days",
    "verified_rules": ["table work crew and output", "manual watering add-on is not applied because source denominator is area and trade is unspecified", "section notes on scope retained separately"],
    "full_rule_verification": False, "validator_ok": validation["ok"], "calculation_node": node_status,
}
AUDIT_PATH.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(audit, ensure_ascii=False, indent=2))
