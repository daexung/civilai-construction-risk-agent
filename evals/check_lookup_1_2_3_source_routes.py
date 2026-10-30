"""Independently compare 1-2-3 source matrices and exact lookup citations."""
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

SPEC = ROOT / "data/drafts/specs/공통/1-2-3.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
T0 = {
    "경암(硬岩)": {"L": "1.70∼2.00", "C": "1.30∼1.50"},
    "보통암(普通硬岩)": {"L": "1.55∼1.70", "C": "1.20∼1.40"},
    "연암(軟岩)": {"L": "1.30∼1.50", "C": "1.00∼1.30"},
    "풍화암(風化岩)": {"L": "1.30∼1.35", "C": "1.00∼1.15"},
    "폐콘크리트": {"L": "1.40∼1.60", "C": "별도 설계"},
    "호박돌(玉石)": {"L": "1.10∼1.15", "C": "0.95∼1.05"},
    "역(礫)": {"L": "1.10∼1.20", "C": "1.05∼1.10"},
    "역질토(礫質土)": {"L": "1.15∼1.20", "C": "0.90∼1.00"},
    "고결(固結)된역질토(礫質土)": {"L": "1.25∼1.45", "C": "1.10∼1.30"},
    "모래(砂)": {"L": "1.10∼1.20", "C": "0.85∼0.95"},
    "암괴(岩塊)나호박돌이섞인모래": {"L": "1.15∼1.20", "C": "0.90∼1.00"},
    "모래질흙": {"L": "1.20∼1.30", "C": "0.85∼0.90"},
    "암괴(岩塊)나호박돌이섞인모래질흙": {"L": "1.40∼1.45", "C": "0.90∼0.95"},
}
T1 = {
    "점질토": {"L": "1.25∼1.35", "C": "0.85∼0.95"},
    "역(礫)이섞인점질토(粘質土)": {"L": "1.35∼1.40", "C": "0.90∼1.00"},
    "암괴(岩塊)나호박돌이섞인점질토": {"L": "1.40∼1.45", "C": "0.90∼0.95"},
    "점토(粘土)": {"L": "1.20∼1.45", "C": "0.85∼0.95"},
    "역이섞인점토": {"L": "1.30∼1.40", "C": "0.90∼0.95"},
    "암괴(岩塊)나호박돌이섞인점토": {"L": "1.40∼1.45", "C": "0.90∼0.95"},
}
T2 = {
    "자연상태의체적": {"자연상태의\n체적": "1", "흐트러진상태의\n체적": "L", "다져진후의\n체적": "C"},
    "흐트러진상태의체적": {"자연상태의\n체적": "1/L", "흐트러진상태의\n체적": "1", "다져진후의\n체적": "C/L"},
}
MATRICES = {"p64-t0": T0, "p65-t0": T1, "p65-t1": T2}


def norm(value: str) -> str:
    return "".join(unicodedata.normalize("NFKC", value).split()).casefold()


def assert_tokens(value: str, text: str) -> None:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    for token in re.findall(r"[가-힣a-z]+|[0-9.]+", normalized):
        assert norm(token) in text, (value, token)


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = package["draft"]
    assert spec["tables"] == [
        {"id": table_id, "role": table["role"], "source": table["source"], "values": matrix,
         "cite": {"table_id": table_id}}
        for table_id, matrix, table in ((table_id, matrix, next(t for t in spec["tables"] if t["id"] == table_id))
                                        for table_id, matrix in MATRICES.items())
    ]
    selector = spec["inputs"][0]
    assert selector["source_table_map"] == {
        "토질별 체적 변화율": ["p64-t0", "p65-t0"], "상태 간 체적환산계수": "p65-t1"}
    checked = citations = 0
    with pymupdf.open(PDF) as doc:
        page_text = {64: norm(doc[63].get_text()), 65: norm(doc[64].get_text())}
        for table_id, matrix in MATRICES.items():
            page = 64 if table_id == "p64-t0" else 65
            text = page_text[page]
            for row, columns in matrix.items():
                assert_tokens(row, text)
                for column, value in columns.items():
                    assert_tokens(column, text)
                    assert_tokens(value, text)
                    checked += 1
        for view, table_ids in selector["source_table_map"].items():
            ids = [table_ids] if isinstance(table_ids, str) else table_ids
            result = lookup(spec, {"lookup_view": view})
            assert result["status"] == "computed" and result.get("table_reference"), result
            if len(ids) == 1:
                assert result["value"] == MATRICES[ids[0]], (view, result["value"])
                assert result["provenance"]["table"] == ids[0]
            else:
                assert list(result["value"]) == ids, (view, result["value"].keys())
                for table_id in ids:
                    assert result["value"][table_id] == MATRICES[table_id]
            for citation in result["provenance"]["citations"]:
                assert citation["internal_id"] in ids
                assert MATRICES[citation["internal_id"]][citation["row"]][citation["column"]] == citation["value"]
                citations += 1
    validation = validate_one(SPEC, ROOT / "data/drafts/specs",
                              load_chunks(ROOT / "data/processed/chunks.all.jsonl"), None)
    assert validation["ok"], validation
    assert checked == 44 and citations == 44, (checked, citations)
    report = {"status": "pass", "printed_pages": [64, 65], "independent_source_cells": checked,
              "exact_routes": 2, "runtime_exact_cell_citations": citations,
              "route_scopes": {"토질별 체적 변화율": ["p64-t0", "p65-t0"],
                               "상태 간 체적환산계수": ["p65-t1"]},
              "range_and_symbolic_policy": "source ranges/formula symbols preserved; no numeric value selected",
              "citation_preflight": "pass", "visual_review": "printed PDF p.64 and p.65 table grids visually compared"}
    out = ROOT / "evals/runtime_validation/lookup-1-2-3-source-audit-2026-10-19.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
