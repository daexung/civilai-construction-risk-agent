"""Source-cell checks for exact, single-row lookup references.

Expected values below were independently transcribed from the cited PDF table
images. This does not authorize resolving rows whose identity is ambiguous.
"""
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

PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"

# Each row and cell value was transcribed from the rendered page/table coordinates.
CASES = [
    ("공통", "2-1-2", "direct_labor_cost_band", "500억 이상", "p91-t1", 91, {
        "현 장 사 무 소 (㎡) 감독･감리자": "210",
        "현 장 사 무 소 (㎡) 수급자": "360",
        "기자재창고\n(㎡)": "100",
    }),
    ("공통", "8-2-15", "equipment_type", "법면다짐판", "p250-t0", 250, {
        "다짐력": "-", "플레이트규격(㎝)": "80×80", "작업량(㎡/h)": "22.7", "비고": "-",
    }),
    ("공통", "8-4-2", "machine_code", "1730-0015", "p333-t0", 333, {
        "기계명": "플레이트콤팩터", "규격": "1.5ton", "주연료(ℓ/hr)": "휘발유1.0",
        "잡재료(주연료의%)": "20", "조종원(인/일)": "1",
    }),
    ("공통", "8-4-7", "specification", "120ton", "p338-t1", 338, {
        "주연료\n(ℓ/hr)": "19.1", "잡재료\n(주연료의%)": "20", "조종원\n(인/일)": "1",
    }),
    ("공통", "8-5-9", "machine_type", "지능형다짐공시스템", "p358-t1", 358, {
        "분류번호": "8205-0100", "가격(￦)": "20,000",
    }),
    ("토목", "6-1-1", "construction_condition", "시공조건 C", "p419-t0", 419, {
        "품": "50%", "시공량": "200%",
    }),
    ("토목", "7-1-4", "dredger_type", "예선", "p445-t0", 445, {
        "취업시간": "〃", "운전시간": "실운전시간",
    }),
    ("토목", "9-5-8", "machine_name", "유속계", "p572-t0", 572, {
        "규격": "0∼3m/sec", "상각\n년수": "5년", "연간\n가동\n연수": "180",
        "상각\n비율": "0.9", "정비\n비율": "0.5", "연간\n관리\n비율": "0.14",
        "일 당(10-5) 상각비\n계수": "100.0", "일 당(10-5) 정비비\n계수": "55.5",
        "일 당(10-5) 관리비\n계수": "49.7", "일 당(10-5) 계": "205.2",
    }),
]


def _norm(text: object) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(text))).replace(",", "")


def main() -> int:
    pdf = pymupdf.open(PDF)
    chunks = [json.loads(line) for line in (ROOT / "data/processed/chunks.all.jsonl")
              .read_text(encoding="utf-8").splitlines() if line.strip()]
    chunk_by_table = {c.get("source", {}).get("table_id"): c for c in chunks
                      if c.get("kind") == "table"}
    checked = 0
    for division, section, field, selected, table_id, pdf_page, expected in CASES:
        package = json.loads((ROOT / "data/drafts/specs" / division / f"{section}.json")
                             .read_text(encoding="utf-8"))
        spec = package["draft"]
        table = next(t for t in spec["tables"] if t["id"] == table_id)
        exact_rows = [row for row in table["values"] if _norm(row) == _norm(selected)]
        assert len(exact_rows) == 1, (spec["id"], selected, exact_rows)
        row = exact_rows[0]
        assert {str(k): str(v) for k, v in table["values"][row].items()} == expected, (
            spec["id"], row, table["values"][row], expected)

        # Verify the row identity and all independently transcribed cell tokens are on
        # the cited PDF page. The rendered source images were checked to establish the
        # row/column association; this text assertion is only a page-content guard.
        source_text = _norm(pdf[pdf_page - 1].get_text())
        assert _norm(row) in source_text, (spec["id"], row, pdf_page)
        for value in expected.values():
            assert _norm(value) in source_text, (spec["id"], row, value, pdf_page)
        chunk = chunk_by_table[table_id]
        assert chunk["source"]["page"] == pdf_page, (table_id, chunk["source"])
        assert chunk["source"].get("bbox"), (table_id, "missing table bbox")

        result = lookup(spec, {field: selected})
        assert result["status"] == "computed" and result.get("row_reference") is True, (
            spec["id"], result)
        actual = {line["name"].split(" — ", 1)[1]: str(line["exact"])
                  for line in result["unit_lines"]}
        assert actual == expected, (spec["id"], actual, expected)
        assert all(line.get("unit") is None for line in result["unit_lines"]), (
            "row with heterogeneous columns must not inherit one table-wide unit", spec["id"])
        citations = {c["column"]: c for line in result["unit_lines"] for c in line["citations"]}
        assert set(citations) == set(expected)
        for column, value in expected.items():
            citation = citations[column]
            assert (citation["internal_id"], citation["row"], citation["column"],
                    str(citation["value"]), citation["pdf_page"]) == (
                        table_id, row, column, value, pdf_page), (spec["id"], citation)
        checked += len(expected)
    # Similar-looking row keys can identify another machine or a different code.
    # Keep these three source-scope / multi-table cases closed after row expansion.
    safety_cases = [
        ("공통", "4108-0060", {"machine_spec": "45ø"}),
        ("공통", "8201-0100", {"equipment_code": "8205-0100"}),
    ]
    for division, section, inputs in safety_cases:
        spec = json.loads((ROOT / "data/drafts/specs" / division / f"{section}.json")
                          .read_text(encoding="utf-8"))["draft"]
        result = lookup(spec, inputs)
        assert result["status"] == "unresolvable", (spec["id"], inputs, result)
    print(f"PASS exact single-row references: {len(CASES)} tables / {checked} independently transcribed cells")
    print("PASS scope guard: 2 misaligned or code-mismatched machine inputs remain unresolved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
