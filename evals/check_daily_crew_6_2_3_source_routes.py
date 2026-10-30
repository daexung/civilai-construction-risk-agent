"""Offline source-cell and runtime check for common 6-2-3 field assembly."""
from __future__ import annotations

import hashlib
import itertools
import json
import sys
from fractions import Fraction
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.daily_crew import adjusted_daily_crew  # noqa: E402
from backend.agent.tools.source.citation import cite_table  # noqa: E402

SPEC_PATH = ROOT / "data/drafts/specs/공통/6-2-3.json"
PDF_PATH = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
IMAGE_PATH = ROOT / "evals/runtime_validation/source-p190-6-2-3.png"
AUDIT_PATH = ROOT / "evals/runtime_validation/daily-crew-6-2-3-exact-source-routes-2026-10-19.json"

EXPECTED = {
    "토목 | 유형 Type-Ⅰ | 유형 Ⅰ-1": ("3.4", "6", "2"),
    "토목 | 유형 Ⅰ-2": ("2.2", "4", "1"),
    "토목 | 유형 Type-Ⅱ | 유형 Ⅱ-1": ("2.6", "5", "2"),
    "토목 | 유형 Ⅱ-2": ("1.1", "2", "1"),
    "토목 | 유형 Type-Ⅲ": ("2.4", "5", "2"),
    "건축 | 유형 Type-Ⅰ": ("3.4", "6", "2"),
    "건축 | 유형 Type-Ⅱ": ("3.0", "6", "2"),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))["draft"]
    table = next(table for table in spec["tables"] if table["id"] == "p190-t0")
    assert set(EXPECTED).issubset(table["values"])
    source_cells = []
    for row, (output, iron, helper) in EXPECTED.items():
        values = table["values"][row]
        normalized = {"".join(str(k).split()): str(v) for k, v in values.items()}
        expected_cells = {"시공량(ton)": output,
                          "인력(인)철근공": iron,
                          "인력(인)보통인부": helper}
        for column, value in expected_cells.items():
            assert normalized.get(column) == value, (row, column, normalized.get(column), value)
            citation = cite_table("p190-t0", row, next(
                key for key in values if "".join(str(key).split()) == column), value)
            assert citation and citation.get("pdf_page") == 190, citation
            source_cells.append({"row": row, "column": column, "value": value,
                                 "pdf_page": 190, "printed_page": 134})

    # The visually rendered original PDF page must remain the same page as the cited cells.
    pdf = pymupdf.open(PDF_PATH)
    assert pdf[189].number + 1 == 190
    pix = pdf[189].get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False)
    pix.save(IMAGE_PATH)

    routes = []
    for work_type, (output, iron, helper) in EXPECTED.items():
        inputs = {"work_type": work_type, "quantity": output,
                  "scattered_small_quantity": False, "crane_required": False,
                  "mechanical_joint_d35_welding": False}
        result = adjusted_daily_crew(spec, inputs)
        assert result.get("status") == "computed", (work_type, result)
        assert Fraction(result.get("daily_volume_m3")) == Fraction(output), (work_type, result)
        assert result.get("work_days") == "1", (work_type, result)
        assert result.get("person_days") == {
            "인력(인) 철근공": iron, "인력(인) 보통인부": helper}, (work_type, result)
        lines = {line["name"]: line for line in result.get("unit_lines", [])}
        assert set(lines) == {"인력(인) 철근공", "인력(인) 보통인부"}
        for name, expected_count in (("인력(인) 철근공", iron), ("인력(인) 보통인부", helper)):
            assert lines[name]["citations"]
            assert lines[name]["citations"][0]["value"] == expected_count
        routes.append({"work_type": work_type, "quantity_ton": output,
                       "work_days": "1", "person_days": {"철근공": iron, "보통인부": helper},
                       "source_citation_count": sum(len(line["citations"]) for line in lines.values())})

    blocked = []
    input_names = ("scattered_small_quantity", "crane_required",
                   "mechanical_joint_d35_welding")
    for work_type, (output, _, _) in EXPECTED.items():
        for flags in itertools.product((False, True), repeat=3):
            inputs = {"work_type": work_type, "quantity": output,
                      **dict(zip(input_names, flags))}
            result = adjusted_daily_crew(spec, inputs)
            if any(flags):
                assert result.get("status") == "blocked", (inputs, result)
                assert result.get("citations"), (inputs, result)
                blocked.append({"work_type": work_type, "inputs": dict(zip(input_names, flags)),
                                "status": result["status"], "reason": result.get("reason"),
                                "citation_count": len(result.get("citations", []))})
            else:
                assert result.get("status") == "computed", (inputs, result)

    audit = {
        "id": spec["id"], "status": "source_cell_and_targeted_runtime_verified",
        "source": {"pdf": str(PDF_PATH.relative_to(ROOT)), "physical_page": 190,
                   "printed_page": 134, "visual_page_image": str(IMAGE_PATH.relative_to(ROOT)),
                   "pdf_sha256": sha256(PDF_PATH), "image_sha256": sha256(IMAGE_PATH),
                   "independent_cells_checked": len(source_cells), "cells": source_cells},
        "runtime": {"exact_work_type_routes": len(routes), "routes": routes,
                    "combinations_checked": len(EXPECTED) * 8,
                    "special_condition_combinations_fail_closed": len(blocked),
                    "blocked_cases": blocked},
        "scope": "All seven work-type rows were checked against the original PDF table and direct daily_crew outputs. This does not verify other sections or every 6-2-3 cost/material rule.",
        "spec_sha256": sha256(SPEC_PATH),
        "daily_crew_sha256": sha256(ROOT / "backend/agent/tools/calc/daily_crew.py"),
    }
    AUDIT_PATH.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"routes": len(routes), "independent_cells": len(source_cells),
                      "blocked_cases": len(blocked), "audit": str(AUDIT_PATH.relative_to(ROOT))},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
