"""Reconcile two focused source-backed formula promotions without replaying inventory."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
baseline = json.loads((ROOT / "tmp/executable-before-row-source-promotions-2026-10-19.json").read_text(encoding="utf-8"))
current = json.loads((ROOT / "data/drafts/executable.json").read_text(encoding="utf-8"))
base_exec, now_exec = set(baseline["executable"]), set(current["executable"])
base_fail = {item["id"]: item for item in baseline["failed"]}
now_fail = {item["id"]: item for item in current["failed"]}
base_skip = {item["id"]: item for item in baseline["skipped"]}
now_skip = {item["id"]: item for item in current["skipped"]}
promoted = ["2026-정오표1차/공통/3-2-3/흙깎기_기계",
            "2026-정오표1차/공통/3-2-4/터파기(기계)"]
for ident in promoted:
    assert ident in base_skip and ident in now_exec
    assert ident not in now_fail and ident not in now_skip
assert not (base_exec & set(now_fail))
assert not (now_exec & set(now_fail) or now_exec & set(now_skip) or set(now_fail) & set(now_skip))

path = ROOT / "evals/runtime_validation/execution-id-and-evidence-scope-reconciliation-2026-10-19.json"
report = json.loads(path.read_text(encoding="utf-8"))
report["current_counts"] = {"executable": len(now_exec), "failed": len(now_fail),
                            "unsupported": current["summary"]["skipped_without_compatible_calculator"],
                            "excluded": current["summary"]["excluded_from_execution"]}
delta = report["id_status_delta"]
failed_to_exec = sorted(set(base_fail) & now_exec)
exec_to_failed = sorted(base_exec & set(now_fail))
unsupported_to_exec = sorted(set(base_skip) & now_exec)
assert promoted[0] in unsupported_to_exec and promoted[1] in unsupported_to_exec
delta["same_id_fail_to_executable"] = len(failed_to_exec)
delta["same_id_executable_to_fail"] = len(exec_to_failed)
delta["same_id_unsupported_to_executable"] = len(unsupported_to_exec)
delta["unsupported_to_executable_ids"] = [
    {"id": ident, "baseline": "unsupported",
     "baseline_reason": base_skip[ident].get("reason"), "current": "executable",
     "evidence_artifacts": ["execution-id-and-evidence-scope-reconciliation-2026-10-19.json",
                            "common-excavation-formula-promotion-2026-10-19.json",
                            "common-3-2-3-source-formula-audit-2026-10-19.json" if ident.endswith("3-2-3/흙깎기_기계") else
                            "common-3-2-4-source-formula-audit-2026-10-19.json"]}
    for ident in unsupported_to_exec]
delta["net_pass_delta"] = len(now_exec) - len(base_exec)
delta["net_fail_delta"] = len(now_fail) - len(base_fail)
delta["unchanged_unsupported"] = len(set(base_skip) & set(now_skip))
delta["unchanged_excluded"] = len(set(baseline.get("excluded", [])) & set(current.get("excluded", []))) if "excluded" in baseline else current["summary"]["excluded_from_execution"]

coverage = report["source_coverage_scope"]
coverage["recent_independent_cell_audit"] += (
    " Common 3-2-3 added 14 independent numeric cells from printed pp.68-69 (physical PDF pp.124-125); "
    "common 3-2-4 added 14 from pp.69-70 (physical pp.125-126), including one p126-t0 equipment row restored from visual source due to merged-cell extraction loss. "
    "Coverage now 103 sections / 3923 numeric source cells. Each route audit separately reports cell-link count and rule gates; governing notes remain outside cell totals."
)
coverage["relation"] = ("Broad source-derived checks remain 89 sections / 303 cases with unknown overlap. "
                        "Independent numeric source-cell audits are 103 sections / 3923 cells, including prior 17/555; "
                        "the two counts are nonadditive. Original pages pp.68-70 were independently checked for the latest two sections. "
                        "Policy/cost rules and unresolved combinations are tracked separately. Inventory-wide full-rule verification remains 0; denominator unknown.")

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

spec_root = ROOT / "data/drafts/specs"
manifest_entries = [p.relative_to(spec_root).as_posix().encode() + b"\0" + sha(p).encode()
                    for p in sorted(spec_root.rglob("*.json"))]
manifest = hashlib.sha256(b"\n".join(manifest_entries)).hexdigest()
runtime = report["current_runtime_hashes"]
runtime["formula_sha256"] = sha(ROOT / "backend/agent/tools/calc/formula.py")
runtime["chunks_sha256"] = sha(ROOT / "data/processed/chunks.all.jsonl")
runtime["executable_index_sha256"] = sha(ROOT / "data/drafts/executable.json")
report["artifacts"]["current_spec_manifest_sha256"] = manifest
report["artifacts"]["focused_incremental_scope"] += (
    "; common 3-2-3/3-2-4 promoted from unsupported after 28 numeric source cells, 62 route/combination cases, "
    "exact citations and validator checks; formula table-divisor rate-multiplier and conditional-input branches focused-rechecked; no whole inventory replay"
)
impact = report["common_executor_impact"]
impact["focused_current_regression"] += (
    "; common 3-2-3 14 source cells/14 scenarios, 18 cell-linked outputs, compute node passed; "
    "common 3-2-4 14 source cells/48 combinations (34 computed/14 source-policy blocked), compute node passed; "
    "3-10-1 existing table_divisor smoke passed after opt-in rate_multiplier addition; check_steel_formula passed"
)
impact["validity"] += (
    " Formula runtime's new conditional-input and table-divisor rate_multiplier branches are opt-in; "
    "the two declarations are used by newly promoted baseline-unsupported 3-2-3/3-2-4. Existing 3-10-1 table_divisor was focused rechecked. "
    "These are basic quantity routes; equipment cost bases, open source combinations and all-rule inventory coverage remain incomplete."
)
report["current_counts"] = report["current_counts"]
path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"baseline": report["baseline_counts"], "current": report["current_counts"],
                  "fail_to_executable": len(failed_to_exec),
                  "unsupported_to_executable": len(unsupported_to_exec),
                  "unchanged_unsupported": delta["unchanged_unsupported"],
                  "source_coverage": "103 sections / 3923 cells; broad 89/303 separate",
                  "spec_manifest_sha256": manifest}, ensure_ascii=False, indent=2))
