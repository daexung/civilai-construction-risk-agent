"""Declare source-signed percentages as changes to the base daily output."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = [
    ("공통", "2-6-1", "p101-t2"),
    ("유지관리", "1-2-11", "p919-t1"),
]
CHUNKS = ROOT / "data/processed/chunks.all.jsonl"
CHUNKS_BACKUP = ROOT / "tmp/chunks-before-lawn-mowing-cost-row-repair.jsonl"


def main() -> int:
    edits = []
    for division, section, table_id in TARGETS:
        path = ROOT / "data/drafts/specs" / division / f"{section}.json"
        backup = ROOT / "tmp" / f"spec-before-signed-output-rate-{division}-{section}.json"
        if not backup.exists():
            shutil.copy2(path, backup)
        package = json.loads(path.read_text(encoding="utf-8"))
        spec = package["draft"]
        matches = [item for item in spec["quantity_model"]["params"]["coefficients"]
                   if item.get("table") == table_id]
        assert len(matches) == 1, (spec["id"], matches)
        coefficient = matches[0]
        assert coefficient["input"] in {field["name"] for field in spec["inputs"]}
        before = coefficient.get("interpretation")
        assert before in (None, "signed_percentage_change"), before
        coefficient["interpretation"] = "signed_percentage_change"
        if section == "2-6-1":
            quantity_input = spec["quantity_model"]["params"].get("quantity_input")
            assert quantity_input in (None, "volume")
            spec["quantity_model"]["params"]["quantity_input"] = "volume"
            skip = ["0.6m초과∼0.8m이하"]
        else:
            skip = ["연3회 이상"]
        existing_skip = coefficient.get("skip_values", [])
        assert existing_skip in ([], skip)
        coefficient["skip_values"] = skip
        if section == "1-2-11":
            table = next(item for item in spec["tables"] if item["id"] == "p919-t2")
            rate_row = table["values"]["요율"]
            assert rate_row.get("배부식 기계") == "8%"
            if "핸드가이드식 기계" not in rate_row:
                rate_row["핸드가이드식 기계"] = "7%"
            rules = [
                {"name": "공구손료 및 경장비 기계경비 (배부식 기계)", "category": "경비",
                 "base": "labor_subtotal", "rate": "0.08", "when": {"machine_type": "배부식"},
                 "cite": {"table_id": "p919-t2", "row": "요율", "column": "배부식 기계", "value": "8%"}},
                {"name": "공구손료 및 경장비 기계경비 (핸드가이드식 기계)", "category": "경비",
                 "base": "labor_subtotal", "rate": "0.07", "when": {"machine_type": "핸드가이드식"},
                 "cite": {"table_id": "p919-t2", "row": "요율", "column": "핸드가이드식 기계", "value": "7%"}},
            ]
            if not spec.get("cost_rules"):
                spec["cost_rules"] = rules
            else:
                assert spec["cost_rules"] == rules
            not_calculated = spec.get("not_calculated", [])
            spec["not_calculated"] = [item for item in not_calculated
                                      if item.get("item") != "공구손료 및 경장비의 기계경비"]
            if not CHUNKS_BACKUP.exists():
                shutil.copy2(CHUNKS, CHUNKS_BACKUP)
            chunks = [json.loads(line) for line in CHUNKS.read_text(encoding="utf-8").splitlines() if line.strip()]
            chunk = next(item for item in chunks if item.get("chunk_id") == "p919-t2")
            chunk["text"] = "1-2-11 잔디깎기 공구손료 및 경장비 기계경비 | 요율 배부식 기계 8% | 핸드가이드식 기계 7%"
            chunks[chunks.index(next(item for item in chunks if item.get("chunk_id") == "p919-t2"))] = chunk
            CHUNKS.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in chunks) + "\n",
                              encoding="utf-8")
        path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        edits.append({"id": spec["id"], "table": table_id, "before": before,
                      "after": coefficient["interpretation"], "backup": str(backup.relative_to(ROOT))})
    print(json.dumps({"root_cause": "signed source percentage cells lacked delta interpretation",
                      "updated": edits}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
