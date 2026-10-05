"""명세에서 참조하는 표를 PDF bbox로 미리 PNG로 만든다."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pymupdf


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.rules.specs import load_specs  # noqa: E402
from agent.tools.source.citation import CHUNKS  # noqa: E402
SPECS = ROOT / "agent/rules/specs"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
OUTPUT = ROOT / "data/processed/sources"
MATERIAL_ALLOWANCES = ROOT / "data/rates/material_allowance.json"
MARGIN = 12
SCALE = 3


def render_source(source_id: str, output_dir: Path = OUTPUT) -> Path:
    """요청된 표는 bbox로, 텍스트 조각은 쪽 전체로 렌더링한다."""
    match = re.fullmatch(r"p(\d+)(?:-([tx])\d+)?", source_id)
    if not match:
        raise LookupError(f"출처 id 형식 오류: {source_id}")
    page_no = int(match.group(1))
    kind = match.group(2)
    chunk = None
    if kind:
        chunk = next((item for line in CHUNKS.read_text(encoding="utf-8").splitlines()
                      if (item := json.loads(line)).get("chunk_id") == source_id), None)
        if chunk is None or chunk["kind"] != ("table" if kind == "t" else "text"):
            raise LookupError(f"출처 조각 없음: {source_id}")
        page_no = chunk["source"]["page"]
    with pymupdf.open(PDF) as document:
        if page_no < 1 or page_no > len(document):
            raise LookupError(f"PDF 쪽 범위 오류: {page_no}")
        page = document[page_no - 1]
        rect = page.rect
        if kind == "t":
            bbox = chunk["source"].get("bbox")
            if not bbox or len(bbox) != 4:
                raise LookupError(f"표 bbox 없음: {source_id}")
            box = pymupdf.Rect(bbox)
            rect = pymupdf.Rect(box.x0 - MARGIN, box.y0 - MARGIN,
                                box.x1 + MARGIN, box.y1 + MARGIN) & page.rect
            if rect.is_empty:
                raise LookupError(f"표 bbox 범위 오류: {source_id}")
        output_dir.mkdir(parents=True, exist_ok=True)
        output = output_dir / f"{source_id}.png"
        page.get_pixmap(matrix=pymupdf.Matrix(SCALE, SCALE), clip=rect, alpha=False).save(output)
    return output


def referenced_tables() -> set[str]:
    return {table["id"] for spec in load_specs().values() for table in spec.get("tables", [])}


def referenced_pages() -> set[int]:
    if not MATERIAL_ALLOWANCES.is_file():
        return set()
    rules = json.loads(MATERIAL_ALLOWANCES.read_text(encoding="utf-8"))
    return {int(rule["source"]["pdf_page"]) for rule in rules.get("rules", [])}


def render() -> list[Path]:
    tables = referenced_tables()
    pages = referenced_pages()
    chunks = {}
    for line in CHUNKS.read_text(encoding="utf-8").splitlines():
        chunk = json.loads(line)
        table_id = chunk["source"].get("table_id")
        if table_id in tables:
            chunks[table_id] = chunk
    missing = tables - chunks.keys()
    if missing:
        raise LookupError(f"표 청크 없음: {sorted(missing)}")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    outputs = []
    with pymupdf.open(PDF) as document:
        for table_id, chunk in sorted(chunks.items()):
            if not re.fullmatch(r"p\d+-t\d+", table_id):
                raise ValueError(f"표 id 형식 오류: {table_id}")
            bbox = chunk["source"].get("bbox")
            if not bbox or len(bbox) != 4:
                raise ValueError(f"표 bbox 없음: {table_id}")
            page = document[chunk["source"]["page"] - 1]
            rect = pymupdf.Rect(bbox)
            rect = pymupdf.Rect(rect.x0 - MARGIN, rect.y0 - MARGIN,
                                rect.x1 + MARGIN, rect.y1 + MARGIN) & page.rect
            if rect.is_empty:
                raise ValueError(f"표 bbox 범위 오류: {table_id}")
            output = OUTPUT / f"{table_id}.png"
            page.get_pixmap(matrix=pymupdf.Matrix(SCALE, SCALE), clip=rect, alpha=False).save(output)
            outputs.append(output)
        for pdf_page in sorted(pages):
            if pdf_page < 1 or pdf_page > len(document):
                raise ValueError(f"PDF 쪽 범위 오류: {pdf_page}")
            output = OUTPUT / f"p{pdf_page}.png"
            document[pdf_page - 1].get_pixmap(matrix=pymupdf.Matrix(SCALE, SCALE), alpha=False).save(output)
            outputs.append(output)
    return outputs


if __name__ == "__main__":
    for path in render():
        print(path.relative_to(ROOT))
