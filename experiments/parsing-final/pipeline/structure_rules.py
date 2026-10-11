"""표 구조 판정에 쓰는 PDF 위치 확인과 공통 상수.

PDF 쪽을 읽기 전용으로 열어 (1) 쪽 크기, (2) 칸 안 글자의 실제 기준선 위치, (3) 머리글 음영만 읽는다.
표를 새로 추출하지 않는다. ODL 출력의 칸·행을 PDF 글자층 위치로 확인하는 용도다.

사용 위치
  - odl_tables.to_common(probe=...)   행 분리 판정에 실제 기준선을 쓴다(문단 높이 추정 대신)
  - structure_store                   쪽 높이, 머리글 음영
"""
from pathlib import Path

import pymupdf

# ALIGN_TOL: 같은 행으로 보는 기준선 차이(pt). 실제 표에서 같은 행의 글자 기준선은 0.00,
# 줄바꿈된 이름 칸은 행 간격과 달라 0.6pt 이상이었다(odl_tables에 정의)
from odl_tables import ALIGN_TOL  # noqa: E402,F401  (행 분리 판정과 같은 값)
# 같은 줄로 묶는 글자 기준선 차이(글자 높이의 비율)
LINE_GAP_RATIO = 0.35
# 칸 안 글자를 고를 때 칸 경계에 주는 여유(pt)
CELL_MARGIN = 1.0


class PdfProbe:
    """PDF 쪽의 실제 글자 위치를 읽는다. 쪽마다 한 번만 읽어 둔다."""

    def __init__(self, pdf_path):
        self.path = Path(pdf_path)
        self.doc = pymupdf.open(self.path)
        self._chars: dict[int, list] = {}
        self._shades: dict[int, list] = {}
        self.pages_read: set[int] = set()

    def close(self) -> None:
        self.doc.close()

    def page_size(self, page: int) -> tuple[float, float]:
        rect = self.doc[page - 1].rect
        self.pages_read.add(page)
        return rect.width, rect.height

    def page_height(self, page: int) -> float:
        return self.page_size(page)[1]

    def shades(self, page: int) -> list:
        if page not in self._shades:
            import assemble
            self._shades[page] = assemble.header_shades(self.doc[page - 1])
            self.pages_read.add(page)
        return self._shades[page]

    def _page_chars(self, page: int) -> list:
        if page not in self._chars:
            out = []
            for block in self.doc[page - 1].get_text("rawdict")["blocks"]:
                for line in block.get("lines", []):
                    for span in line["spans"]:
                        for ch in span["chars"]:
                            if ch["c"].strip():
                                x0, y0, x1, y1 = ch["bbox"]
                                out.append(((x0 + x1) / 2, ch["origin"][1], y1 - y0, ch["c"]))
            self._chars[page] = out
            self.pages_read.add(page)
        return self._chars[page]

    def baselines(self, page: int, bbox_native) -> list[float]:
        """칸(ODL 좌표, 왼쪽 아래 원점) 안 글자의 줄 기준선을 위에서 아래 순서로 낸다. 같은 좌표계(왼쪽 아래 원점)로 돌려준다."""
        height = self.page_height(page)
        x0, y0, x1, y1 = bbox_native
        top, bottom = height - y1, height - y0       # 왼쪽 위 원점 좌표
        chars = sorted((c for c in self._page_chars(page)
                        if x0 - CELL_MARGIN <= c[0] <= x1 + CELL_MARGIN and top - CELL_MARGIN <= c[1] <= bottom + CELL_MARGIN),
                       key=lambda c: c[1])
        lines: list[list] = []
        for c in chars:
            if lines and abs(c[1] - sum(x[1] for x in lines[-1]) / len(lines[-1])) <= LINE_GAP_RATIO * c[2]:
                lines[-1].append(c)
            else:
                lines.append([c])
        return [round(height - sum(x[1] for x in line) / len(line), 2) for line in lines]

    __call__ = baselines
