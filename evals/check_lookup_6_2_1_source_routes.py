"""Independently verify civil/building classification tables on printed p.133."""
from __future__ import annotations

import json
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402
from backend.agent.tools.calc.lookup import lookup, source_domain_options  # noqa: E402
from pipeline.validate_drafts import load_chunks, validate_one  # noqa: E402

SPEC = ROOT / "data/drafts/specs/공통/6-2-1.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
EXPECTED = {
    "p189-t0": {
        "Type-Ⅰ": {
            "Ⅰ-1": "- 철근가공 및 조립 작업이 일반적인 토목시설(반중력식 옹벽, L형 옹벽, 교량 슬래브,\n매트기초, 수문 등)",
            "Ⅰ-2": "- 특정위치에서 철근의 가공 및 조립이 반복되는 경우(빔제작, 철근망 등)",
        },
        "Type-Ⅱ": {
            "Ⅱ-1": "- 철근가공 및 조립 작업이 복잡한 토목시설(라멘교, 교대, 암거, 지하차도, 부벽식\n옹벽 등)\n- Type-Ⅰ 시설에서 직경 13mm이하 철근이 전 철근중량의 50%이상인 경우",
            "Ⅱ-2": "- 콘크리트대비 소량의 철근이 사용되는 경우(측구/개거, 중력식 옹벽, 일체형\n중앙분리대 등)",
        },
        "Type-Ⅲ": {
            "Ⅲ": "- 철근가공 및 조립 작업이 매우 복잡한 토목시설(교각, 구주식 교대 등)\n- 특수 구조시설물에서 철근직경 35mm를 초과하여 인력에 의한 단독시공이 어려운\n경우(플랜트, 원자력 발전소 등)",
        },
    },
    "p189-t1": {
        "Type-Ⅰ": {"유형": "- 직경 13mm이하 철근이 전 철근중량의 50%미만인 경우"},
        "Type-Ⅱ": {"유형": "- 직경 13mm이하 철근이 전 철근중량의 50%이상인 경우 또는 철골과 병행 시공되는\n경우\n- 직경 13mm이하 철근이 50% 미만이나 철근가공 및 조립 작업이 복잡한\n구조시설물(하수종말처리장, 폐기물처리장 등)"},
    },
}


def norm(value: str) -> str:
    return "".join(unicodedata.normalize("NFKC", value).split()).casefold()


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = package["draft"]
    category = next(field for field in spec["inputs"] if field["name"] == "facility_category")
    assert category["source_table_map"] == {"토목": "p189-t0", "건축": "p189-t1"}
    assert source_domain_options(spec, "facility_type", {"facility_category": "토목"}) == list(EXPECTED["p189-t0"])
    assert source_domain_options(spec, "facility_type", {"facility_category": "건축"}) == list(EXPECTED["p189-t1"])
    tables = {table["id"]: table for table in spec["tables"]}
    checked_cells = cited_cells = 0
    with pymupdf.open(PDF) as doc:
        text = norm(doc[188].get_text())
        for table_id, matrix in EXPECTED.items():
            assert tables[table_id]["values"] == matrix, table_id
            section = "토목" if table_id == "p189-t0" else "건축"
            for row, columns in matrix.items():
                assert norm(row) in text, row
                for column, value in columns.items():
                    assert norm(column) in text, column
                    for phrase in value.split("\n"):
                        assert norm(phrase) in text, (row, phrase)
                    result = lookup(spec, {"facility_category": section, "facility_type": row})
                    assert result["status"] == "computed" and result["value"] == columns, (section, row, result)
                    citations = result["provenance"]["citations"]
                    assert {(c["internal_id"], c["row"], c["column"], c["value"]) for c in citations} == {
                        (table_id, row, col, val) for col, val in columns.items()}
                    checked_cells += len(columns)
                    cited_cells += len(citations)
        wrong = lookup(spec, {"facility_category": "건축", "facility_type": "Type-Ⅲ"})
        assert wrong["status"] != "computed", wrong
    validation = validate_one(SPEC, ROOT / "data/drafts/specs", load_chunks(ROOT / "data/processed/chunks.all.jsonl"), None)
    assert validation["ok"], validation
    report = {"status": "pass", "printed_page": 133, "independently_checked_source_cells": checked_cells,
              "exact_table_routes": 2, "source_derived_row_domains": {"토목": 3, "건축": 2},
              "runtime_citation_cells": cited_cells, "invalid_building_type_III": "not computed",
              "citation_preflight": "pass", "source_visual_review": "p.133 classification grids compared"}
    out = ROOT / "evals/runtime_validation/lookup-6-2-1-source-audit-2026-10-19.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
