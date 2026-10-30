"""Promote common 8-2-18 after its saved source audit passes."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
ident = "2026-정오표1차/공통/8-2-18/시간당작업량"
audit_path = "evals/runtime_validation/common-8-2-18-source-formula-audit-2026-10-19.json"
audit = json.loads((ROOT / audit_path).read_text(encoding="utf-8"))
assert audit["status"] == "pass" and audit["validator_ok"] and audit["combinations_checked"] == 288
idx_path = ROOT / "data/drafts/executable.json"
idx = json.loads(idx_path.read_text(encoding="utf-8"))
before = {"executable": idx["summary"]["executable"], "failed": idx["summary"]["failed"],
          "unsupported": idx["summary"]["skipped_without_compatible_calculator"],
          "excluded": idx["summary"]["excluded_from_execution"]}
if ident not in idx["executable"]:
    assert not any(x["id"] == ident for x in idx["failed"])
    matches = [x for x in idx["skipped"] if x["id"] == ident]
    assert len(matches) == 1 and matches[0].get("stage") == "calculator_selection", matches
    idx["skipped"].remove(matches[0])
    idx["executable"].append(ident)
idx["executable"].sort()
idx_path.write_text(json.dumps(idx, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

unsupported_path = ROOT / "data/drafts/unsupported_classification.json"
unsupported = json.loads(unsupported_path.read_text(encoding="utf-8"))
unsupported["items"] = [x for x in unsupported["items"] if x.get("id") != ident]
unsupported["count"] = len(unsupported["items"])
unsupported_path.write_text(json.dumps(unsupported, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONPATH": str(ROOT)}
subprocess.run([sys.executable, "evals/refresh_saved_execution_summary.py"], check=True, env=env)
idx = json.loads(idx_path.read_text(encoding="utf-8"))
after = {"executable": idx["summary"]["executable"], "failed": idx["summary"]["failed"],
         "unsupported": idx["summary"]["skipped_without_compatible_calculator"],
         "excluded": idx["summary"]["excluded_from_execution"]}
assert after == {"executable": 890, "failed": 6, "unsupported": 160, "excluded": 2}
record = {"id": ident, "previous_counts": before, "current_counts": after,
          "evidence": audit_path, "source_cell_count": audit["independent_numeric_source_cells"],
          "case_count": audit["combinations_checked"],
          "promotion_basis": "original p250/p251 source cells and formula routes independently checked; scope exceptions fail closed"}
(ROOT / "evals/runtime_validation/executable-8-2-18-source-formula-promotion-2026-10-19.json").write_text(
    json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(record, ensure_ascii=False, indent=2))
