"""ODL 경로의 새 조립: 공통 표 → 레코드 (전환 계획 P4).

parse.py의 table_to_records와 같은 레코드 글자 형식("절 | 라벨 | 열이름 값 | ...")을 만든다.
parse.py는 이 모듈을 쓰지 않으며, parse.py의 함수는 가져다 쓰기만 한다.

현행 조립과 다른 점:
  1. 머리글 판정: 표 머리글 칸에 깔린 회색 음영으로 정한다. 음영이 없는 표만 현행 규칙
     (숫자 칸이 처음 나오는 행 앞까지)을 쓴다. 현행 규칙은 '5만㎡'·'(1)'·'4이하'처럼 순수 숫자가 아닌 값에서
     머리글을 과다 계산하고, '50이하 100 150'처럼 숫자가 든 머리글에서 과소 계산한다.
  2. 쌓인 행 풀기: 하위 행 수는 숫자 칸의 줄 수로 정한다. 숫자 칸이 없으면 줄바꿈된 글자로 보고 잇는다.
     첫 열은 줄마다 다른 글자로 된 행 라벨 열(재료명·상태 등)이 따로 있으면 여러 행에 걸친 조건으로 본다.
  3. 괄호 기호(⌉⌋ 등)로 묶인 공유 값: 기호를 지우고 묶음의 첫 행에만 한 번 붙인다(이중 계상 방지).
  4. 값 없이 라벨만 있는 행: 다음 행 라벨 앞에 붙인다(두 줄 공정명이 두 행으로 쪼개진 경우).
"""
import re
from collections import Counter

from parse import (NUMERIC_RE, clean_cell, count_header_rows, read_text_blocks, read_titles,
                   title_above)

BRACKETS = "⌈⌉⌊⌋┌┐└┘│├┤"
VALUE_RE = re.compile(r"^(?:[-–〃]|\(?\d[\d.,\-]*\)?(?:[~∼]\d[\d.,]*)?(?:%|이하|이상|미만|초과)?)$")
CONTINUATION_PREFIXES = ("-", "(", "※")
SHADE_GRAY = (0.80, 0.95)   # 머리글 음영 회색 범위(쪽 아래 막대 0.76은 제외)


def header_shades(page) -> list[tuple[float, float, float, float]]:
    """쪽에 깔린 머리글 음영 사각형(왼쪽 위 원점)."""
    shades = []
    for drawing in page.get_drawings():
        fill = drawing.get("fill")
        if not fill or not all(SHADE_GRAY[0] <= c <= SHADE_GRAY[1] for c in fill):
            continue
        for item in drawing["items"]:
            if item[0] == "re":
                r = item[1]
                shades.append((r.x0, r.y0, r.x1, r.y1))
    return shades


def in_shade(box, shades, tol: float = 1.0) -> bool:
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return any(s[0] - tol <= cx <= s[2] + tol and s[1] - tol <= cy <= s[3] + tol for s in shades)


def to_grid(table: dict) -> tuple[list[list[str | None]], list[list[bool]]]:
    """병합 범위를 채운 격자와, 칸마다 괄호 기호가 있었는지 표시."""
    grid = [[None] * table["n_cols"] for _ in range(table["n_rows"])]
    bracket = [[False] * table["n_cols"] for _ in range(table["n_rows"])]
    for cell in sorted(table["cells"], key=lambda c: (c["r1"] - c["r0"]) * (c["c1"] - c["c0"]), reverse=True):
        text = cell["text"] if (cell["text"] or "").strip() else None
        has_bracket = bool(text) and any(ch in BRACKETS for ch in text)
        for r in range(cell["r0"], cell["r1"]):
            for c in range(cell["c0"], cell["c1"]):
                grid[r][c] = text
                bracket[r][c] = has_bracket
    return grid, bracket


def clean(cell):
    """현행 clean_cell(한 글자씩 띄운 줄 붙이기, 괄호 기호만 있는 줄 버리기) + 줄 안의 괄호 기호 지우기."""
    if cell is None:
        return None
    cell = "\n".join(line.strip() for line in "".join(ch for ch in cell if ch not in BRACKETS).split("\n"))
    cell = clean_cell(cell)
    return cell if cell and cell.strip() else None


def count_header(table: dict, grid: list, shades: list) -> tuple[int, str]:
    """머리글 행 수와 판정 근거."""
    if shades and all("bbox_pt" in c for c in table["cells"]):
        count, prev = 0, False
        for r in range(table["n_rows"]):
            starting = [c for c in table["cells"] if c["r0"] == r]
            shaded = (sum(in_shade(c["bbox_pt"], shades) for c in starting) * 2 >= len(starting)) if starting else prev
            if not shaded:
                break
            count, prev = count + 1, shaded
        if 0 < count < table["n_rows"]:
            return count, "음영"
    return count_header_rows(grid), "숫자 규칙"


def column_names(header_rows: list, col_count: int) -> list[str]:
    names = []
    for col in range(col_count):
        parts = []
        for row in header_rows:
            value = row[col]
            if value and value.replace("\n", " ") not in parts:
                parts.append(value.replace("\n", " "))
        names.append(" ".join(parts))
    return names


def join_continuations(lines: list[str]) -> list[str]:
    out = []
    for line in lines:
        if out and line.strip().startswith(CONTINUATION_PREFIXES):
            out[-1] = f"{out[-1]} {line}"
        else:
            out.append(line)
    return out


def is_value_lines(lines: list[str]) -> bool:
    return len(lines) >= 2 and all(VALUE_RE.match(re.sub(r"\s+", "", line)) for line in lines)


