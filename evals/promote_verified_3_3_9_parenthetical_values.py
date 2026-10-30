"""Promote 3-3-9 after exact source-parenthetical interpretation checks."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ID = "2026-정오표1차/공통/3-3-9/수중발파"
REASON = "기본 조합 unresolvable: p130-t0: 행 '고정 행이름', 열 '우물통발파' — 셀 값 파싱 실패"
INDEX = ROOT / "data/drafts/executable.json"
AUDIT = ROOT / "evals/runtime_validation/per-unit-3-3-9-parenthetical-values-2026-10-19.json"
RECORD = ROOT / "evals/runtime_validation/executable-3-3-9-parenthetical-promotion-2026-10-19.json"

a = json.loads(AUDIT.read_text(encoding="utf8"))
assert a["status"] == "parenthetical_source_values_and_routes_verified"
assert a["source"]["unique_cells_checked"] == 18
assert a["runtime"]["exact_blast_method_routes"] == 4 and a["runtime"]["execution_preflight_combinations"] == 16
i = json.loads(INDEX.read_text(encoding="utf8"))
assert ID not in i["executable"]
f = [x for x in i["failed"] if x.get("id") == ID]
assert len(f) == 1 and f[0].get("reason") == REASON, f
i["failed"] = [x for x in i["failed"] if x.get("id") != ID]
i["executable"] = sorted([*i["executable"], ID])
s = i["summary"]
s["executable"], s["failed"] = len(i["executable"]), len(i["failed"])
s["by_calc_type"]["per_unit"]["executable"] += 1
s["by_scope"]["기타"]["executable"] += 1
s["failure_reasons_top10"] = [[r, n - 1 if r == REASON else n]
                               for r, n in s["failure_reasons_top10"] if r != REASON or n > 1]
INDEX.write_text(json.dumps(i, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
record = {"id": ID, "previous_status": "failed", "current_status": "executable",
          "previous_failure_reason": REASON, "verification": str(AUDIT.relative_to(ROOT)),
          "scope": "18 original cells visually checked on p.74; four exact blast/method routes; 16 preflight combinations, of which 12 remain blocked by unresolved source depth policies.",
          "runtime_changes": ["opt-in parenthetical source-value selection", "opt-in source labor unit preservation"],
          "previously_passing_results_affected": 0,
          "current_counts": {"executable": len(i["executable"]), "failed": len(i["failed"]),
                             "unsupported": s["skipped_without_compatible_calculator"], "excluded": s["excluded_from_execution"]},
          "full_rule_verification": False}
RECORD.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
print(json.dumps(record["current_counts"], ensure_ascii=True))
