"""원본 PDF의 인쇄 쪽 번호와 부문 머리말을 전수 추출한다."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import pymupdf


ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
OUTPUT = ROOT / "data/processed/page_map.json"
DIVISIONS = ("공통부문", "토목부문", "건축부문", "기계설비부문", "유지관리부문")
KNOWN = {62: 6, 185: 129, 802: 746, 876: 820, 922: 866}


def isolated_divisions(pages: dict[str, dict]) -> list[int]:
    """Find one-page division changes between matching neighboring pages."""
    return [page for page in range(2, len(pages))
            if pages[str(page - 1)]["division"]
            and pages[str(page - 1)]["division"] == pages[str(page + 1)]["division"]
            and pages[str(page)]["division"] not in (None, pages[str(page - 1)]["division"])]


def correct_isolated_divisions(pages: dict[str, dict]) -> list[int]:
    """Correct numbered content pages; an unnumbered division title page is real."""
    corrected = []
    for page in isolated_divisions(pages):
        entry = pages[str(page)]
        if entry["printed_page"] is None:
            continue
        division = pages[str(page - 1)]["division"]
        previous = entry["division"]
        entry["division"] = division
        entry["division_reason"] = (
            f"단일 쪽 부문 이상치 보정: PDF {page - 1}·{page + 1}쪽은 {division}, "
            f"PDF {page}쪽 머리말은 {previous}")
        corrected.append(page)
    return corrected


def build_page_map(pdf_path: Path = PDF) -> dict:
    pages: dict[str, dict] = {}
    with pymupdf.open(pdf_path) as document:
        for pdf_page, page in enumerate(document, 1):
            lines = page.get_text("text").splitlines()
            # 본문/목차의 숫자를 쪽 번호로 오인하지 않도록 머리말 첫 줄만 읽는다.
            first = lines[0].strip() if lines else ""
            number = int(first) if pdf_page >= 59 and re.fullmatch(r"\d{1,4}", first) else None
            header = " ".join(lines[:4])
            division = next((name for name in DIVISIONS if name in header), None)
            chapter_match = re.search(r"제\s*\d+\s*장\s+[^\n]+", "\n".join(lines[:4]))
            pages[str(pdf_page)] = {
                "pdf_page": pdf_page, "printed_page": number, "division": division,
                "chapter": chapter_match.group(0).strip() if chapter_match else None,
                "number_reason": None if number is not None else "머리말 첫 줄에서 인쇄 쪽 번호를 찾지 못함",
                "division_reason": None if division else "해당 쪽 머리말에 부문 이름이 없음",
            }

    # 장 제목 머리말이 있는 맞은편 쪽은 앞뒤에 직접 인쇄된 같은 부문을 사용한다.
    known_divisions = {int(key): value["division"] for key, value in pages.items() if value["division"]}
    for key, entry in pages.items():
        if entry["division"] or entry["printed_page"] is None:
            continue
        index = int(key)
        before = max((i for i in known_divisions if i < index), default=None)
        after = min((i for i in known_divisions if i > index), default=None)
        if before and after and known_divisions[before] == known_divisions[after]:
            entry["division"] = known_divisions[before]
            entry["division_reason"] = f"인접 머리말 PDF {before}·{after}쪽의 같은 부문으로 보완"

    correct_isolated_divisions(pages)

    chapter = None
    division = None
    for entry in pages.values():
        if entry["division"] != division:
            chapter = None
            division = entry["division"]
        if entry["chapter"]:
            chapter = entry["chapter"]
        elif entry["printed_page"] is not None:
            entry["chapter"] = chapter

    for pdf_page, expected in KNOWN.items():
        actual = pages[str(pdf_page)]["printed_page"]
        if actual != expected:
            raise ValueError(f"PDF {pdf_page}쪽 인쇄 쪽: 기대 {expected}, 추출 {actual}")
    return {"pdf": str(pdf_path.relative_to(ROOT)).replace("\\", "/"), "pages": pages}


def summarize(page_map: dict) -> dict:
    pages = page_map["pages"].values()
    missing = [entry["pdf_page"] for entry in pages if entry["printed_page"] is None]
    offsets: dict[str, Counter] = defaultdict(Counter)
    chapter_offsets: dict[str, Counter] = defaultdict(Counter)
    for entry in pages:
        if entry["printed_page"] is not None:
            offset = entry["pdf_page"] - entry["printed_page"]
            offsets[entry["division"] or "부문 미확인"][offset] += 1
            chapter_offsets[f"{entry['division'] or '부문 미확인'} / {entry['chapter'] or '장 미확인'}"][offset] += 1
    return {"total": len(page_map["pages"]), "unreadable_count": len(missing),
            "unreadable_pages": missing, "offsets_by_division": {k: dict(v) for k, v in offsets.items()},
            "offsets_by_chapter": {k: dict(v) for k, v in chapter_offsets.items()}}


def main() -> None:
    page_map = build_page_map()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(page_map, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summarize(page_map), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
