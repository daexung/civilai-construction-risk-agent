"""Source-cell audit for the sparse-layout recovery across p.801-p.804."""
from __future__ import annotations

import json
from pathlib import Path

from extract_pdf_sparse_numeric_table import extract_sparse_numeric_table

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"


def check(condition: bool, label: str) -> None:
    print(f"{'PASS' if condition else 'FAIL'} {label}")
    if not condition:
        raise SystemExit(1)


tables = [extract_sparse_numeric_table(PDF, page, table)
          for page, table in [(801, 1), (802, 0), (802, 1),
                              (803, 0), (803, 1), (804, 0)]]
arc, arc_large, rod, rod_large, tig, tig_large = tables
expected_counts = [(arc, 15, 72, "p.801 arc labor"),
                   (arc_large, 4, 36, "p.802 large arc labor"),
                   (rod, 11, 36, "p.802 electrode"),
                   (rod_large, 8, 72, "p.803 large electrode"),
                   (tig, 20, 142, "p.803 TIG labor"),
                   (tig_large, 20, 94, "p.804 TIG labor")]
for data, row_count, cell_count, label in expected_counts:
    check(len(data["rows"]) == row_count, f"{label}: {row_count} source rows")
    check(sum(map(len, data["rows"].values())) == cell_count,
          f"{label}: {cell_count} numeric cells")

# Independently transcribed sample cells from rendered original pages.
expected = [
    (arc, "15", "40 플랜트 용접공", "0.066"),
    (arc, "15", "160 플랜트 용접공", "0.087"),
    (arc, "100", "120 플랜트 용접공", "0.325"),
    (arc, "200", "20 용접공", "0.287"),
    (arc, "350", "160 플랜트 용접공", "2.170"),
    (arc_large, "400", "20 용접공", "0.540"),
    (arc_large, "600", "160 플랜트 용접공", "5.560"),
    (rod, "15", "40 용접봉", "0.006"),
    (rod, "100", "120 용접봉", "0.730"),
    (rod, "150", "160 용접봉", "2.490"),
    (rod_large, "600", "160 용접봉", "42.100"),
    (tig, "15", "40 플랜트 용접공", "0.065"),
    (tig, "15", "40 특별인부", "0.038"),
    (tig, "200", "20 플랜트 용접공", "0.244"),
    (tig, "200", "20 특별인부", "0.143"),
    (tig_large, "100", "120 플랜트 용접공", "0.216"),
    (tig_large, "100", "120 특별인부", "0.127"),
    (tig_large, "600", "160 플랜트 용접공", "4.597"),
    (tig_large, "600", "160 특별인부", "2.692"),
]
for data, row, column, value in expected:
    check(data["rows"].get(row, {}).get(column) == value,
          f"source cell {row} / {column} = {value}")
check(not any(key.startswith("20 ") for key in arc["rows"]["15"]),
      "p.801 blank remains unmapped")
check(not any(key.startswith("100 ") for key in rod["rows"]["125"]),
      "p.802 blank remains unmapped")

out = ROOT / "evals/runtime_validation/13-2-3-sparse-pdf-extraction-audit-2026-10-19.json"
out.write_text(json.dumps({"source_pages": [801, 802, 803, 804], "tables": tables,
                           "cells_reconstructed": sum(count for _, _, count, _ in expected_counts),
                           "independent_visual_samples": len(expected),
                           "blank_cells_inferred": 0,
                           "execution_routing_verified": False},
                          ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"Saved {out.relative_to(ROOT)}; extraction is verified, full 13-2-3 rule routing remains open.")
