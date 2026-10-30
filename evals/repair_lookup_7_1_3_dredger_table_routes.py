"""Separate pump and grab dredger source-table axes with an exact selector."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "data/drafts/specs/토목/7-1-3.json"


def main() -> None:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    if not (ROOT / "tmp/7-1-3-spec-before-exact-dredger-route.json").exists():
        (ROOT / "tmp/7-1-3-spec-before-exact-dredger-route.json").write_bytes(SPEC.read_bytes())
    spec = package["draft"]
    selector = next(item for item in spec["inputs"] if item["name"] == "dredger_type")
    selector["source_table_map"] = {"펌프준설선": "p444-t0", "그래브 준설선": "p444-t1"}
    pump = next(item for item in spec["inputs"] if item["name"] == "pump_dredger_spec")
    pump["allowed_values"] = ["4,476∼8,952" if value == "4,476~8,952" else value
                               for value in pump["allowed_values"]]
    pump.setdefault("synonyms", {})["4,476∼8,952"] = ["4,476~8,952"]
    for name, selected in (("pump_dredger_spec", "펌프준설선"), ("grab_dredger_spec", "그래브 준설선")):
        field = next(item for item in spec["inputs"] if item["name"] == name)
        field["when"] = {"input": "dredger_type", "equals": selected}
    SPEC.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("added exact p444-t0/p444-t1 routing and conditional spec fields")


if __name__ == "__main__":
    main()
