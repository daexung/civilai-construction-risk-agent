"""검사를 통과한 미지원 ID를 executable 인덱스로 옮기고 저장 집계를 갱신한다(재계산 없음).

사용: python evals/promote_ids_to_executable.py <id> [<id>...]
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
idx_path = ROOT / "data/drafts/executable.json"
idx = json.loads(idx_path.read_text(encoding="utf-8"))
for ident in sys.argv[1:]:
    if ident in idx["executable"]:
        continue
    assert not any(x["id"] == ident for x in idx["failed"])
    match = [x for x in idx["skipped"] if x["id"] == ident]
    assert len(match) == 1 and match[0].get("stage") == "calculator_selection", (ident, match)
    idx["skipped"].remove(match[0])
    idx["executable"].append(ident)
idx["executable"].sort()
idx_path.write_text(json.dumps(idx, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
cls_path = ROOT / "data/drafts/unsupported_classification.json"
cls = json.loads(cls_path.read_text(encoding="utf-8"))
cls["items"] = [x for x in cls["items"] if x.get("id") not in sys.argv[1:]]
cls["count"] = len(cls["items"])
cls_path.write_text(json.dumps(cls, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONPATH": str(ROOT)}
subprocess.run([sys.executable, "evals/refresh_saved_execution_summary.py"], check=True, env=env)
s = json.loads(idx_path.read_text(encoding="utf-8"))["summary"]
print({k: s[k] for k in ("executable", "failed", "skipped_without_compatible_calculator", "excluded_from_execution")})
