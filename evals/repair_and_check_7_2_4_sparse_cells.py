"""Restore PDF-visible dash cells and verify all 7-2-4 work-type routes."""
from __future__ import annotations

import json
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.agent.tools.calc.per_unit import per_unit  # noqa: E402
from pipeline.validate_drafts import file_sha256, load_chunks, validate_one  # noqa: E402

SPEC_PATH = ROOT / "data/drafts/specs/토목/7-2-4.json"
CHUNKS_PATH = ROOT / "data/processed/chunks.all.jsonl"
AUDIT_PATH = ROOT / "evals/runtime_validation/per-unit-7-2-4-sparse-cells-2026-10-19.json"
TABLE_ID = "p446-t2"
WORK_TYPES = ["기초고르기", "피복석 고르기", "피복석\n거친고르기",
              "내부사석\n고르기", "필터사석\n고르기"]
# Transcribed independently from the rendered original PDF page 446 (printed
# page 390). A dash is a source exclusion, not a zero-valued rate.
SOURCE = {
    "석공": ["0.70", "0.62", "0.55", "0.55", "0.07"],
    "보통인부": ["0.42", "0.39", "0.36", "0.36", "-"],
    "굴착기": ["1.72", "-", "-", "1.36", "0.31"],
    "크레인": ["-", "1.53", "1.36", "-", "-"],
}


def main() -> int:
    package = json.loads(SPEC_PATH.read_text(encoding="utf8"))
    spec = package["draft"]
    table = next(item for item in spec["tables"] if item["id"] == TABLE_ID)
    columns = list(table["values"]["석공"])
    assert columns == WORK_TYPES, (columns, WORK_TYPES)
    for trade, expected in SOURCE.items():
        actual = [table["values"].get(trade, {}).get(column, "-") for column in columns]
        assert actual == expected, (trade, actual, expected)

    params = spec["quantity_model"]["params"]
    rate = params["unit_rate_table"]
    assert rate["table"] == TABLE_ID
    exclusions = params.get("excluded_resources", [])
    expected_exclusions = {
        (trade, WORK_TYPES[i])
        for trade, cells in SOURCE.items()
        for i, value in enumerate(cells) if value == "-"
    }
    actual_exclusions = {
        (item["trade"], item["when"]["work_type"]): item
        for item in exclusions
    }
    assert set(actual_exclusions) == expected_exclusions, {
        "missing": sorted(expected_exclusions - set(actual_exclusions)),
        "extra": sorted(set(actual_exclusions) - expected_exclusions),
    }
    for (trade, work_type), item in actual_exclusions.items():
        cite = item["cite"]
        assert (cite["table_id"], cite["row"], cite["column"], cite["value"]) == (
            TABLE_ID, trade, work_type, "-")

    chunks = [json.loads(line) for line in CHUNKS_PATH.read_text(encoding="utf8").splitlines()
              if line.strip()]
    chunk = next(item for item in chunks if item.get("chunk_id") == TABLE_ID)
    restoration = (
        "\n[원문 표 셀 복원: PDF 446쪽(인쇄 390쪽), 7-2-4 수상고르기] "
        "보통인부 | 필터사석 고르기 -; "
        "굴착기(1.0㎥) | 피복석 고르기 -, 피복석 거친고르기 -; "
        "크레인(10ton) | 기초고르기 -, 내부사석 고르기 -, 필터사석 고르기 -."
    )
    if restoration.strip() not in chunk["text"]:
        chunk["text"] = chunk["text"].rstrip() + restoration
        CHUNKS_PATH.write_text("\n".join(json.dumps(item, ensure_ascii=False)
                                       for item in chunks) + "\n", encoding="utf8")

    routes = 0
    output_count = 0
    for work_index, work_type in enumerate(WORK_TYPES):
        present = {trade: Fraction(cells[work_index]) for trade, cells in SOURCE.items()
                   if cells[work_index] != "-"}
        for quantity in ("10", "20"):
            result = per_unit(spec, {"work_type": work_type, "area": quantity})
            assert result["status"] == "computed", (work_type, quantity, result)
            got = {line["name"]: Fraction(line["exact"]) for line in result["unit_lines"]}
            expected = {trade: rate_value / 10
                        for trade, rate_value in present.items()}
            assert got == expected, (work_type, quantity, got, expected)
            for line in result["unit_lines"]:
                citations = line["citations"]
                matching = [c for c in citations if c.get("internal_id") == TABLE_ID]
                assert len(matching) == 1, (line, citations)
                cite = matching[0]
                assert cite.get("row") == line["name"]
                assert cite.get("value") == str(SOURCE[line["name"]][work_index])
                # Independently apply the per-square-metre rate to the supplied
                # area and confirm the 10㎡ source-basis arithmetic.
                computed_total = Fraction(line["exact"]) * Fraction(quantity)
                expected_total = SOURCE[line["name"]][work_index]
                assert computed_total == Fraction(expected_total) * Fraction(quantity) / 10
            excluded_rows = result["provenance"]["excluded_resources"]
            excluded = {(item["trade"], item["when"]["work_type"])
                        for item in excluded_rows}
            expected_for_work = {(trade, work_type) for trade, cells in SOURCE.items()
                                 if cells[work_index] == "-"}
            assert excluded == expected_for_work, (work_type, excluded, expected_for_work)
            routes += 1
            output_count += len(got)

    validation = validate_one(SPEC_PATH, ROOT / "data/drafts", load_chunks(CHUNKS_PATH),
                              file_sha256(CHUNKS_PATH))
    assert not validation["format_issues"], validation["format_issues"]
    assert not validation["citation_issues"], validation["citation_issues"]
    audit = {
        "status": "pass", "section": "토목/7-2-4", "table_id": TABLE_ID,
        "source": "Original PDF p.446, printed p.390, visually transcribed independently",
        "independent_source_cells": 20,
        "source_dash_cells": len(expected_exclusions),
        "dash_cells_restored_to_chunk_and_exclusions": len(expected_exclusions),
        "exact_work_type_quantity_routes": routes,
        "exact_resource_outputs_with_table_citations": output_count,
        "quantities_tested": ["10", "20"],
        "format_preflight": "pass", "citation_preflight": "pass",
        "full_rule_verification": False,
        "validation_issues": [],
    }
    AUDIT_PATH.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
