"""Record the focused 8-1-3 promotion and latest incremental evidence."""
import collections
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def read(path):
    return json.loads(path.read_text(encoding="utf-8"))

def write(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

idx_path = ROOT / "data/drafts/executable.json"
idx = read(idx_path)
counts = {"executable": len(idx["executable"]), "failed": len(idx["failed"]),
          "unsupported": idx["summary"]["skipped_without_compatible_calculator"],
          "excluded": idx["summary"]["excluded_from_execution"],
          "failure_stages": dict(collections.Counter(x.get("stage", "unknown") for x in idx["failed"]))}
checkpoint_path = ROOT / "evals/runtime_validation/incremental-source-citation-checkpoint-2026-10-19.json"
cp = read(checkpoint_path)
cp["previous_active_lists"] = cp["current_active_lists"]
cp["current_active_lists"] = counts
promoted = "2026-정오표1차/토목/8-1-3/천공(암반층)"
if promoted not in cp["promoted"]:
    cp["promoted"].append(promoted)
cp["source_checks"]["토목/8-1-3"] = "Printed pp.397-398 visually checked: 70 distinct source cells (40 labor + 30 merged BX/NX material cells), ten exact rock/hole routes; 80 preflight combinations computed and 200 blocked by source-grounded policies. Depth>20m 5% rate and inclined drilling remain unresolved; over-water cost is separately accounted."
cp["source_checks"]["기계설비/6-1-1"] = "Printed p.679 visually checked: 28 cells including eight explicit protection dashes, fourteen exact size/item routes, and 56 runner-preflight combinations; source dashes exclude only inapplicable protection labor resources."
cp["source_evidence_added_this_continuation"]["sections"] += 1
cp["source_evidence_added_this_continuation"]["cells"] += 70
cp["source_evidence_added_this_continuation"]["breakdown"]["토목/8-1-3 transposed continuation"] = 70
cp["source_evidence_added_this_continuation"]["sections"] += 1
cp["source_evidence_added_this_continuation"]["cells"] += 28
cp["source_evidence_added_this_continuation"]["breakdown"]["기계설비/6-1-1 sparse source dashes"] = 28
promoted_6_1_1 = "2026-정오표1차/기계설비/6-1-1/유량계(직독식)설치"
if promoted_6_1_1 not in cp["promoted"]:
    cp["promoted"].append(promoted_6_1_1)
cp["validation"]["all_rule_verification"] = 0
cp["validation"]["full_replay"] = False
cp["validation"]["runtime_change_impact"] = "The opt-in additional_unit_rates exact selector and daily_crew exact_component_inputs are declared only in failed-at-baseline 토목/8-1-3. Baseline 692 executable IDs had no such opt-ins. check_per_unit.py passed 44/44; existing 6-2-3, 6-3-3, and 8-1-2 source-route checkers were rerun after the shared selector edit."
cp["validation"]["per_unit_runtime_impact_rechecked"] = sorted(set(cp["validation"].get("per_unit_runtime_impact_rechecked", [])) | {"토목/8-1-3"})
cp["remaining_failures"]["calculator_or_rule_gate"] = counts["failure_stages"].get("calculator_execution_or_rule_gate", 0)
cp["remaining_failures"]["source_preflight"] = counts["failure_stages"].get("source_preflight", 0)
cp["current_hashes"].update({"spec_8_1_3": sha(ROOT / "data/drafts/specs/토목/8-1-3.json"),
                             "spec_6_1_1": sha(next(p for p in (ROOT / "data/drafts/specs").rglob("*.json") if (lambda d: d.get("division") == "기계설비" and d.get("section_no") == "6-1-1")(read(p)["draft"]))),
                             "per_unit.py": sha(ROOT / "backend/agent/tools/calc/per_unit.py"),
                             "daily_crew.py": sha(ROOT / "backend/agent/tools/calc/daily_crew.py"),
                             "executable.json": sha(idx_path)})
write(checkpoint_path, cp)

for filename in ("incremental-table-root-cause-checkpoint-2026-10-19.json",):
    p = ROOT / "evals/runtime_validation" / filename
    d = read(p)
    d["previous"] = d.get("current", {})
    d["current"] = {k: counts[k] for k in ("executable", "failed", "unsupported", "excluded", "failure_stages")}
    roots = read(ROOT / "evals/runtime_validation/active-table-link-root-causes-2026-10-19.json")
    d["table_link_failure_queue_after"] = roots["table_link_candidate_count"]
    d["other_table_diagnostics_after"] = roots["other_table_lookup_diagnostics_count"]
    d["root_cause_diagnostics"] = {"link_classes": roots["table_link_classes"], "root_cause_groups": roots["root_cause_group_counts"]}
    d["source_evidence"]["new_independent_pdf_cells"] = 836
    d["source_evidence"]["new_source_sections"] = 23
    d["source_evidence"]["added_after_543_checkpoint"]["cells"] = 140
    d["source_evidence"]["added_after_543_checkpoint"]["sections"] = 5
    d["source_evidence"]["added_after_543_checkpoint"]["breakdown"]["토목/8-1-3"] = 70
    d["source_evidence"]["added_after_543_checkpoint"]["breakdown"]["기계설비/6-1-1"] = 28
    specroot = ROOT / "data/drafts/specs"
    entries = [p.relative_to(specroot).as_posix().encode() + b"\0" + sha(p).encode() for p in sorted(specroot.rglob("*.json"))]
    d["hashes"].update({"spec_count": len(entries), "spec_manifest_sha256": hashlib.sha256(b"\n".join(entries)).hexdigest(),
                        "executable_sha256": sha(idx_path), "runtime_per_unit_sha256": sha(ROOT / "backend/agent/tools/calc/per_unit.py"),
                        "runtime_daily_crew_sha256": sha(ROOT / "backend/agent/tools/calc/daily_crew.py"),
                        "validator_sha256": sha(ROOT / "pipeline/validate_drafts.py")})
    write(p, d)

print(json.dumps({"current": counts, "promoted": [promoted, promoted_6_1_1], "source_cell_total": "23 sections / 836 cells; includes earlier 17/555", "all_rule_verification": 0}, ensure_ascii=True))
