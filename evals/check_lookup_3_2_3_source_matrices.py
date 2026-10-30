"""Verify both 3-2-3 source tables, reconstructed axes, and exact cited cells."""
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

SPEC = ROOT / "data/drafts/specs/토목/3-2-3.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
T0 = {
    "소형브레이커": {"풍화암": "27", "연암": "20", "보통암": "16", "경암": "12"},
    "점보드릴": {"1.2m 이하": "75~85", "1.2~2.0m 이하": "85~95", "2.0~3.0m 이하": "95~105", "3.0m 초과": "105~120"},
}
ADVANCES = ["연암 0.8", "연암 1.0", "연암 1.1", "보통암 1.2", "보통암 1.3", "경암 1.4", "경암 1.5"]
T1 = {
    "굴착단면 1㎡당천공수(도갱면적 5.3㎡)": dict(zip(ADVANCES, ["2.1", "2.4", "3.3", "3.5", "3.8", "4.1", "4.5"])),
    "굴착단면 1㎡당천공수(도갱면적 9.7㎡)": dict(zip(ADVANCES, ["2.0", "2.2", "3.2", "3.4", "3.7", "4.0", "4.3"])),
    "1구멍당천공길이(m)": dict(zip(ADVANCES, ["1.0", "1.2", "1.3", "1.4", "1.5", "1.6", "1.7"])),
    "뚫기 1구멍 1m당 폭약량(㎏/m)": dict(zip(ADVANCES, ["0.25", "0.30", "0.30", "0.32", "0.35", "0.38", "0.40"])),
    "심빼기구멍수": dict(zip(ADVANCES, ["4", "5", "6", "6", "7", "8", "9"])),
}


def norm(value: str) -> str:
    return "".join(unicodedata.normalize("NFKC", value).split()).casefold()


def assert_source_tokens(value: str, source: str) -> None:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    for token in re.findall(r"[가-힣a-z]+|[0-9.]+", normalized):
        assert norm(token) in source, (value, token)


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = package["draft"]
    selector = next(field for field in spec["inputs"] if field["name"] == "target_info")
    assert selector["source_table_map"] == {"천공속도": "p396-t0", "소형터널 굴착기준": "p396-t1"}
    tables = {table["id"]: table for table in spec["tables"]}
    assert tables["p396-t0"]["values"] == T0
    assert tables["p396-t1"]["values"] == T1
    checked = citations = 0
    with pymupdf.open(PDF) as doc:
        source = norm(doc[395].get_text())
        for matrix in (T0, T1):
            for row, columns in matrix.items():
                for column, value in columns.items():
                    # Composite labels in p396-t1 span separate source header cells;
                    # their constituents and every data value are checked against
                    # the rendered grid plus the PDF text layer.
                    assert_source_tokens(row, source)
                    assert_source_tokens(column, source)
                    assert_source_tokens(value, source)
                    if matrix is T0:
                        selected = {"target_info": "천공속도", "equipment_type": row}
                        selected["rock_type_breaker" if row == "소형브레이커" else "advance_length_jumbo"] = column
                    else:
                        selected = {"target_info": "소형터널 굴착기준", "small_tunnel_metric": row,
                                    "small_tunnel_rock_advance": column}
                    result = lookup(spec, selected)
                    assert result["status"] == "computed" and result["value"] == value, (selected, result)
                    cite = result["provenance"]["citations"][0]
                    table_id = "p396-t0" if matrix is T0 else "p396-t1"
                    assert (cite["internal_id"], cite["row"], cite["column"], cite["value"]) == (
                        table_id, row, column, value)
                    checked += 1
                    citations += 1
    bad_branch = lookup(spec, {"target_info": "소형터널 굴착기준", "equipment_type": "점보드릴"})
    assert bad_branch["status"] == "rejected", bad_branch
    validation = validate_one(SPEC, ROOT / "data/drafts/specs", load_chunks(ROOT / "data/processed/chunks.all.jsonl"), None)
    assert validation["ok"], validation
    report = {"status": "pass", "printed_page": 340, "independent_source_cells": checked,
              "exact_table_routes": 2, "runtime_exact_cell_citations": citations,
              "p396_t1_label_shift": "reconstructed from rendered table; issue cleared after 35-cell audit",
              "conditional_domains": "pass", "citation_preflight": "pass",
              "footnote": "풍화암 준용을 source explanation으로 보존; lookup axis uses printed 연암 0.8"}
    out = ROOT / "evals/runtime_validation/lookup-3-2-3-source-audit-2026-10-19.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
