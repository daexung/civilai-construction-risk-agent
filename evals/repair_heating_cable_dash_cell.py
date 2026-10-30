"""Restore an omitted source dash and resource-row axis for 3-4-1."""
import json
import sys
from fractions import Fraction
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
SPEC_PATH = ROOT / "data/drafts/specs/기계설비/3-4-1.json"
CHUNKS_PATH = ROOT / "data/processed/chunks.all.jsonl"


def repair():
    package = json.loads(SPEC_PATH.read_text(encoding="utf8"))
    draft = package["draft"]
    params = draft["quantity_model"]["params"]
    rate = params["unit_rate_table"]
    rate["row_input"] = None
    values = next(table for table in draft["tables"] if table["id"] == "p724-t2")["values"]
    values["보통인부"]["수량 세대내"] = "-"
    params["excluded_resources"] = [{
        "trade": "보통인부", "when": {"location": "수량 세대내"},
        "source": "p724-t2 원문 대시 셀",
        "cite": {"table_id": "p724-t2", "row": "보통인부",
                 "column": "수량 세대내", "value": "-"},
    }]
    SPEC_PATH.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf8")

    lines = CHUNKS_PATH.read_text(encoding="utf8").splitlines()
    found = False
    for i, line in enumerate(lines):
        chunk = json.loads(line)
        if chunk.get("chunk_id") != "p724-t2":
            continue
        marker = "보통인부 | 단위 인 | 수량 공용부위 0.006"
        assert marker in chunk["text"], chunk["text"]
        chunk["text"] = chunk["text"].replace(
            marker, "보통인부 | 단위 인 | 수량 세대내 - | 수량 공용부위 0.006", 1)
        lines[i] = json.dumps(chunk, ensure_ascii=False)
        found = True
        break
    assert found
    CHUNKS_PATH.write_text("\n".join(lines) + "\n", encoding="utf8")


def main():
    repair()
    sys.path.insert(0, str(ROOT))
    from backend.agent.tools.calc.per_unit import per_unit
    from pipeline.validate_drafts import file_sha256, load_chunks, validate_one

    spec = json.loads(SPEC_PATH.read_text(encoding="utf8"))["draft"]
    with fitz.open(PDF) as document:
        grid = document[723].find_tables().tables[2].extract()
    assert grid[2][2].strip() == "0.015\n-"
    assert grid[2][3].strip() == "0.017\n0.006"
    values = next(table for table in spec["tables"] if table["id"] == "p724-t2")["values"]
    assert values == {
        "기계설비공": {"수량 세대내": "0.015", "수량 공용부위": "0.017"},
        "보통인부": {"수량 공용부위": "0.006", "수량 세대내": "-"},
    }
    routes = 0
    for location, expected in (("수량 세대내", {"기계설비공": "3/200"}),
                               ("수량 공용부위", {"기계설비공": "17/1000", "보통인부": "3/500"})):
        result = per_unit(spec, {"location": location, "length": "100"})
        assert result["status"] == "computed", result
        lines = {line["name"]: line for line in result["unit_lines"]}
        assert {name: line["exact"] for name, line in lines.items()} == expected
        for name, line in lines.items():
            cite = line["citations"][0]
            assert (cite["internal_id"], cite["row"], cite["column"], cite["value"]) == (
                "p724-t2", name, location, values[name][location])
        excluded = result["provenance"].get("excluded_resources", [])
        if location == "수량 세대내":
            assert len(excluded) == 1 and excluded[0]["citations"][0]["value"] == "-"
        routes += 1
    chunks = load_chunks(CHUNKS_PATH)
    validation = validate_one(SPEC_PATH, ROOT / "data/drafts", chunks, file_sha256(CHUNKS_PATH))
    assert not validation["format_issues"] and not validation["citation_issues"], validation
    print(json.dumps({"status": "pass", "section": "기계설비/3-4-1",
                      "independent_pdf_cells": 4, "exact_input_routes": routes,
                      "exact_rate_outputs": 3, "source_dash_exclusions": 1,
                      "citation_preflight": "pass", "full_rule_verification": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
