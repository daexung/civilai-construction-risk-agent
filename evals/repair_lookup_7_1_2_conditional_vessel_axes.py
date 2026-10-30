"""Ask only the capacity/specification axis for the selected towed vessel."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "data/drafts/specs/토목/7-1-2.json"


def main() -> None:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    if not (ROOT / "tmp/7-1-2-spec-before-conditional-vessel-axes.json").exists():
        (ROOT / "tmp/7-1-2-spec-before-conditional-vessel-axes.json").write_bytes(SPEC.read_bytes())
    spec = package["draft"]
    for name, selected in (("pump_dredger_power", "펌프준설선"),
                           ("grab_dredger_power", "그래브준설선"),
                           ("barge_capacity", "토운선")):
        field = next(item for item in spec["inputs"] if item["name"] == name)
        field["when"] = {"input": "towed_vessel_type", "equals": selected}
    SPEC.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("capacity/spec axes now follow the exact vessel category; source table unchanged")


if __name__ == "__main__":
    main()
