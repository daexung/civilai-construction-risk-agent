"""Audit coordinate recovery of the merged diameter axis on source p.723."""
from __future__ import annotations

import json
from pathlib import Path

from extract_pdf_sparse_numeric_table import extract_sparse_numeric_table

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
TABLE = extract_sparse_numeric_table(PDF, 779, 0, row_label_column=1)


def check(condition: bool, label: str) -> None:
    print(f"{'PASS' if condition else 'FAIL'} {label}")
    if not condition:
        raise SystemExit(1)


check(len(TABLE["rows"]) == 20, "p.723 merged first column reconstructed as 20 exact diameter rows")
check(sum(map(len, TABLE["rows"].values())) == 140,
      "20 rows × seven exact data columns reconstructed")
expected_headers = ["외경 ㎜", "두께 ㎜", "단위 중량 ㎏/m",
                    "배 관 구 분 옥 내 배 관 용접식 플랜트 용접공",
                    "배 관 구 분 옥 내 배 관 용접식 플랜트 배관공",
                    "배 관 구 분 옥 내 배 관 용접식 특별 인부",
                    "배 관 구 분 옥 내 배 관 나사식 플랜트 배관공"]
check(TABLE["headers"] == expected_headers, "multilevel header hierarchy preserved as exact composite source axes")
samples = {"6": {"외경 ㎜": "10.5", "두께 ㎜": "2.0", "단위 중량 ㎏/m": "0.419",
                 expected_headers[3]: "92.0", expected_headers[4]: "46.0",
                 expected_headers[5]: "46.0", expected_headers[6]: "92.0"},
           "300": {"외경 ㎜": "318.5", "두께 ㎜": "6.9", "단위 중량 ㎏/m": "53.0",
                   expected_headers[3]: "17.8", expected_headers[4]: "9.3",
                   expected_headers[5]: "9.3", expected_headers[6]: "17.8"}}
for row, expected in samples.items():
    for column, value in expected.items():
        check(TABLE["rows"][row].get(column) == value,
              f"independent original cell row {row} / {column} = {value}")

out = ROOT / "evals/runtime_validation/13-1-1-p779-coordinate-extraction-audit-2026-10-19.json"
out.write_text(json.dumps({"source_page": 779, "printed_page": 723,
                           "rows_reconstructed": 20, "numeric_cells_reconstructed": 140,
                           "independent_cells_checked": sum(map(len, samples.values())),
                           "tables": [TABLE], "blank_cells_inferred": 0,
                           "execution_routing_verified": False,
                           "open_scope": ["per-ton lower table row basis", "outdoor/other pipe material routes",
                                          "source notes and adjustments"]},
                          ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"Saved {out.relative_to(ROOT)}; confirms table recovery, not a complete 13-1-1 calculator path.")
