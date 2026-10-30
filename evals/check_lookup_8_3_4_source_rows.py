"""Cross-check all 8-3-4 mixing-plant rows and lookup outputs against the PDF."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402
from backend.agent.tools.calc.lookup import lookup  # noqa: E402
from pipeline.validate_drafts import load_chunks, validate_one  # noqa: E402

SPEC = ROOT / "data/drafts/specs/공통/8-3-4.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
EXPECTED = [
    ["3108-0040", "40t\n(80㎾)", "9,000", "890", "0.9", "0.75", "0.1", "1,000", "833", "668", "2,501"],
    ["3108-0060", "60t\n(120㎾)", "11,000", "890", "0.9", "0.75", "0.1", "818", "682", "659", "2,159"],
    ["3108-0080", "80t\n(160㎾)", "11,000", "890", "0.9", "0.75", "0.1", "818", "682", "659", "2,159"],
    ["3108-0100", "100t\n(200㎾)", "11,000", "890", "0.9", "0.75", "0.1", "818", "682", "659", "2,159"],
    ["3108-0120", "120t\n(240㎾)", "11,000", "890", "0.9", "0.75", "0.1", "818", "682", "659", "2,159"],
]
FIELDS = ["분류 번호", "내용\n시간", "연간표준\n가동시간", "상각\n비율", "정비\n비율",
          "연간\n관리\n비율", "시 간 당(10-7) 상각비\n계수", "시 간 당(10-7) 정비비\n계수",
          "시 간 당(10-7) 관리비\n계수", "시 간 당(10-7) 계"]


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = package["draft"]
    table = next(t for t in spec["tables"] if t["id"] == "p296-t2")
    source_row = pymupdf.open(PDF)[295].find_tables().tables[2].extract()[2]
    assert len(source_row) == 11
    raw_codes = [line.strip() for line in source_row[0].splitlines() if line.strip()]
    prefix = raw_codes[0].split("-", 1)[0] + "-"
    codes = [raw_codes[0], *(prefix + code for code in raw_codes[1:])]
    raw_specs = [line.strip() for line in source_row[1].splitlines() if line.strip()]
    source_specs = ["\n".join(raw_specs[i:i + 2]) for i in range(0, len(raw_specs), 2)]
    source_columns = [[line.strip() for line in source_row[index].splitlines() if line.strip()]
                      for index in range(2, 11)]
    assert len(codes) == len(source_specs) == 5 and all(len(col) == 5 for col in source_columns)
    for i, expected in enumerate(EXPECTED):
        observed = [codes[i], source_specs[i], *[col[i] for col in source_columns]]
        assert observed == expected, (observed, expected)

    assert len(table["values"]) == 5
    cases = 0
    for row_key, row in table["values"].items():
        code = row["분류 번호"]
        assert code in codes
        lookup_spec = next(x for x in spec["inputs"] if x["name"] == "machine_spec")
        assert row_key in lookup_spec["allowed_values"]
        result = lookup(spec, {"machine_spec": row_key})
        expected_output = dict(row)
        assert result["status"] == "computed" and result["value"] == expected_output, result
        assert len(result["provenance"]["citations"]) == len(expected_output)
        assert all(c["internal_id"] == "p296-t2" for c in result["provenance"]["citations"])
        cases += 1

    validation = validate_one(SPEC, ROOT / "data/drafts/specs",
                              load_chunks(ROOT / "data/processed/chunks.all.jsonl"), None)
    assert validation["ok"], validation
    print(json.dumps({"status": "pass", "pdf_printed_page": 240, "table_id": "p296-t2",
                      "rows_checked": len(EXPECTED), "source_cells_checked": len(EXPECTED) * 11,
                      "lookup_paths": cases, "citation_preflight": "pass"},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