def is_row_label_lines(lines: list[str], depth: int) -> bool:
    """줄마다 다른, 숫자 없는 글자 줄 → 행 라벨 열(재료명 'Epoxy…/시너', 상태 '軟質/硬質')."""
    return (len(lines) == depth and len(set(lines)) == depth
            and not any(re.search(r"\d", line) for line in lines))


# 행 라벨 열이 아닌 열: 단위·규격 열은 줄마다 다른 글자여도 행 라벨이 아니다(668쪽 '매/%')
NOT_LABEL_HEADERS = ("단위", "규격")


def unstack(row: list, bracket: list, names: list[str]) -> list[list[str | None]]:
    """한 행에 쌓인 하위 행을 푼다. 반환은 하위 행 목록."""
    stacks = [cell.split("\n") if cell else [] for cell in row]
    numeric = [c for c in range(1, len(row)) if is_value_lines(stacks[c])]
    if not numeric:
        # 여러 행이 쌓인 것이 아니라 칸 안 줄바꿈이다(500쪽 '(50,000×0.65 / ÷120)=270')
        return [[" ".join(s) if s else None for s in stacks]]
    counts = Counter(len(stacks[c]) for c in numeric)
    depth = max(counts, key=lambda n: (counts[n], n))

    labels = join_continuations(stacks[0]) if stacks[0] else []
    has_row_label_col = any(row[c] != row[0] and is_row_label_lines(stacks[c], depth)
                            and not any(h in re.sub(r"\s+", "", names[c]) for h in NOT_LABEL_HEADERS)
                            for c in range(1, len(row)) if c not in numeric)
    label_per_row = not has_row_label_col and len(labels) == depth

    out = []
    for i in range(depth):
        sub = []
        for c, s in enumerate(stacks):
            if c == 0:
                sub.append(labels[i] if label_per_row else (" ".join(labels) or None))
            elif len(s) == depth:
                sub.append(s[i] or None)
            elif not s:
                sub.append(None)
            elif bracket[c]:
                # 괄호 기호로 묶인 공유 값: 묶음의 첫 행에만 한 번
                sub.append(" ".join(s) if i == 0 else None)
            else:
                sub.append(" ".join(s))
        out.append(sub)
    return out


def table_to_records(table: dict, shades: list, section_title: str, page_no: int) -> list[dict]:
    raw_grid, bracket = to_grid(table)
    grid = [[clean(c) for c in row] for row in raw_grid]
    header_count, _ = count_header(table, grid, shades)
    names = column_names(grid[:header_count], table["n_cols"])

    # 값 없이 라벨만 있는 행은 다음 행 라벨 앞에 붙인다. 이어받기보다 먼저 해야
    # 그 아래 행들도 합친 라벨을 이어받는다(872쪽 '거푸집하부용' + '앵커설치')
    rows, carry = [], None
    for row, br in zip(grid[header_count:], bracket[header_count:]):
        row = list(row)
        if row[0] and all(c is None for c in row[1:]):
            carry = row[0] if carry is None else f"{carry} {row[0]}"
            continue
        if carry:
            row[0] = f"{carry} {row[0]}" if row[0] else carry
            carry = None
        rows.append((row, br))

    # 첫 열 이어받기(현행 clean_table과 같은 규칙)
    label, merged = None, []
    for row, br in rows:
        if row[0] is not None:
            label = row[0]
        elif label is not None and any(c is not None for c in row):
            row[0] = label
        merged.append((row, br))

    records, note_written = [], False
    for row, br in merged:
        label = (row[0] or "").replace("\n", " ").strip()
        if label == "비고":
            if note_written:
                continue
            note_written = True
            note = next((cell for cell in row[1:] if cell), "")
            records.append({"text": f"{section_title} | 비고 | {note}".replace("\n", " "),
                            "section": section_title, "page": page_no})
            continue
        for sub in unstack(row, br, names):
            row_label = (sub[0] or "").replace("\n", " ").strip()
            if row_label and names[0] and NUMERIC_RE.match(row_label):
                parts = [section_title, f"{names[0]} {row_label}"]
            else:
                parts = [section_title, row_label]
            for col in range(1, len(sub)):
                value = (sub[col] or "").replace("\n", " ").strip()
                if value in ("", "-"):
                    continue
                name = names[col].strip()
                skip_name = not name or name == names[0].strip()
                parts.append(value if skip_name else f"{name} {value}")
            records.append({"text": " | ".join(parts), "section": section_title, "page": page_no})
    return records


def parse_pages(pdf_path, start_page: int, end_page: int, tables_by_page: dict) -> list[dict]:
    """parse.parse_pages와 같은 흐름. 표만 ODL 경로(tables_by_page)와 새 조립을 쓴다."""
    import pymupdf

    records, last_title = [], ""
    with pymupdf.open(pdf_path) as doc:
        for page_no in range(start_page, end_page + 1):
            page = doc[page_no - 1]
            titles = read_titles(page)
            tables = tables_by_page.get(page_no, [])
            shades = header_shades(page)
            items = [(t["bbox_pt"][1], "table", t) for t in tables]
            items += [(y, "text", text) for y, text in read_text_blocks(page, [t["bbox_pt"] for t in tables])]
            for top, kind, content in sorted(items, key=lambda item: item[0]):
                title = title_above(titles, top) or last_title
                last_title = title
                if kind == "table":
                    records += table_to_records(content, shades, title, page_no)
                else:
                    records.append({"text": f"{title} | 설명 | {content}", "section": title, "page": page_no})
            if titles:
                last_title = titles[-1][1]

    seen, unique = set(), []
    for record in records:
        if record["text"] not in seen:
            seen.add(record["text"])
            unique.append(record)
    return unique
