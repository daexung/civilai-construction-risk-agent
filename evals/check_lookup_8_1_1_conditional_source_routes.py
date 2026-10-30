"""Audit both exact 8-1-1 source matrices and all conditional lookup paths."""
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

SPEC = ROOT / "data/drafts/specs/공통/8-1-1.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
EXPECTED = {
    "p219-t0": {
        "벌개,제근": {"건설기계 종류": "불도저(레이크도우저)"},
        "굴착": {"건설기계 종류": "로더, 굴착기, 불도저, 리퍼"},
        "굴착,적재": {"건설기계 종류": "로더, 굴착기"},
        "굴착･운반": {"건설기계 종류": "불도저, 스크레이퍼"},
        "운반": {"건설기계 종류": "불도저, 덤프트럭, 벨트컨베이어"},
        "부설": {"건설기계 종류": "불도저, 모터그레이더"},
        "함수량조절": {"건설기계 종류": "살수차"},
        "다짐": {"건설기계 종류": "롤러(타이어, 탬핑, 진동, 로드), 불도저, 플레이트 콤팩터, 래머, 탬퍼, 법면다짐기"},
        "정지": {"건설기계 종류": "불도저, 모터그레이더"},
    },
    "p219-t1": {
        "절붕･압토": {"평균 20m": "불도저"},
        "토운반": {
            "60m이하": "불도저",
            "60∼100m": "- 불도저, - 로더+덤프트럭, - 굴착기+덤프트럭",
            "100m이상": "- 로더+덤프트럭, - 굴착기+덤프트럭, - 모터스크레이퍼",
        },
    },
}


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = package["draft"]
    tables = {table["id"]: table for table in spec["tables"]}
    selector = next(field for field in spec["inputs"] if field["name"] == "lookup_type")
    assert selector["source_table_map"] == {"작업종류별": "p219-t0", "운반거리별": "p219-t1"}
    for table_id, expected in EXPECTED.items():
        assert tables[table_id]["values"] == expected, table_id
    # The mapping below was transcribed by visual comparison with the rendered
    # two-table crop on PDF p.163; token checks only guard transcription presence.
    with pymupdf.open(PDF) as document:
        source_text = "".join(unicodedata.normalize("NFKC", document[218].get_text()).split()).casefold()
    for expected in EXPECTED.values():
        for row, columns in expected.items():
            assert "".join(unicodedata.normalize("NFKC", row).split()).casefold() in source_text, row
            for column, value in columns.items():
                assert "".join(unicodedata.normalize("NFKC", column).split()).casefold() in source_text, column
                for token in value.split(", "):
                    assert "".join(unicodedata.normalize("NFKC", token).split()).casefold() in source_text, token

    operations = lookup(spec, {"lookup_type": "작업종류별"})
    assert operations["status"] == "ask" and [q["name"] for q in operations["questions"]] == ["work_type"]
    assert operations["questions"][0]["allowed_values"] == list(EXPECTED["p219-t0"])
    transport = lookup(spec, {"lookup_type": "운반거리별"})
    assert transport["status"] == "ask" and [q["name"] for q in transport["questions"]] == ["earth_work_type"]
    for work, expected_options in (("절붕･압토", ["평균 20m"]),
                                   ("토운반", ["60m이하", "60∼100m", "100m이상"])):
        domain = lookup(spec, {"lookup_type": "운반거리별", "earth_work_type": work})
        assert domain["status"] == "ask" and domain["questions"][0]["name"] == "haul_distance"
        assert domain["questions"][0]["allowed_values"] == expected_options, (work, domain)

    checked_cells = 0
    cases = [("작업종류별", "work_type", row, expected["건설기계 종류"], "p219-t0", "건설기계 종류")
             for row, expected in EXPECTED["p219-t0"].items()]
    cases.extend(("운반거리별", "earth_work_type", row, value, "p219-t1", column)
                 for row, columns in EXPECTED["p219-t1"].items() for column, value in columns.items())
    for route, row_field, row, expected_value, table_id, column in cases:
        inputs = {"lookup_type": route, row_field: row}
        if table_id == "p219-t1":
            inputs["haul_distance"] = column
        result = lookup(spec, inputs)
        assert result["status"] == "computed" and result["value"] == expected_value, inputs
        citation = result["provenance"]["citations"][0]
        assert (citation["internal_id"], citation["row"], citation["column"], citation["value"]) == (
            table_id, row, column, expected_value), inputs
        checked_cells += 1
    wrong_branch = lookup(spec, {"lookup_type": "작업종류별", "earth_work_type": "토운반"})
    assert wrong_branch["status"] == "rejected", wrong_branch
    validation = validate_one(SPEC, ROOT / "data/drafts/specs",
                              load_chunks(ROOT / "data/processed/chunks.all.jsonl"), None)
    assert validation["ok"], validation
    report = {"status": "pass", "source_tables": 2,
              "independently_transcribed_source_cells": sum(sum(len(row) for row in t.values()) for t in EXPECTED.values()),
              "exact_table_routes": 2, "source_derived_paths_and_cell_citations": checked_cells,
              "irrelevant_branch_rejected": True, "citation_preflight": "pass"}
    out = ROOT / "evals/runtime_validation/lookup-8-1-1-conditional-source-audit-2026-10-19.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
