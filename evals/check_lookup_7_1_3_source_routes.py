"""Audit pump/grab table cells and exact row citations against PDF p.388."""
from __future__ import annotations

import json
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402
from backend.agent.tools.calc.lookup import lookup  # noqa: E402
from pipeline.validate_drafts import load_chunks, validate_one  # noqa: E402

SPEC = ROOT / "data/drafts/specs/토목/7-1-3.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
EXPECTED = {
    "p444-t0": {
        "224": {"예선(㎾)": "119∼134", "양묘선(㎾)": "7.5∼37.3", "연락선(㎾)": "29.8"},
        "448": {"예선(㎾)": "187", "양묘선(㎾)": "37.3∼74.6", "연락선(㎾)": "29.8"},
        "746": {"예선(㎾)": "261", "양묘선(㎾)": "89.5", "연락선(㎾)": "29.8"},
        "895": {"예선(㎾)": "261", "양묘선(㎾)": "89.5", "연락선(㎾)": "29.8"},
        "1,492": {"예선(㎾)": "336", "양묘선(㎾)": "89.5", "연락선(㎾)": "29.8"},
        "1,641": {"예선(㎾)": "336", "양묘선(㎾)": "89.5", "연락선(㎾)": "29.8"},
        "2,462": {"예선(㎾)": "373", "양묘선(㎾)": "149.2", "연락선(㎾)": "29.8"},
        "2,984": {"예선(㎾)": "373∼597", "양묘선(㎾)": "149.2", "연락선(㎾)": "29.8"},
        "3,282": {"예선(㎾)": "597", "양묘선(㎾)": "149.2", "연락선(㎾)": "29.8"},
        "4,476∼8,952": {"예선(㎾)": "597∼1,492", "양묘선(㎾)": "186.5 이상", "연락선(㎾)": "29.8"},
        "14,920": {"예선(㎾)": "746 : 1척, 1,790 : 1척", "양묘선(㎾)": "186.5 이상", "연락선(㎾)": "29.8"},
    },
    "p444-t1": {
        "0.65": {"예선(㎾)": "-", "토운선(㎥)": "척수와 용량은 작업조건에 따라서 조정", "양묘선(㎾)": "7.5", "연락선(㎾)": "29.8"},
        "1.00": {"예선(㎾)": "-", "토운선(㎥)": "척수와 용량은 작업조건에 따라서 조정", "양묘선(㎾)": "7.5", "연락선(㎾)": "29.8"},
        "1.50": {"예선(㎾)": "-", "토운선(㎥)": "척수와 용량은 작업조건에 따라서 조정", "양묘선(㎾)": "7.5", "연락선(㎾)": "29.8"},
        "3.00": {"예선(㎾)": "119", "토운선(㎥)": "60", "양묘선(㎾)": "7.5", "연락선(㎾)": "29.8"},
        "5.00": {"예선(㎾)": "119", "토운선(㎥)": "60", "양묘선(㎾)": "7.5", "연락선(㎾)": "29.8"},
        "6.00": {"예선(㎾)": "119", "토운선(㎥)": "60, 100", "양묘선(㎾)": "22.4", "연락선(㎾)": "29.8"},
        "7.50": {"예선(㎾)": "119", "토운선(㎥)": "60, 100", "양묘선(㎾)": "22.4", "연락선(㎾)": "29.8"},
        "12.50~25.00": {"예선(㎾)": "134, 187, 336", "토운선(㎥)": "200, 300, 500이상", "양묘선(㎾)": "37.3", "연락선(㎾)": "29.8"},
    },
}


def norm(value: str) -> str:
    return "".join(unicodedata.normalize("NFKC", value).split()).casefold()


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = package["draft"]
    selector = next(field for field in spec["inputs"] if field["name"] == "dredger_type")
    routes = {"펌프준설선": "p444-t0", "그래브 준설선": "p444-t1"}
    assert selector["source_table_map"] == routes
    tables = {table["id"]: table for table in spec["tables"]}
    checked_cells = citation_cells = 0
    with pymupdf.open(PDF) as doc:
        text = norm(doc[443].get_text())
        for table_id, expected in EXPECTED.items():
            assert tables[table_id]["values"] == expected, table_id
            for row, columns in expected.items():
                assert norm(row.replace("~", "∼")) in text or norm(row) in text, row
                for value in columns.values():
                    for token in value.split(", "):
                        assert norm(token) in text or token == "-", (row, value, token)
                    checked_cells += 1
                dredger = "펌프준설선" if table_id == "p444-t0" else "그래브 준설선"
                field = "pump_dredger_spec" if table_id == "p444-t0" else "grab_dredger_spec"
                result = lookup(spec, {"dredger_type": dredger, field: row})
                assert result["status"] == "computed" and result["value"] == columns, (dredger, row, result)
                citations = result["provenance"]["citations"]
                assert {(c["internal_id"], c["row"], c["column"], c["value"]) for c in citations} == {
                    (table_id, row, column, value) for column, value in columns.items()
                }
                citation_cells += len(citations)
        # A mismatched branch value must not silently select the other table.
        wrong_branch = lookup(spec, {"dredger_type": "펌프준설선", "grab_dredger_spec": "12.50~25.00"})
        assert wrong_branch["status"] in {"ask", "rejected"}, wrong_branch
    validation = validate_one(SPEC, ROOT / "data/drafts/specs", load_chunks(ROOT / "data/processed/chunks.all.jsonl"), None)
    assert validation["ok"], validation
    report = {"status": "pass", "printed_page": 388, "source_tables": 2,
              "independently_transcribed_source_cells": checked_cells, "exact_table_routes": 2,
              "runtime_row_citation_cells": citation_cells, "citation_preflight": "pass",
              "source_visual_review": "PDF p.388 pump and grab tables visually compared; open alternative rows preserved as printed"}
    out = ROOT / "evals/runtime_validation/lookup-7-1-3-source-audit-2026-10-19.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
