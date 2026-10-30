"""Promote only source-audited common machine excavation formula routes."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
targets = {
    "2026-정오표1차/공통/3-2-4/터파기(기계)":
        "evals/runtime_validation/common-3-2-4-source-formula-audit-2026-10-19.json",
}
for ident, audit_path in targets.items():
    audit = json.loads((ROOT / audit_path).read_text(encoding="utf-8"))
    assert audit["status"] == "pass" and audit["validator_ok"]
index_path = ROOT / "data/drafts/executable.json"
index = json.loads(index_path.read_text(encoding="utf-8"))
before = {key: index["summary"][key] for key in
          ("executable", "failed", "skipped_without_compatible_calculator", "excluded_from_execution")}
newly_promoted = []
for ident in targets:
    if ident in index["executable"]:
        continue
    assert not any(item["id"] == ident for item in index["failed"])
    matches = [item for item in index["skipped"] if item["id"] == ident]
    assert len(matches) == 1 and matches[0].get("stage") == "calculator_selection", matches
    index["skipped"].remove(matches[0])
    index["executable"].append(ident)
    newly_promoted.append(ident)
index["executable"].sort()
index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

classification_path = ROOT / "data/drafts/unsupported_classification.json"
classification = json.loads(classification_path.read_text(encoding="utf-8"))
for ident in targets:
    classification["items"] = [item for item in classification["items"] if item.get("id") != ident]
classification["count"] = len(classification["items"])
classification_path.write_text(json.dumps(classification, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONPATH": str(ROOT)}
subprocess.run([sys.executable, "evals/refresh_saved_execution_summary.py"], check=True, env=env)
index = json.loads(index_path.read_text(encoding="utf-8"))
after = {"executable": index["summary"]["executable"], "failed": index["summary"]["failed"],
         "unsupported": index["summary"]["skipped_without_compatible_calculator"],
         "excluded": index["summary"]["excluded_from_execution"]}
assert after == {"executable": before["executable"] + len(newly_promoted), "failed": before["failed"],
                 "unsupported": before["skipped_without_compatible_calculator"] - len(newly_promoted),
                 "excluded": before["excluded_from_execution"]}, (before, after)
assert after == {"executable": 889, "failed": 6, "unsupported": 161, "excluded": 2}
record = {"promoted_ids": ["2026-정오표1차/공통/3-2-3/흙깎기_기계", *targets],
          "checkpoint_counts_before_both": {"executable": 887, "failed": 6, "unsupported": 163, "excluded": 2},
          "counts_before_3_2_4": {"executable": 888, "failed": 6, "unsupported": 162, "excluded": 2},
          "current_counts": after,
          "evidence": list(targets.values()) +
                      ["evals/runtime_validation/common-3-2-3-source-formula-audit-2026-10-19.json"],
          "promotion_basis": "original source page cell audits, exact formula combinations, citation/validator checks and compute-node pass; no ambiguous policy/cost basis was defaulted"}
out = ROOT / "evals/runtime_validation/common-excavation-formula-promotion-2026-10-19.json"
out.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(record, ensure_ascii=False, indent=2))
