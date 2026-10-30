"""Check exact 8-3-1 category-to-table headings in the source PDF."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402
from pipeline.validate_drafts import load_chunks, validate_one  # noqa: E402

SPEC = ROOT / "data/drafts/specs/공통/8-3-1.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
ROUTES = {
    "불도저(무한궤도)": ("p285-t1", 284), "불도저(타이어)": ("p285-t2", 284),
    "유압식 리퍼": ("p285-t3", 284), "습지 불도저": ("p286-t0", 285),
    "굴착기(무한궤도)": ("p286-t1", 285), "굴착기(타이어)": ("p286-t2", 285),
    "습지굴착기(무한궤도)": ("p286-t3", 285), "대형 브레이커": ("p287-t0", 286),
    "유압식 진동콤팩터(굴착기 부착용)": ("p287-t1", 286), "압쇄기(펄버라이저)": ("p287-t2", 286),
    "트랜처": ("p287-t3", 286), "로더(무한궤도)": ("p288-t0", 287),
    "로더(타이어)": ("p288-t1", 287), "스크레이퍼(자주식)": ("p288-t2", 287),
    "스크레이퍼(피견인식)": ("p289-t0", 288), "모터그레이더(일반용)": ("p289-t1", 288),
    "모터그레이더(사리도)": ("p289-t2", 288), "덤프트럭": ("p289-t3", 288),
    "덤프트럭 자동덮개시설": ("p290-t0", 289),
}


def norm(text: str) -> str:
    return "".join(text.split())


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = package["draft"]
    field = next(f for f in spec["inputs"] if f["name"] == "machine_category")
    assert field["source_table_map"] == {name: pair[0] for name, pair in ROUTES.items()}
    assert set(field["allowed_values"]) == set(ROUTES)
    pdf = pymupdf.open(PDF)
    for category, (table_id, page_index) in ROUTES.items():
        assert table_id in {t["id"] for t in spec["tables"]}
        assert norm(category) in norm(pdf[page_index].get_text()), (category, table_id, page_index + 1)
    validation = validate_one(SPEC, ROOT / "data/drafts/specs", load_chunks(ROOT / "data/processed/chunks.all.jsonl"), None)
    assert validation["ok"], validation
    print(json.dumps({"status": "pass", "exact_heading_to_table_links": len(ROUTES),
                      "printed_pages": sorted({int(table[1:4]) for table, _ in ROUTES.values()}),
                      "matrix_value_audit": "pending; not promoted"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
