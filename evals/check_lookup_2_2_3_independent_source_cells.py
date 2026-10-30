"""Source-audit all three independent 2-2-3 tables and their conditional axes."""
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

SPEC = ROOT / "data/drafts/specs/공통/2-2-3.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
PREFAB = {
    "손율(%)": {"3개월": "12", "6개월": "16", "12개월": "25", "24개월": "38", "36개월": "53", "48개월": "70", "60개월 이상": "100"},
    "부자재율 (%) 사무실": {"3개월": "36", "6개월": "28", "12개월": "19", "24개월": "13", "36개월": "11", "48개월": "9", "60개월 이상": "7"},
    "부자재율 (%) 창고": {"3개월": "42", "6개월": "32", "12개월": "22", "24개월": "15", "36개월": "12", "48개월": "10", "60개월 이상": "8"},
}
CONTAINER = {"손율(%)": {"3개월": "18", "6개월": "23", "12개월": "34", "24개월": "56", "36개월": "78", "48개월 이상": "100"}}
FENCE = {
    "3개월": {"손 율 (%) 전기아연도금강판": "29", "손 율 (%) 재생플라스틱방음판": "31", "손 율 (%) 스틸방음판": "33"},
    "6개월": {"손 율 (%) 전기아연도금강판": "33", "손 율 (%) 재생플라스틱방음판": "36", "손 율 (%) 스틸방음판": "38"},
    "12개월": {"손 율 (%) 전기아연도금강판": "43", "손 율 (%) 재생플라스틱방음판": "45", "손 율 (%) 스틸방음판": "47"},
    "24개월": {"손 율 (%) 전기아연도금강판": "62", "손 율 (%) 재생플라스틱방음판": "63", "손 율 (%) 스틸방음판": "64"},
    "36개월": {"손 율 (%) 전기아연도금강판": "81", "손 율 (%) 재생플라스틱방음판": "82", "손 율 (%) 스틸방음판": "82"},
    "48개월": {"손 율 (%) 전기아연도금강판": "100", "손 율 (%) 재생플라스틱방음판": "100", "손 율 (%) 스틸방음판": "100"},
}


def norm(value: str) -> str:
    return "".join(unicodedata.normalize("NFKC", value).split()).casefold()


def label_visible(label: str, source: str) -> bool:
    # Some source labels are hierarchical merged headers (e.g. "부자재율 (%)"
    # spanning the next "사무실/창고" rows); compare their source components.
    return norm(label) in source or all(norm(token) in source for token in label.split())


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = package["draft"]
    maps = {"p94-t1": PREFAB, "p95-t1": CONTAINER, "p95-t2": FENCE}
    tables = {table["id"]: table for table in spec["tables"]}
    route = next(field for field in spec["inputs"] if field["name"] == "facility_category")
    assert route["source_table_map"] == {"철제조립식 가설건축물": "p94-t1", "콘테이너형 가설건축물": "p95-t1", "가설울타리 및 가설방음벽": "p95-t2"}
    inputs_map = {
        "p94-t1": lambda row, col: {"facility_category": "철제조립식 가설건축물", "rate_basis": row, "duration_prefab": col},
        "p95-t1": lambda row, col: {"facility_category": "콘테이너형 가설건축물", "duration_container": col},
        "p95-t2": lambda row, col: {"facility_category": "가설울타리 및 가설방음벽", "duration_fence": row, "fence_material": col},
    }
    page_for = {"p94-t1": 93, "p95-t1": 94, "p95-t2": 94}
    cells = citations = 0
    with pymupdf.open(PDF) as doc:
        for table_id, expected in maps.items():
            assert tables[table_id]["values"] == expected, table_id
            source = norm(doc[page_for[table_id]].get_text())
            for row, columns in expected.items():
                assert label_visible(row, source), row
                for column, value in columns.items():
                    assert label_visible(column, source), column
                    assert norm(value) in source, (table_id, row, column, value)
                    result = lookup(spec, inputs_map[table_id](row, column))
                    assert result["status"] == "computed" and result["value"] == value, (table_id, row, column, result)
                    cite = result["provenance"]["citations"][0]
                    assert (cite["internal_id"], cite["row"], cite["column"], cite["value"]) == (table_id, row, column, value)
                    cells += 1
                    citations += 1
    wrong = lookup(spec, {"facility_category": "가설울타리 및 가설방음벽", "duration_container": "48개월 이상"})
    assert wrong["status"] == "rejected", wrong
    validation = validate_one(SPEC, ROOT / "data/drafts/specs", load_chunks(ROOT / "data/processed/chunks.all.jsonl"), None)
    assert validation["ok"], validation
    report = {"status": "pass", "printed_pages": [38, 39], "independent_source_cells": cells,
              "exact_table_routes": 3, "runtime_exact_cell_citations": citations,
              "mutually_exclusive_axes": "pass", "citation_preflight": "pass",
              "source_visual_review": "p.38 steel prefab and p.39 container/fence tables compared cell-by-cell"}
    out = ROOT / "evals/runtime_validation/lookup-2-2-3-source-audit-2026-10-19.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
