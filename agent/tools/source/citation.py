"""청크 위치와 원본 PDF 문장을 함께 사용한 품셈 인용."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

import pymupdf


ROOT = Path(__file__).resolve().parents[3]
ALL_CHUNKS = ROOT / "data/processed/chunks.all.jsonl"
CHUNKS = ALL_CHUNKS if ALL_CHUNKS.is_file() else ROOT / "data/processed/chunks.jsonl"
PAGE_MAP = ROOT / "data/processed/page_map.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
CODE = "2026 건설공사 표준품셈"


@lru_cache(maxsize=1)
def _chunks() -> list[dict]:
    return [json.loads(line) for line in CHUNKS.read_text(encoding="utf-8").splitlines() if line]


@lru_cache(maxsize=1)
def _pages() -> dict:
    if not PAGE_MAP.exists():
        raise FileNotFoundError(f"인쇄 쪽 대응표 없음: {PAGE_MAP}; .venv/Scripts/python.exe pipeline/page_map.py 실행")
    return json.loads(PAGE_MAP.read_text(encoding="utf-8"))["pages"]


@lru_cache(maxsize=32)
def _pdf_text(page: int) -> str:
    with pymupdf.open(PDF) as document:
        return document[page - 1].get_text("text")


def _clean_title(section: str) -> str:
    return re.sub(r"\s*\([^)]*(?:보완|신설)[^)]*\)", "", section).strip()


def _base(chunk: dict, item: str, internal_id: str) -> dict:
    pdf_page = chunk["source"]["page"]
    page = _pages()[str(pdf_page)]
    subsection = chunk.get("subsection")
    section = chunk["section"]
    clean = _clean_title(section)
    subsection_label = f"{subsection['no']}. {subsection['title']}" if subsection else None
    location = f"{clean} › {subsection_label}" if subsection_label else clean
    page_label = f"인쇄 {page['printed_page']}쪽" if page["printed_page"] is not None else f"PDF {pdf_page}쪽"
    return {
        "code": CODE, "division": page["division"], "section_no": chunk["section_no"],
        "section_title": clean.removeprefix(chunk["section_no"]).strip(), "section": section,
        "subsection": subsection_label, "item": item, "row": None, "column": None,
        "value": None, "pdf_page": pdf_page, "printed_page": page["printed_page"],
        "quote": None, "internal_id": internal_id,
        "label": f"{CODE} {page['division'] or '부문 미확인'}\n{location} ({page_label})",
    }


def cite_table(table_id: str, row: str | None = None, column: str | None = None,
               value: str | None = None) -> dict:
    """표 청크의 절·소제목·쪽을 읽어 사람이 읽는 인용을 만든다."""
    chunk = next((entry for entry in _chunks() if entry["kind"] == "table"
                  and entry["source"].get("table_id") == table_id), None)
    if chunk is None:
        raise LookupError(f"표 청크 없음: {table_id}")
    citation = _base(chunk, "표", table_id)
    citation.update(row=row, column=column, value=value)
    row_label = row
    column_label = column
    value_label = value
    if row and "슬럼프" in _pdf_text(chunk["source"]["page"]) and "기준 시공량" in chunk["text"]:
        row_label = f"슬럼프 {row}"
    if column and f"{column}구조물" in chunk["text"]:
        column_label = f"{column}구조물"
    if value and chunk.get("basis") == "(일당)" and "기준 시공량(㎥)" in chunk["text"]:
        value_label = f"{value}㎥/일"
    detail = " · ".join(str(part) for part in (row_label, column_label) if part is not None)
    if value is not None:
        detail += f" → {value_label}"
    if detail:
        citation["label"] += f"\n표: {detail}"
    return citation


def cite_page(source: dict) -> dict:
    """표 경계가 불확실한 규칙은 원문 PDF 페이지 전체를 출처 이미지로 연결한다."""
    pdf_page = int(source["pdf_page"])
    page_info = _pages()[str(pdf_page)]
    chunk = {"source": {"page": pdf_page},
             "section": f"{source['section_no']} {source.get('section_title', '재료의 할증')}",
             "section_no": source["section_no"],
             "subsection": {"no": "8", "title": source["item"]}}
    citation = _base(chunk, "표", f"p{pdf_page}")
    citation.update(row=source.get("row"), value=source.get("value"))
    citation["printed_page"] = source.get("printed_page", page_info["printed_page"])
    row, value = source.get("row"), source.get("value")
    if row or value:
        detail = " · ".join(str(part) for part in (row, value) if part)
        citation["label"] += f"\n표: {detail}"
    citation["label"] += " (쪽 전체 이미지)"
    return citation


def _section_chunk(section_no: str, subsection_no: str | None, marker: str) -> dict | None:
    candidates = [entry for entry in _chunks() if entry["kind"] == "text"
                  and entry["section_no"] == section_no
                  and (entry.get("subsection") or {}).get("no") == subsection_no]
    return next((entry for entry in candidates if marker in entry["text"]), None)


def _pdf_section(section_no: str, subsection_no: str | None) -> tuple[dict, str] | None:
    """청크 범위 밖의 공통 규칙은 원본 PDF에서 절 표제로 찾는다."""
    with pymupdf.open(PDF) as document:
        for index, page in enumerate(document):
            if index + 1 < 59 or _pages()[str(index + 1)]["printed_page"] is None:
                continue
            text = page.get_text("text")
            match = re.search(rf"(?m)^{re.escape(section_no)}\s+[^\n]+", text)
            if not match or "···" in match.group(0):
                continue
            section = match.group(0)
            start = match.end()
            if subsection_no:
                sub_match = re.search(rf"(?m)^{re.escape(subsection_no)}\.\s+[^\n]+", text[start:])
                if sub_match is None:
                    continue
                start += sub_match.end()
                subsection = {"no": subsection_no, "title": sub_match.group(0).split(".", 1)[1].strip()}
            else:
                subsection = None
            return ({"source": {"page": index + 1}, "section": section,
                     "section_no": section_no, "subsection": subsection}, text[start:])
    return None


def _extract_quote(text: str, marker: str) -> str | None:
    if marker == "본문":
        lines = [line for line in text.splitlines() if line.strip()]
        return lines[0] if lines else None
    match = re.search(rf"(?<!\S){re.escape(marker)}\s*", text)
    if match is None:
        return None
    remainder = text[match.end():]
    # 다음 주석/항목의 시작까지만 가져온다. 원본 PDF의 줄바꿈과 문자는 유지한다.
    boundary = re.search(r"(?m)(?<!\S)(?:[①②③④⑤⑥⑦⑧⑨⑩]|※|[가-하]\.|\d+\.\s+[^\n]+)", remainder)
    quote = remainder[:boundary.start()] if boundary else remainder
    return quote.strip() or None


def cite_note(section_no: str, subsection_no: str | None, marker: str) -> dict:
    """텍스트 청크로 위치를 찾고, 원본 PDF에서 주석 문장을 그대로 추출한다."""
    chunk = _section_chunk(section_no, subsection_no, marker)
    if chunk:
        pdf_text = _pdf_text(chunk["source"]["page"])
        heading = f"{subsection_no}. " if subsection_no else section_no
        start = pdf_text.find(heading)
        scoped = pdf_text[start:] if start >= 0 else pdf_text
    else:
        fallback = _pdf_section(section_no, subsection_no)
        if fallback is None:
            raise LookupError(f"절 청크·PDF 표제 없음: {section_no} / {subsection_no}")
        chunk, scoped = fallback
    quote = _extract_quote(scoped, marker)
    citation = _base(chunk, f"[주] {marker}" if marker in "①②③④⑤⑥⑦⑧⑨⑩" else marker,
                     chunk.get("chunk_id", f"PDF {chunk['source']['page']}"))
    citation["quote"] = quote
    if quote is None:
        citation["reason"] = f"원문에서 {marker} 문장을 찾지 못함"
    else:
        citation["label"] += f"\n{citation['item']} “{quote}”"
    return citation


def resolve_cite(key: dict) -> dict:
    if "table_id" in key:
        return cite_table(key["table_id"], key.get("row"), key.get("column"), key.get("value"))
    if "page_source" in key:
        return cite_page(key["page_source"])
    if "chunk_id" in key:
        chunk = next((item for item in _chunks() if item.get("chunk_id") == key["chunk_id"]), None)
        if chunk is None:
            raise LookupError(f"텍스트 청크 없음: {key['chunk_id']}")
        quote = key.get("quote")
        citation = _base(chunk, "본문", key["chunk_id"])
        citation["quote"] = quote
        if quote:
            citation["label"] += f"\n본문 “{quote}”"
        return citation
    return cite_note(key["section_no"], key.get("subsection_no"), key["marker"])


def resolve_cites(keys: dict | list[dict] | None) -> list[dict]:
    if keys is None:
        return []
    return [resolve_cite(key) for key in (keys if isinstance(keys, list) else [keys])]
