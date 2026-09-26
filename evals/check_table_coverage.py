"""185~214쪽의 내용 있는 표가 레코드 없이 사라지지 않는지 검사한다.

실행: python evals/check_table_coverage.py
"""

import sys
from collections import defaultdict
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
from parse import parse_pages  # noqa: E402

PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
START, END = 185, 214

# 앞뒤 쪽에 이어지는 표의 머리글 한 줄뿐이므로 행 레코드가 없다.
EXCEPTIONS = {"p198-t0": "머리글 '구조물 | 적용면적(㎡)' 한 줄뿐인 이어지는 표"}

REQUIRED_TEXT = {
    "p187-t2": ("매트기초", "Type"),
    "p189-t1": ("직경 13mm", "철근"),
    "p191-t1": ("10%", "20%"),
    "p192-t3": ("6.99", "0.62"),
    "p193-t1": ("50∼60",),
}


def main() -> int:
    records = parse_pages(str(PDF), START, END)
    by_table = defaultdict(list)
    for record in records:
        if record.get("kind") == "table":
            by_table[record["table_id"]].append(record)

    failed = []
    checked = 0
    with pymupdf.open(PDF) as doc:
        for page_no in range(START, END + 1):
            for index, table in enumerate(doc[page_no - 1].find_tables().tables):
                table_id = f"p{page_no}-t{index}"
                grid = table.extract()
                if not any(cell and cell.strip() for row in grid for cell in row):
                    continue
                if table_id in EXCEPTIONS:
                    continue
                checked += 1
                if not by_table[table_id]:
                    failed.append(f"{table_id}: 내용 있는 표의 레코드 0개")

    for table_id, words in REQUIRED_TEXT.items():
        texts = "\n".join(row["text"] for row in by_table[table_id])
        missing = [word for word in words if word not in texts]
        if missing:
            failed.append(f"{table_id}: 원문 글자 누락 {missing}")

    for table_id in ("p187-t2", "p189-t1"):
        if not by_table[table_id] or any(
            row.get("structure", {}).get("status") != "uncertain"
            or "header_fallback" not in row.get("structure", {}).get("issues", [])
            for row in by_table[table_id]
        ):
            failed.append(f"{table_id}: 글자 표의 header_fallback/uncertain 표시 누락")

    for table_id in ("p191-t1", "p192-t3", "p193-t1"):
        if not by_table[table_id] or any(
            row.get("structure", {}).get("status") != "uncertain"
            or "header_extended_numeric" not in row.get("structure", {}).get("issues", [])
            for row in by_table[table_id]
        ):
            failed.append(f"{table_id}: 확장 숫자 판정의 uncertain 표시 누락")

    print(f"검사 대상: 내용 있는 표 {checked}개, 예외 {len(EXCEPTIONS)}개")
    for reason in failed:
        print(f"FAIL {reason}")
    if failed:
        print(f"실패 {len(failed)}건")
        return 1
    print("통과: 내용 있는 표의 레코드·대표 원문 글자·fallback 상태")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
