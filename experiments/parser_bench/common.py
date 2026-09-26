"""파서 비교 실험의 공통 경로·정규화·격자 변환.

파서마다 출력 형식이 달라서, 각 추출 스크립트는 표를 아래 '공통 표'로 바꿔 저장한다.
    {"id", "page", "match_iou", "bbox_pt", "n_rows", "n_cols",
     "cells": [{"r0", "r1", "c0", "c1", "text"}]}   # r1·c1은 끝을 포함하지 않는다
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
GOLDEN_DIR = ROOT / "evals/golden_tables"
RESULTS = Path(__file__).resolve().parent / "results"
PAGES_DIR = RESULTS / "pages"

# 여러 행을 묶어 보이려고 그린 괄호 글리프
BRACKETS = "⌈⌉⌊⌋┌┐└┘│├┤"


def ws(text) -> str:
    """공백·줄바꿈을 모두 지운 비교용 문자열. 그 밖의 문자는 바꾸지 않는다."""
    return re.sub(r"\s+", "", text or "")


def strip_brackets(text) -> str:
    return "".join(ch for ch in (text or "") if ch not in BRACKETS)


def lines(text) -> list[str]:
    return [line for line in (text or "").split("\n") if ws(line)]


def load_goldens() -> dict:
    goldens = {}
    for path in sorted(GOLDEN_DIR.glob("*.json")):
        golden = json.loads(path.read_text(encoding="utf-8"))
        goldens[golden["id"]] = golden
    return goldens


def iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union else 0.0


def grid_from_cells(table: dict, fill_spans: bool) -> list[list]:
    """공통 표 → 2차원 격자.

    fill_spans=False: 병합 셀 텍스트를 왼쪽 위 칸에만 두고 나머지는 None (PyMuPDF extract()와 같은 규약).
    fill_spans=True: 병합 범위의 모든 칸에 같은 텍스트를 채운다.
    """
    grid = [[None] * table["n_cols"] for _ in range(table["n_rows"])]
    # 큰 셀을 먼저 쓰고 작은 셀이 덮어쓰게 해, 겹친 셀(비고 안 중첩 표 등)은 구체적인 쪽이 남는다
    ordered = sorted(table["cells"], key=lambda c: (c["r1"] - c["r0"]) * (c["c1"] - c["c0"]), reverse=True)
    for cell in ordered:
        # 빈 칸 표기를 파서끼리 맞춘다. PyMuPDF는 None, ODL·Docling은 ''를 주는데,
        # 운영 조립 로직은 None일 때만 위 라벨을 이어받으므로 ''를 그대로 넘기면 파서 간 비교가 불공정해진다
        text = cell["text"] if (cell["text"] or "").strip() else None
        rows = range(cell["r0"], cell["r1"]) if fill_spans else [cell["r0"]]
        cols = range(cell["c0"], cell["c1"]) if fill_spans else [cell["c0"]]
        for r in rows:
            for c in cols:
                grid[r][c] = text
    return grid


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
