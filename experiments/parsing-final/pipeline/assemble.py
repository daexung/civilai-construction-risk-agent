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

표 구조 보존 작업(2026-10-10)에서 바꾼 점:
  5. 행 분리 판정을 한 곳(unstack)에서 근거와 함께 남긴다. 어댑터(odl_tables.split_row)가 이미 나눈 행은
     다시 나누지 않고, 줄 수가 우연히 같은 글자 칸끼리는 줄바꿈된 이름으로 본다(555쪽 가짜 작업 행 원인).
  6. table_to_records(trace=True)는 레코드마다 원래 칸 번호와 글 조각을 함께 낸다.
  7. 숫자 칸이 없어 본문이 통째로 사라지던 표는 운영 parse.py와 같은 규칙(첫 줄만 머리글)으로 내용을 남긴다.
  8. 끝까지 값 없이 남은 라벨 행도 글을 잃지 않게 레코드로 남긴다.
  9. 비고 라벨 칸이 여러 열에 걸치면 라벨 자신을 비고 글로 읽어 실제 문장을 잃던 것을 고친다(951쪽).
"""
import re
from collections import Counter

from parse import (NUMERIC_RE, clean_cell, read_text_blocks, read_titles, table_header_count,
                   title_above)

BRACKETS = "⌈⌉⌊⌋┌┐└┘│├┤"
VALUE_RE = re.compile(r"^(?:[-–〃]|\(?\d[\d.,\-]*\)?(?:[~∼]\d[\d.,]*)?(?:%|이하|이상|미만|초과)?)$")
# 단위가 붙은 수치: '27 ㎝/min', '1.2∼2.0m 이하', '0.2㎥', '10ton'
VALUE_UNIT_RE = re.compile(r"^\(?\d[\d.,]*\)?(?:\s*[~∼]\s*\d[\d.,]*)?\s*[A-Za-z㎝㎜㎡㎥㎏%/·ℓ]*\s*(?:이하|이상|미만|초과)?$")
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
    # 변경: 원문 대조로 머리글 끝을 지정한 표(표별 교정 자료)
    if table.get("header_override") is not None:
        return table["header_override"], "원문 대조 지정"
    # Two-column key/value lists have a shaded row label, not a header row.
    # Treat the listed subjects as body text rather than swallowing them as column names.
    if table["n_cols"] == 2 and grid and clean(grid[0][0]) == "항목":
        if grid[0][1] and re.search(r"\d+-\d+(?:-\d+)?\s+\S", grid[0][1]):
            return 0, "항목 목록(머리글 없음)"
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
    # 숫자 칸이 없어 본문이 사라지던 표는 운영 parse.py와 같은 규칙으로 첫 줄만 머리글로 둔다
    count, issue = table_header_count(grid)
    # Keep explicit shaded headers authoritative. Numeric column headings occur
    # in unshaded coefficient reference tables, with one or two heading rows.
    if count == 0 and grid and table["n_cols"] >= 3:
        first = clean(grid[0][0]) or ""
        if re.search(r"\((?:㎏|kg|㎡|㎥|m|mm|㎜|ton|t)\)", first, re.I):
            for r in range(1, min(3, len(grid))):
                label = clean(grid[r][0]) or ""
                if re.match(r"^(?:보정치|보정계수|계수)(?:\(|$)", label):
                    values = [clean(x) for x in grid[r][1:] if clean(x)]
                    if values and all(NUMERIC_RE.match(x) for x in values):
                        return r, "단위 제목과 계수 행 경계"
    return count, issue or "숫자 규칙"


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


def shared_value_depth(row: list, stacks: list[list[str]]) -> int:
    """첫 열을 뺀 칸 중 둘 이상이 같은 줄 수(≥2)로 쌓였고 그중 하나가 단위 붙은 수치 칸이면 그 줄 수.

    한 칸만 여러 줄이면 줄바꿈이다(334쪽 규격 '10ton / (0.29)'). 병합으로 복사된 칸은 한 칸으로 센다.
    글자 줄 중 '-'·'('·'※'로 시작하는 줄은 앞 줄에 이어 센다(수치 줄은 그대로).
    """
    counts, value_counts, prev = Counter(), set(), object()
    for c in range(1, len(row)):
        if row[c] == prev or row[c] == row[0] or len(stacks[c]) < 2:
            prev = row[c]
            continue
        prev = row[c]
        lines = stacks[c]
        if all(VALUE_UNIT_RE.match(line.strip()) for line in lines):
            value_counts.add(len(lines))
        else:
            lines = join_continuations(lines)
        counts[len(lines)] += 1
    shared = [n for n, k in counts.items() if n > 1 and k >= 2 and n in value_counts]
    return max(shared, default=0)


def digits_in_every_line(lines: list[str]) -> bool:
    return bool(lines) and all(re.search(r"\d", line) for line in lines)


def unstack(row: list, bracket: list, names: list[str], allow_split: bool = True,
            info: dict | None = None) -> list[list[str | None]]:
    """한 행에 쌓인 하위 행을 푼다. 반환은 하위 행 목록.

    판정 근거는 info["basis"]에 남긴다(table_to_records가 레코드 추적에 싣는다).
      adapter        어댑터(odl_tables.split_row)가 나눈 행(table_to_records가 표시). 조립은 다시 나누지 않는다
      not_split      어댑터가 한 줄 행으로 본 행이라 나누지 않았다(allow_split=False)
      value_lines    숫자 칸이 같은 줄 수로 쌓였다
      shared_value   단위 붙은 수치 칸이 둘 이상 같은 줄 수로 쌓였다
      line_count     첫 열과 줄 수가 같은 칸에 값(숫자가 든 줄)이 같은 줄 수로 쌓였다
      label_wrap     줄 수가 같은 글자 칸끼리뿐이라 줄바꿈된 이름으로 보고 나누지 않았다
      single         쌓인 칸이 없다
    """
    info = {} if info is None else info
    info.update(depth=1, basis="single")
    stacks = [cell.split("\n") if cell else [] for cell in row]
    if not allow_split:
        info["basis"] = "not_split"
        return [[" ".join(s) if s else None for s in stacks]]
    numeric = [c for c in range(1, len(row)) if is_value_lines(stacks[c])]
    if numeric:
        counts = Counter(len(stacks[c]) for c in numeric)
        depth = max(counts, key=lambda n: (counts[n], n))
        info["basis"] = "value_lines"
    elif (depth := shared_value_depth(row, stacks)) > 1:
        # 단위가 붙은 수치 칸과 같은 줄 수로 쌓인 칸이 또 있으면 여러 행이다
        # (396쪽 첫 표: 암종 '풍화암/연암/보통암/경암' + '27 ㎝/min/20 ㎝/min/…')
        info["basis"] = "shared_value"
    elif len(stacks[0]) >= 2 and any(len(stacks[c]) == len(stacks[0]) for c in range(1, len(row)) if row[c] != row[0]):
        # 줄 수가 같은 글자 칸끼리는 줄바꿈된 이름일 수 있다(555쪽 '지상/기준점/선점'과 '정사/영상/제작').
        # 값(숫자가 든 줄)이 같은 줄 수로 쌓였을 때만 여러 행으로 본다
        # (500쪽 첫 표: 직종 5줄·수량 '7.5×2=15' 5줄·단가 5줄)
        if any(len(stacks[c]) == len(stacks[0]) and digits_in_every_line(stacks[c])
               for c in range(1, len(row)) if row[c] != row[0]):
            depth = len(stacks[0])
            info["basis"] = "line_count"
        else:
            info["basis"] = "label_wrap"
            return [[" ".join(s) if s else None for s in stacks]]
    else:
        # 첫 열이 한 줄이면 칸 안 줄바꿈이다(500쪽 '획지수 | (50,000×0.65 / ÷120)=270')
        return [[" ".join(s) if s else None for s in stacks]]
    info["depth"] = depth

    # Equipment lists can print a shared code stem and type above N aligned
    # specifications. ODL may keep all N+1 lines in one cell even when the
    # numeric columns contain N separate values (including mixed list nodes).
    prefixes = {}
    if (len(stacks[0]) == depth + 1 and re.fullmatch(r"\d+-", stacks[0][0].strip())
            and all(VALUE_RE.match(s.strip()) for s in stacks[0][1:])
            and sum(len(s) == depth + 1 for s in stacks) >= 2):
        for c, s in enumerate(stacks):
            if len(s) == depth + 1:
                prefixes[c] = s[0]
                stacks[c] = s[1:]

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
                label = labels[i] if label_per_row else (" ".join(labels) or None)
                sub.append(f"{prefixes[0]} {label}" if label and 0 in prefixes else label)
            elif len(s) == depth:
                value = s[i] or None
                sub.append(f"{prefixes[c]} {value}" if value and c in prefixes else value)
            elif not s:
                sub.append(None)
            elif bracket[c]:
                # 괄호 기호로 묶인 공유 값: 묶음의 첫 행에만 한 번
                sub.append(" ".join(s) if i == 0 else None)
            else:
                sub.append(" ".join(s))
        out.append(sub)
    return out


def parallel_column_groups(row: list) -> list[tuple[int, int]]:
    """Find independent side-by-side lists with different row counts.

    Both groups need at least two columns and their own numeric values. This
    avoids pairing, for example, two workers with three tile sizes.
    """
    lengths = [len(cell.split("\n")) if cell else 0 for cell in row]
    if any(n < 2 for n in lengths):
        return [(0, len(row))]
    cut = next((i for i in range(1, len(row)) if lengths[i] != lengths[0]), None)
    if cut is None or cut < 2 or len(row) - cut < 2 or len(set(lengths[cut:])) != 1:
        return [(0, len(row))]
    if not all(any(all(VALUE_RE.match(re.sub(r"\s+", "", line)) for line in row[c].split("\n"))
                   for c in range(start + 1, stop)) for start, stop in ((0, cut), (cut, len(row)))):
        return [(0, len(row))]
    return [(0, cut), (cut, len(row))]


def note_clauses(note: str) -> list[str]:
    """Keep each bullet condition with its own consequence."""
    clauses = [part.strip() for part in re.split(r"(?m)(?=^\s*-\s+)", note) if part.strip()]
    return clauses if len(clauses) > 1 else [note]


def owner_grid(table: dict) -> list[list[int | None]]:
    """to_grid와 같은 겹침 규칙으로, 격자 칸마다 그 글을 가진 원래 칸(table["cells"] 위치)을 낸다."""
    owner = [[None] * table["n_cols"] for _ in range(table["n_rows"])]
    order = sorted(range(len(table["cells"])),
                   key=lambda i: (table["cells"][i]["r1"] - table["cells"][i]["r0"])
                   * (table["cells"][i]["c1"] - table["cells"][i]["c0"]), reverse=True)
    for i in order:
        cell = table["cells"][i]
        for r in range(cell["r0"], cell["r1"]):
            for c in range(cell["c0"], cell["c1"]):
                owner[r][c] = i
    return owner


def header_of(table: dict, shades: list) -> tuple[int, str]:
    """표의 머리글 행 수와 판정 근거. 보관 구조와 조립이 같은 판정을 쓰도록 한 곳에 둔다."""
    raw_grid, _ = to_grid(table)
    grid = [[clean(c) for c in row] for row in raw_grid]
    return count_header(table, grid, shades)


def split_state(table: dict, grid_rows: list[int]) -> str | None:
    """격자 행의 분리 상태: split(어댑터가 나눔)|stacked_unsplit(쌓였으나 못 나눔: 후보)|single.
    행 분리 기록(row_map)이 없는 표(PyMuPDF 대체 추출 등)는 None이고, 이때만 조립 단계가 후보를 만든다."""
    row_map = table.get("row_map")
    if row_map is None:
        return None
    return row_map[grid_rows[0]]["state"] if grid_rows and grid_rows[0] < len(row_map) else "single"


def table_to_records(table: dict, shades: list, section_title: str, page_no: int, trace: bool = False) -> list[dict]:
    """공통 표 → 레코드. trace=True면 레코드마다 어느 원래 칸(table["cells"] 위치)에서 왔는지 함께 낸다.

    trace 항목:
      role       row(본문 행) | remark(비고 행) | label_only(값 없이 남은 라벨 행)
      parts      글 조각 [{role: section|label|value, col, cells, line, repeated, text}] — text는 조각을 ' | '로 이은 것
      omitted    글에 넣지 않은 칸 [{col, cells, raw}] ('-' 또는 빈 칸)
      grid_rows  이 레코드가 나온 격자 행 번호(앞 행 라벨을 이어받았으면 여러 개)
      row_split  {basis, depth, index} 행 분리 판정 근거(unstack 설명 참조)
      header     {count, basis}
    """
    raw_grid, bracket = to_grid(table)
    owner = owner_grid(table)
    grid = [[clean(c) for c in row] for row in raw_grid]
    header_count, header_basis = count_header(table, grid, shades)
    names = column_names(grid[:header_count], table["n_cols"])
    header = {"count": header_count, "basis": header_basis}

    def own_of(r: int, c: int) -> list[int]:
        return [owner[r][c]] if owner[r][c] is not None else []

    # 값 없이 라벨만 있는 행은 다음 행 라벨 앞에 붙인다. 이어받기보다 먼저 해야
    # 그 아래 행들도 합친 라벨을 이어받는다(872쪽 '거푸집하부용' + '앵커설치')
    # rows 항목: (글 칸 목록, 괄호 표시, 칸마다 원래 칸 목록, 격자 행 번호 목록)
    rows, carry, carry_own, carry_rows = [], None, [], []
    for r in range(header_count, table["n_rows"]):
        row, br = list(grid[r]), bracket[r]
        own = [own_of(r, c) for c in range(table["n_cols"])]
        src = [r]
        if row[0] and all(c is None for c in row[1:]) and not table.get("line_regrid"):
            carry = row[0] if carry is None else f"{carry} {row[0]}"
            carry_own, carry_rows = carry_own + own[0], carry_rows + [r]
            continue
        if carry:
            row[0] = f"{carry} {row[0]}" if row[0] else carry
            own[0], src = carry_own + own[0], carry_rows + src
            carry, carry_own, carry_rows = None, [], []
        rows.append((row, br, own, src))

    # 첫 열 이어받기(현행 clean_table과 같은 규칙)
    label, label_own, merged = None, [], []
    for row, br, own, src in rows:
        if row[0] is not None:
            label, label_own = row[0], own[0]
        elif label is not None and any(c is not None for c in row) and not table.get("line_regrid"):
            row[0], own[0] = label, label_own
        merged.append((row, br, own, src))

    records, note_written = [], False
    previous_values = [None] * table["n_cols"]
    previous_own = [[] for _ in range(table["n_cols"])]
    for row, br, own, src in merged:
        # A horizontally merged explanation is one text cell. It is not a value
        # independently attached to every column it spans (unit, quantity, remark).
        explanation = {ids[0] for col, ids in enumerate(own[1:], 1) if row[col] and len(ids) == 1}
        if len(explanation) == 1:
            i = next(iter(explanation)); cell = table["cells"][i]
            content = clean(cell["text"]) or ""
            if (clean(row[0]) != "비고" and cell["c0"] >= 1 and cell["c1"] - cell["c0"] > 1
                    and cell["r1"] - cell["r0"] == 1 and content and not NUMERIC_RE.match(content)
                    and (len(content) > 20 or re.search(r"적용|계상|산출|참조|제외|별도", content))):
                label = (row[0] or "").replace("\n", " ").strip()
                record = {"text": f"{section_title} | {label} | {content}".replace("\n", " "),
                          "section": section_title, "page": page_no}
                if trace:
                    record.update(role="remark", grid_rows=src, header=header,
                                  cells={"label": own[0], "note": [i]})
                records.append(record)
                continue
        # 다시 짠 표는 이름 열의 〃도 위 이름으로 푼다(이어받기 대신 원문의 같음 표시를 따른다)
        for col in range(0 if table.get("line_regrid") else 1, len(row)):
            ditto = ("〃", '"') if table.get("line_regrid") else ("〃",)     # 다시 짠 표: 원문 " 도 같음 표시
            if row[col] and set(re.sub(r"\s+", "", row[col])) <= set(ditto) and previous_values[col]:
                # 〃는 위 칸 값으로 풀어 쓴다. 원래 칸(〃)과 값을 가져온 칸을 둘 다 남긴다
                row[col], own[col] = previous_values[col], own[col] + previous_own[col]
            elif row[col] and not set(re.sub(r"\s+", "", row[col])) <= set(ditto):
                previous_values[col], previous_own[col] = row[col], own[col]
        label = (row[0] or "").replace("\n", " ").strip()
        if label == "비고":
            if note_written:
                continue
            note_written = True
            # 비고 라벨 칸이 둘 이상의 열에 걸치면 row[1]도 라벨 자신이다(951쪽). 라벨이 아닌 첫 칸을 글로 쓴다
            note_col = next((c for c in range(1, len(row)) if row[c] and own[c] != own[0]), None)
            note = row[note_col] if note_col is not None else ""
            clauses = [note] if table.get("contains_nested_table") else note_clauses(note)
            for clause in clauses:
                record = {"text": f"{section_title} | 비고 | {clause}".replace("\n", " "),
                          "section": section_title, "page": page_no}
                if trace:
                    record.update(role="remark", grid_rows=src, header=header,
                                  cells={"label": own[0], "note": own[note_col] if note_col is not None else []})
                records.append(record)
            continue
        for start, stop in parallel_column_groups(row):
            info: dict = {}
            state = split_state(table, src)
            # 행을 나누는 판정은 어댑터(odl_tables.split_row)에만 있다. 조립은 어댑터가 쌓였다고 표시했으나
            # 나누지 못한 행(stacked_unsplit)에서만 후보 레코드를 만든다. 이미 나눈 행·한 줄 행은 건드리지 않는다
            subs = unstack(row[start:stop], br[start:stop], names[start:stop],
                           allow_split=state in (None, "stacked_unsplit"), info=info)
            if state == "split":
                info["basis"] = "adapter"
            for index, sub in enumerate(subs):
                row_label = (sub[0] or "").replace("\n", " ").strip()
                if row_label and names[start] and (start > 0 or NUMERIC_RE.match(row_label)):
                    label_text = f"{names[start]} {row_label}"
                else:
                    label_text = row_label
                parts = [{"role": "section", "text": section_title},
                         {"role": "label", "col": start, "cells": own[start], "line": None, "repeated": False,
                          "text": label_text}]
                omitted = []
                for col in range(1, len(sub)):
                    value = (sub[col] or "").replace("\n", " ").strip()
                    absolute = start + col
                    if value in ("", "-"):
                        omitted.append({"col": absolute, "cells": own[absolute], "raw": value})
                        continue
                    name = names[absolute].strip()
                    skip_name = not name or name == names[start].strip()
                    # 쌓인 칸이면 이 레코드가 그 칸의 몇 번째 줄인지, 아니면 같은 칸을 레코드마다 되풀이한 것
                    lines = (row[absolute] or "").split("\n")
                    stacked = info["depth"] > 1 and len(lines) == info["depth"]
                    parts.append({"role": "value", "col": absolute, "cells": own[absolute],
                                  "line": index if stacked else None,
                                  "repeated": info["depth"] > 1 and not stacked,
                                  "text": value if skip_name else f"{name} {value}"})
                record = {"text": " | ".join(p["text"] for p in parts),
                          "section": section_title, "page": page_no}
                if trace:
                    record.update(role="row", parts=parts, omitted=omitted, grid_rows=src, header=header,
                                  row_split={"basis": info["basis"], "depth": info["depth"], "index": index,
                                             "state": state or "legacy"})
                records.append(record)
    # 값 없이 끝난 라벨 행도 글을 잃지 않게 남긴다
    if carry:
        record = {"text": f"{section_title} | {carry}".replace("\n", " "), "section": section_title, "page": page_no}
        if trace:
            record.update(role="label_only", grid_rows=carry_rows, header=header, cells={"label": carry_own})
        records.append(record)
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
