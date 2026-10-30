"""Check exact A/B/C and small-tunnel equipment cells from printed p.341."""
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

SPEC = ROOT / "data/drafts/specs/토목/3-2-4.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
EXPECTED = {
    "p397-t0": {
        "발파천공및 록볼트 천공장비": {"A군": "소형브레이커 (2.7㎥/min 2~4대)", "B군": "점보드릴 (2붐)", "C군": "점보드릴 (3붐)", "비고": "장비조합은 공단면 크기 및 조건에 따라 적정하게 조합하여 적용"},
        "버력상차장비": {"A군": "로더 1.72㎥", "B군": "로더 3.5㎥", "C군": "로더 5.0㎥", "비고": ""},
        "버력운반장비": {"A군": "로더 1.72㎥", "B군": "덤프트럭 15톤", "C군": "덤프트럭 15톤", "비고": ""},
    },
    "p397-t2": {
        "발파천공천공장비": {"소형터널": "소형브레이커(2대)"},
        "버력상차장비": {"소형터널": "인력, 록커쇼벨"},
        "버력운반장비": {"소형터널": "리어카, 경운기, 대차"},
    },
}


def norm(value: str) -> str:
    return ("".join(unicodedata.normalize("NFKC", value).split()).casefold()
            .replace("~", "-").replace("∼", "-").replace("〜", "-").replace("～", "-"))


def source_tokens(value: str, source: str) -> None:
    for token in re.findall(r"[가-힣]+|[0-9][0-9.,~∼-]*|[a-z]+", norm(value)):
        assert token in source, (value, token)


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = package["draft"]
    selector = next(field for field in spec["inputs"] if field["name"] == "lookup_type")
    assert selector["source_table_map"] == {
        "A·B·C군 표준 장비조합": "p397-t0", "소형터널 장비조합": "p397-t2",
    }
    roles = next(field for field in spec["inputs"] if field["name"] == "equipment_role")
    assert roles.get("source_row_key") is True
    tables = {table["id"]: table for table in spec["tables"]}
    checked_cells = cited_cells = 0
    with pymupdf.open(PDF) as doc:
        source = norm(doc[396].get_text())
        for table_id, matrix in EXPECTED.items():
            assert tables[table_id]["values"] == matrix, table_id
            for row, columns in matrix.items():
                assert norm(row) in source, row
                for column, value in columns.items():
                    assert norm(column) in source, column
                    if value:
                        source_tokens(value, source)
                    checked_cells += 1
                    if not value or column == "비고":
                        continue  # visually blank source cells do not produce citations
                    route = "A·B·C군 표준 장비조합" if table_id == "p397-t0" else "소형터널 장비조합"
                    tunnel_class = column
                    result = lookup(spec, {"lookup_type": route, "tunnel_class": tunnel_class,
                                           "equipment_role": row, "custom_combination": False})
                    assert result["status"] == "computed" and result["value"] == value, (route, tunnel_class, row, result)
                    cite = result["provenance"]["citations"][0]
                    assert (cite["internal_id"], cite["row"], cite["column"], cite["value"]) == (
                        table_id, row, column, value)
                    cited_cells += 1
    blocked = lookup(spec, {"lookup_type": "A·B·C군 표준 장비조합", "tunnel_class": "B군",
                            "equipment_role": "버력상차장비", "custom_combination": True})
    assert blocked["status"] == "blocked", blocked
    validation = validate_one(SPEC, ROOT / "data/drafts/specs", load_chunks(ROOT / "data/processed/chunks.all.jsonl"), None)
    assert validation["ok"], validation
    report = {"status": "pass", "printed_page": 341, "independent_matrix_cells": checked_cells,
              "nonblank_source_cells_with_exact_runtime_citations": cited_cells,
              "exact_table_routes": 2, "custom_combination": "source-backed block retained",
              "criteria_table_p397_t1": "used as human classification reference; no automatic class inference claimed",
              "citation_preflight": "pass"}
    out = ROOT / "evals/runtime_validation/lookup-3-2-4-source-audit-2026-10-19.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
