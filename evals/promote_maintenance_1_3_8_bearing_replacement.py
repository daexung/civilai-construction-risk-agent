"""Promote maintenance 1-3-8 after its two-table source/rule audit passes."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
package_path = ROOT / "data/drafts/specs/유지관리/1-3-8.json"
package = json.loads(package_path.read_text(encoding="utf-8"))
ident = package["draft"]["id"]
index_path = ROOT / "data/drafts/executable.json"
data = json.loads(index_path.read_text(encoding="utf-8"))
if ident in data["executable"]:
    print("already promoted", ident)
else:
    candidate = next((item for item in data["skipped"] if item["id"] == ident), None)
    if candidate is None or candidate.get("stage") != "calculator_selection":
        raise SystemExit(f"unexpected saved status for {ident}: {candidate}")
    if package["calc_type"] != "daily_crew" or package["draft"]["quantity_model"]["name"] != "adjusted_daily_crew":
        raise SystemExit("calculator declaration missing")
    data["skipped"].remove(candidate)
    data["executable"].append(ident)
    index_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("promoted", ident)
