"""Audit remaining 8-4-9 source matrices and all nine exact table routes."""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402
from backend.agent.tools.calc.lookup import lookup  # noqa: E402
from pipeline.validate_drafts import load_chunks, validate_one  # noqa: E402

SPEC = ROOT / "data/drafts/specs/공통/8-4-9.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
ROUTES = {
    "펌프준설선": ("p341-t0", 341, 0, "9010", ["주연료", "잡재료", "준설선 선장", "준설선 기관사", "준설선 운전사", "선원"], ["ℓ/hr", "%", "인", "〃", "〃", "〃"]),
    "그래브 준설선": ("p341-t1", 341, 1, "9020", ["주연료", "잡재료", "준설선 선장", "준설선 기관사", "준설선 운전사", "선원"], ["ℓ/hr", "%", "인", "〃", "〃", "〃"]),
    "예선": ("p341-t2", 341, 2, "9030", ["주연료", "잡재료", "선원"], ["ℓ/hr", "%", "인"]),
    "양묘선(앵커바지)": ("p342-t0", 342, 0, "9040", ["주연료", "잡재료", "선원"], ["ℓ/hr", "%", "인"]),
    "기중기선(비자항)": ("p342-t1", 342, 1, "9050", ["주연료", "잡재료", "건설기계운전사", "선원"], ["ℓ/hr", "%", "인", "인"]),
    "토운선": ("p342-t2", 342, 2, "9060", ["주연료", "잡재료", "선원"], ["ℓ/hr", "%", "인"]),
    "이우선(비자항)": ("p342-t3", 342, 3, "9070", ["주연료", "잡재료", "선원"], ["ℓ/hr", "%", "인"]),
    "대선": ("p343-t0", 343, 0, "9080", ["주연료", "잡재료", "고급선원"], ["ℓ/hr", "%", "인"]),
    "하천골재채취선": ("p343-t1", 343, 1, "9090", ["주연료", "잡재료", "준설선기관사", "준설선운전사", "선원"], ["ℓ/hr", "%", "〃", "〃", "〃"]),
}
ALREADY_CHECKED = {"p342-t0": 33}


def norm(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    # PDF extraction may split a range over two lines and preserve the
    # mathematical tilde (U+223C), while the draft uses ASCII '~'. These are
    # equivalent range separators; do not normalize other punctuation/numbers.
    text = text.translate(str.maketrans({"∼": "~", "〜": "~", "～": "~"}))
    return re.sub(r"\s+", "", text).casefold()


def lines(value: object) -> list[str]:
    return [part.strip() for part in str(value or "").splitlines() if part.strip()]


def ordered_contains(haystack: object, needles: list[str]) -> bool:
    source = norm(haystack)
    cursor = 0
    for needle in needles:
        token = norm(needle)
        position = source.find(token, cursor)
        if not token or position < 0:
            return False
        cursor = position + len(token)
    return True


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = package["draft"]
    route_field = next(field for field in spec["inputs"] if field["name"] == "machine_type")
    assert route_field["source_table_map"] == {category: row[0] for category, row in ROUTES.items()}
    pdf = pymupdf.open(PDF)
    matrices = {table["id"]: table for table in spec["tables"]}
    newly_checked_cells = 0
    route_citations = 0
    for category, (table_id, printed_page, table_index, code, expected_labels, expected_units) in ROUTES.items():
        page = pdf[printed_page - 1]
        assert norm(f"({code})") in norm(page.get_text()), (table_id, code)
        table = matrices[table_id]
        grid = page.find_tables().tables[table_index].extract()
        assert len(grid) >= 3 and len(grid[0]) == len(grid[1])
        source_headers = [header for header in grid[1][2:-1] if header]
        draft_specs = list(next(iter(table["values"].values())))
        assert len(source_headers) == len(draft_specs), (table_id, source_headers, draft_specs)
        for source_header, draft_key in zip(source_headers, draft_specs):
            assert norm(source_header).endswith(norm(draft_key)), (table_id, source_header, draft_key)

        if table_id not in ALREADY_CHECKED:
            source_row = grid[2]
            if len(grid) == len(expected_labels) + 2:
                actual_labels = [row[0] for row in grid[2:]]
                actual_units = [row[1] for row in grid[2:]]
                assert [norm(value) for value in actual_units] == [norm(value) for value in expected_units], (
                    table_id, actual_units)
                for label, raw_label in zip(expected_labels, actual_labels):
                    assert norm(label) == norm(raw_label), (table_id, label, raw_label)
                for label, row in zip(expected_labels, grid[2:]):
                    expected = [row[index] for index in range(2, 2 + len(draft_specs))]
                    actual = [table["values"][label][draft_spec] for draft_spec in draft_specs]
                    assert [norm(v) for v in actual] == [norm(v) for v in expected], (
                        table_id, label, actual, expected)
                    newly_checked_cells += len(actual)
            else:
                raw_labels = source_row[0]
                raw_units = lines(source_row[1])
                assert ordered_contains(raw_labels, expected_labels), (table_id, raw_labels, expected_labels)
                assert [norm(value) for value in raw_units] == [norm(value) for value in expected_units], (
                    table_id, raw_units, expected_units)
                for spec_index, draft_spec in enumerate(draft_specs):
                    column = lines(source_row[2 + spec_index])
                    assert len(column) == len(expected_labels), (table_id, draft_spec, column)
                    for row_index, label in enumerate(expected_labels):
                        actual = table["values"][label][draft_spec]
                        assert norm(actual) == norm(column[row_index]), (table_id, label, draft_spec, actual, column[row_index])
                        newly_checked_cells += 1
        else:
            assert sum(len(row) for row in table["values"].values()) == ALREADY_CHECKED[table_id]

        result = lookup(spec, {"machine_type": category})
        assert result.get("status") == "computed" and result.get("table_reference"), (category, result)
        assert result["provenance"].get("table") == table_id and result["value"] == table["values"]
        citation_count = sum(len(row) for row in table["values"].values())
        assert len(result["provenance"]["citations"]) == citation_count
        assert all(citation["internal_id"] == table_id for citation in result["provenance"]["citations"])
        route_citations += citation_count

    first = lookup(spec, {})
    assert first.get("status") == "ask" and first["questions"][0]["name"] == "machine_type"
    assert first["questions"][0]["allowed_values"] == list(ROUTES)
    validation = validate_one(SPEC, ROOT / "data/drafts/specs",
                              load_chunks(ROOT / "data/processed/chunks.all.jsonl"), None)
    assert validation["ok"], validation
    print(json.dumps({"status": "pass", "printed_pages": [341, 342, 343],
                      "exact_category_routes": len(ROUTES), "newly_audited_tables": len(ROUTES) - len(ALREADY_CHECKED),
                      "new_independent_source_value_cells": newly_checked_cells,
                      "reused_prior_source_audit": ALREADY_CHECKED,
                      "route_value_cells_and_citations": route_citations, "citation_preflight": "pass"},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
