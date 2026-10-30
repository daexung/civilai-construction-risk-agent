"""Repair the lossy 1-6-2 extraction from source PDF row/column evidence."""
import json
import re
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
CHUNKS = ROOT / "data/processed/chunks.all.jsonl"
SPEC = ROOT / "data/drafts/specs/기계설비/1-6-2.json"


def main() -> None:
    original = fitz.open(PDF)[712].get_text()
    assert "1-6-2 폴리부틸렌(PB) 이중관 접합 및 배관" in original
    for token in ("ø16mm", "ø20mm", "0.048", "0.053", "0.021", "0.023", "1%로 계상한다"):
        assert token in original, f"원문 p.657에서 {token!r} 확인 불가"
    assert re.search(r"배\s*관\s*공", original) and re.search(r"보\s*통\s*인\s*부", original)

    records = [json.loads(line) for line in CHUNKS.read_text(encoding="utf-8").splitlines() if line.strip()]
    chunk = next(item for item in records if item["chunk_id"] == "p713-t0")
    assert chunk["source"]["page"] == 713 and chunk["section_no"] == "1-6-2"
    assert "ø20mm" not in chunk["text"] and "배관공" not in chunk["text"]
    chunk["text"] = "\n".join([
        "1-6-2 폴리부틸렌(PB) 이중관 접합 및 배관('13, '19년 보완)",
        "기준 (m당)",
        "배관공 | 단위 인 | 수량(규격) ø16mm 0.048 | ø20mm 0.053",
        "보통인부 | 단위 인 | 수량(규격) ø16mm 0.021 | ø20mm 0.023",
    ])
    CHUNKS.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in records) + "\n", encoding="utf-8")

    package = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = package["draft"]
    size = next(item for item in spec["inputs"] if item["name"] == "diameter")
    size["allowed_values"] = ["ø16mm", "ø20mm"]
    size["source"] = "PDF 657쪽 p713-t0 규격 머리글"
    table = spec["tables"][0]
    table["role"] = "관경별 작업 직종 단위 품"
    table["unit"] = "인/m"
    table["values"] = {
        "배관공": {"ø16mm": "0.048", "ø20mm": "0.053"},
        "보통인부": {"ø16mm": "0.021", "ø20mm": "0.023"},
    }
    spec["quantity_model"] = {
        "name": "per_unit",
        "params": {"unit_rate_table": {"table": "p713-t0", "row_input": None,
                                       "column_input": "diameter", "trades": ["배관공", "보통인부"],
                                       "resource_units": {"배관공": "인", "보통인부": "인"},
                                       "rate_codes": {"배관공": "1039", "보통인부": "1002"}},
                    "quantity_input": "quantity", "surcharges": [], "note_adjustments": []},
        "steps": ["관경(ø16mm/ø20mm)에 따라 배관공·보통인부의 단위당 품을 표에서 찾는다.",
                  "관경별 단위당 품에 배관 물량(m)을 곱한다.",
                  "노무비의 1%를 공구손료 및 경장비로 별도 계상한다."],
        "source": "PDF 657쪽 1-6-2 표 및 [주] ③",
        "rounding": "총 투입량은 정확한 유리수로 보존; 단위당 품은 공통 1-2-8·1-2-1 기본 자릿수 적용",
    }
    package["calc_type"] = "per_unit"
    package["calc_type_reason"] = "원문 표에서 관경별 두 직종의 m당 품을 직접 조회하여 물량을 곱하는 구조이다."
    package["open_questions"] = []
    package["questions"] = ["관경(ø16mm 또는 ø20mm)은 무엇입니까?", "배관 물량은 몇 m입니까?"]
    package["citations"] = []
    SPEC.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("recovered p713-t0 from physical PDF page 713")


if __name__ == "__main__":
    main()
