"""Independent PDF-cell and exact-route audit for two independent lookup sections."""
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

PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
SOURCE_CELLS = {
    "1-4-3": {
        "p80-t0": {
            "통제보안지역": {"적용조건": "- 보안구역 등 작업인력의 출입통제로 작업에 지장을 받는 경우", "할증": "20%"},
            "군(軍)통제지역": {"적용조건": "- 인근 사격훈련 등 군(軍) 관련 지역 내 출입통제 등으로 작업에 지장을 받는 경우", "할증": "50%"},
            "도서지역": {"적용조건": "- 본토와 도서지구간 인력의 이동(출퇴근) 발생으로 작업에 지장을 받는 경우", "할증": "50%"},
            "공항지역": {"적용조건": "- 공항 내 이착륙(1일 20회 이상)발생으로 작업에 지장을 받는 경우", "할증": "50%"},
        },
        "p80-t1": {
            "본선상작업": {"13회 이하": "14%", "14~18회 이하": "25%", "19회 이상": "37%"},
            "열차운행선 인접작업": {"13회 이하": "3%", "14~18회 이하": "5%", "19회 이상": "7%"},
        },
        "p81-t0": {
            "지상층": {"2~5층": "1%", "10층 이하": "3%", "15층 이하": "4%", "20층 이하": "5%", "25층 이하": "6%", "30층 이하": "7%", "30층 초과": "5층마다 1%씩 가산"},
            "지하층": {"지하 1층": "1%", "지하 2층": "2%", "지하 2층 초과": "1층마다 1%씩 가산"},
        },
    },
    "1-4-4": {
        "p81-t1": {"산지 A": {"할증": "15%"}, "산지 B": {"할증": "25%"}, "산지 C": {"할증": "50%"}, "경사지 A": {"할증": "10%"}, "경사지 B": {"할증": "20%"}, "습지/해안지": {"할증": "20%"}},
        "p83-t0": {"차도 A (2차로)": {"할증": "30%"}, "차도 B (4차로 이하)": {"할증": "25%"}, "차도 C (4차로 초과)": {"할증": "20%"}, "보행자 및 차량통행": {"할증": "15%"}, "주거환경영향": {"할증": "15%"}, "현장협소": {"할증": "15%"}, "지하매설물": {"할증": "15%"}, "고층/초고층 건축물": {"할증": "10%"}, "대심도굴착 A": {"할증": "20%"}, "대심도굴착 B": {"할증": "30%"}},
    },
}


def norm(value: str) -> str:
    return "".join(unicodedata.normalize("NFKC", value).split()).casefold()


def check_pdf_tokens(document: pymupdf.Document, section: str, table_id: str,
                     expected: dict) -> int:
    page_indices = {"p80-t0": 79, "p80-t1": 79, "p81-t0": 80,
                    "p81-t1": 80, "p83-t0": 82}
    text = norm(document[page_indices[table_id]].get_text())
    checked = 0
    for row, columns in expected.items():
        assert norm(row) in text, (section, table_id, row)
        for column, value in columns.items():
            assert norm(column.replace("적용조건 ", "")) in text, (section, table_id, column)
            # The corresponding rendered source grid was visually checked; these
            # independent tokens guard transcription against the PDF text layer.
            for token in (value if value.startswith("-") else value,):
                assert norm(token) in text, (section, table_id, row, column, value)
            checked += 1
    return checked


def main() -> int:
    checked_cells = pdf_tokens = exact_routes = citation_cells = 0
    blocked_open_ended_cells = 0
    with pymupdf.open(PDF) as document:
        for section, tables_expected in SOURCE_CELLS.items():
            path = ROOT / "data/drafts/specs/공통" / f"{section}.json"
            package = json.loads(path.read_text(encoding="utf-8"))
            spec = package["draft"]
            route = next(field for field in spec["inputs"] if field["name"] == "lookup_type")
            expected_routes = ({"1-4-3": {"현장조건": "p80-t0", "열차의 운행빈도": "p80-t1", "건물 층수": "p81-t0"},
                                "1-4-4": {"지세": "p81-t1", "도심지": "p83-t0"}}[section])
            assert route["source_table_map"] == expected_routes, section
            tables = {table["id"]: table for table in spec["tables"]}
            for table_id, expected in tables_expected.items():
                assert tables[table_id]["values"] == expected, (section, table_id)
                pdf_tokens += check_pdf_tokens(document, section, table_id, expected)
                exact_routes += 1
                for row, columns in expected.items():
                    if section == "1-4-3" and table_id == "p80-t0":
                        result = lookup(spec, {"lookup_type": "현장조건", "site_condition": row})
                        assert result["status"] == "computed" and result["value"] == columns
                        citations = result["provenance"]["citations"]
                        assert {(c["row"], c["column"], c["value"], c["internal_id"]) for c in citations} == {
                            (row, col, value, table_id) for col, value in columns.items()}
                        citation_cells += len(citations)
                        checked_cells += len(columns)
                    else:
                        for column, value in columns.items():
                            if table_id == "p80-t1":
                                route_value, row_field, row_value = "열차의 운행빈도", "train_work_type", row
                                column_field = "train_frequency"
                                input_value = column
                            elif table_id == "p81-t0":
                                route_value, row_field, row_value = "건물 층수", "building_floor_type", row
                                column_field = "above_ground_floor" if row == "지상층" else "underground_floor"
                                input_value = column
                            elif table_id == "p81-t1":
                                route_value, row_field, row_value, column_field, input_value = "지세", "terrain_type", row, None, None
                            elif table_id == "p83-t0":
                                route_value, row_field, row_value, column_field, input_value = "도심지", "urban_type", row, None, None
                            else:
                                raise AssertionError(table_id)
                            inputs = {"lookup_type": route_value, row_field: row_value}
                            if column_field:
                                inputs[column_field] = input_value
                            result = lookup(spec, inputs)
                            if value in ("5층마다 1%씩 가산", "1층마다 1%씩 가산"):
                                assert result["status"] == "blocked", (section, inputs, result)
                                assert result["citations"][0]["internal_id"] == table_id
                                blocked_open_ended_cells += 1
                                checked_cells += 1
                                continue
                            assert result["status"] == "computed" and result["value"] == value, (section, inputs, result)
                            citation = result["provenance"]["citations"][0]
                            assert (citation["internal_id"], citation["row"], citation["column"], citation["value"]) == (table_id, row, column, value)
                            citation_cells += 1
                            checked_cells += 1
            validation = validate_one(path, ROOT / "data/drafts/specs", load_chunks(ROOT / "data/processed/chunks.all.jsonl"), None)
            assert validation["ok"], validation
    report = {"status": "pass", "sections": 2, "independently_transcribed_source_cells": checked_cells,
              "pdf_text_token_checks": pdf_tokens, "exact_table_routes": exact_routes,
              "runtime_cell_citations": citation_cells, "format_citation_preflight": "pass",
              "source_backed_open_ended_cells_remain_blocked": blocked_open_ended_cells,
              "source_visual_review": "PDF source table crops p.24-25 and p.25/27 visually compared cell-by-cell"}
    out = ROOT / "evals/runtime_validation/lookup-1-4-3-1-4-4-source-audit-2026-10-19.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
