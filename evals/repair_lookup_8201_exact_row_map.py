"""Declare the exact source equipment row for catalogue item 8201-0100."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "data/drafts/specs/공통/8201-0100.json"
BACKUP = ROOT / "tmp/8201-0100-spec-before-exact-row-map.json"


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    field = next(item for item in package["draft"]["inputs"] if item["name"] == "equipment_code")
    assert field["allowed_values"] == ["8205-0100"]
    assert package["draft"]["tables"][0]["values"].keys() == {"8205-0100"}
    shutil.copy2(SPEC, BACKUP)
    field["machine_codes"] = {"8205-0100": "8205-0100"}
    SPEC.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = {"change": "explicit exact equipment_code -> full source row key",
              "catalogue_id": "8201-0100", "source_row": "8205-0100",
              "source": "PDF p.270 / p326-t0; one visible row, ten value columns",
              "backup": str(BACKUP.relative_to(ROOT)),
              "spec_sha256": hashlib.sha256(SPEC.read_bytes()).hexdigest()}
    out = ROOT / "evals/runtime_validation/repair-8201-exact-row-map-2026-10-19.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
