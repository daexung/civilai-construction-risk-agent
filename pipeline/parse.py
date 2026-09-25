# PDF에서 텍스트와 표를 뽑아 청킹 직전 형태(레코드)로 만드는 단계
#
# 실행: python pipeline/parse.py --start 185 --end 185

import argparse
import json
import re
from pathlib import Path

import pymupdf

# "6-1-1 레디믹스트콘크리트 타설" 처럼 세 자리 절 번호로 시작하는 줄
SECTION_RE = re.compile(r"^\d+-\d+-\d+\s")

# "6-1 콘크리트" 처럼 두 자리 중분류. 절이 시작되기 전 도입부 설명을 묶는 데 쓴다
SUBSECTION_RE = re.compile(r"^\d+-\d+\s")

# 모든 쪽에 반복되는 머리글("제6장 철근콘크리트공사")과 쪽 번호.
# 본문도 같은 높이에서 시작하는 쪽이 있어 위치가 아니라 내용으로 걸러야 한다
RUNNING_HEAD_RE = re.compile(r"^(제\d+장(\s|$)|\d+$)")

# "3", "0.15", "3\n3" 처럼 숫자만 들어있는 칸
NUMERIC_RE = re.compile(r"^\d+(\.\d+)?(\n\d+(\.\d+)?)*$")


# text 추출 함수
def extract_text(pdf_path: str, page_no: int) -> str:
    with pymupdf.open(pdf_path) as doc:
        text = doc[page_no - 1].get_text()

    return text


# 표를 (bbox, 격자)로 읽는다
def read_tables(page) -> list:
    return [(table.bbox, table.extract()) for table in page.find_tables().tables]


# 제목을 (세로 위치, 제목, 절인지 여부)로 읽는다
def read_titles(page) -> list:
    titles = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            text = "".join(span["text"] for span in line["spans"]).strip()
            if SECTION_RE.match(text):
                titles.append((line["bbox"][1], text, True))
            elif SUBSECTION_RE.match(text):
                titles.append((line["bbox"][1], text, False))
    return titles


# 표 밖에 있는 줄글을 (세로 위치, 글) 목록으로 읽는다
def read_text_blocks(page, table_boxes: list) -> list:
    blocks = []

    for x0, y0, x1, y1, text, _, block_type in page.get_text("blocks"):
        text = " ".join(text.split())
        if block_type != 0 or not text:
            continue

        # 쪽 번호와 쪽마다 반복되는 머리글
        if RUNNING_HEAD_RE.match(text):
            continue

        # 제목 줄은 section 항목으로 따로 남으므로 본문에서는 뺀다
        if SECTION_RE.match(text) or SUBSECTION_RE.match(text):
            continue

        # 표 안의 글자는 이미 격자로 읽었다
        center_x, center_y = (x0 + x1) / 2, (y0 + y1) / 2
        if any(
            box[0] - 2 <= center_x <= box[2] + 2 and box[1] - 2 <= center_y <= box[3] + 2
            for box in table_boxes
        ):
            continue

        blocks.append((y0, text))

    return blocks


# text 추출 함수
def extract_text(pdf_path: str, page_no: int) -> str:
    with pymupdf.open(pdf_path) as doc:
        text = doc[page_no - 1].get_text()

    return text


# table 추출 함수
def extract_tables(pdf_path: str, page_no: int) -> list:
    with pymupdf.open(pdf_path) as doc:
        return [grid for _, grid in read_tables(doc[page_no - 1])]


# 절 제목 추출 함수 (세로 위치, 제목)
def find_section_titles(pdf_path: str, page_no: int) -> list:
    with pymupdf.open(pdf_path) as doc:
        return [(y, title) for y, title, is_section in read_titles(doc[page_no - 1]) if is_section]


# 여러 행을 묶어 보이려고 그려 넣은 괄호 기호. 값이 아니므로 줄 수에서 빼야 한다
BRACKET_RE = re.compile(r"^[⌈⌉⌊⌋┌┐└┘│├┤]+$")


# 칸 하나 정리: 한 글자씩 띄어 쓴 줄만 공백을 없애고, 괄호 기호 줄은 버린다
def clean_cell(cell):
    if cell is None:
        return None

    lines = []
    for line in cell.split("\n"):
        if BRACKET_RE.match(line.strip()):
            continue

        parts = line.split(" ")
        if len(parts) > 1 and all(len(p) == 1 for p in parts):
            line = "".join(parts)
        lines.append(line)

    return "\n".join(lines)


# 표 정리: 칸 공백 제거 + 병합 셀로 비어버린 첫 칸 채우기
def clean_table(table: list) -> list:
    cleaned = []
    label = None

    for row in table:
        new_row = [clean_cell(cell) for cell in row]

        if new_row[0] is not None:
            label = new_row[0]
        elif label is not None and any(cell is not None for cell in new_row):
            new_row[0] = label

        cleaned.append(new_row)

    return cleaned


# 머리글이 몇 행까지인지 (숫자 칸이 처음 나오는 행 앞까지)
def count_header_rows(table: list) -> int:
    for i, row in enumerate(table):
        if any(cell and NUMERIC_RE.match(cell) for cell in row):
            return i
    return len(table)


# 열 이름 만들기: "시공량(㎥)" + "무근구조물" -> "시공량(㎥) 무근구조물"
def build_column_names(header_rows: list, col_count: int) -> list:
    if not header_rows:
        return [""] * col_count

    # 첫 머리글 행은 가로로 병합돼 있어 빈 칸을 왼쪽 값으로 채운다
    top = []
    current = None
    for cell in header_rows[0]:
        current = cell if cell is not None else current
        top.append(current)

    names = []
    for col in range(col_count):
        parts = []
        for i, row in enumerate(header_rows):
            value = top[col] if i == 0 else row[col]
            if value and value not in parts:
                parts.append(value)
        names.append(" ".join(parts))
    return names


# 표 -> 레코드. 한 레코드가 한 행(구분+직종)에 대응한다
#
# structure는 이 행의 표 구조를 믿을 수 있는지 표시한다. 글자는 바꾸지 않는다.
#   label_joined: 여러 줄 라벨을 행으로 나누지 못하고 한 라벨로 이었다('형틀목공 보통인부')
#   value_lines_mismatch: 줄 수가 행 수와 다른 값 칸에서 첫 줄만 썼다(나머지 줄은 다른 행 값일 수 있다)
def table_to_records(table: list, section_title: str, page_no: int) -> list:
    header_count = count_header_rows(table)
    names = build_column_names(table[:header_count], len(table[0]))

    records = []
    note_written = False

    for row in table[header_count:]:
        label = (row[0] or "").replace("\n", " ").strip()

        # 비고 행은 한 번만 남긴다 (표 안에 표가 있어 같은 내용이 여러 행으로 쪼개져 나옴)
        if label == "비고":
            if note_written:
                continue
            note_written = True
            note = next((cell for cell in row[1:] if cell), "")
            text = f"{section_title} | 비고 | {note}".replace("\n", " ")
            records.append({"text": text, "section": section_title, "page": page_no,
                            "structure": {"status": "ok", "issues": []}})
            continue

        # 한 칸에 '\n'으로 쌓인 값들을 세로로 풀어 짝을 맞춘다
        stacks = {col: (row[col].split("\n") if row[col] else []) for col in range(len(row))}

        # 몇 개로 풀지는 값 칸들로 정한다. 첫 칸은 라벨이라 개수 계산에서 빼야
        # 라벨만 두 줄인 행에서 같은 레코드가 두 번 생기지 않는다.
        value_counts = {len(values) for col, values in stacks.items() if col > 0 and values}
        depth = max(value_counts, default=1) or 1

        # 첫 칸도 쌓여 있는 경우가 있다. 다만 칸 폭이 좁아 라벨이 줄바꿈된 것과 구분해야 한다.
        # 모든 칸의 줄 수가 같으면 쌓인 값으로 보고 풀고, 아니면 줄바꿈된 라벨로 보고 합친다.
        label_is_stacked = len(value_counts) == 1 and len(stacks[0]) == depth and depth > 1

        # 첫 칸 여러 줄을 이어 붙인 경우, 줄마다 다른 글자를 가진 다른 칸(직종·재료명)이 있으면
        # 행은 그 칸으로 구분되고 첫 칸은 줄바꿈된 조건이다(185쪽 '인력운반\n타설'). 그런 칸이 없으면 행을 합친 것이다
        per_row_label_col = any(
            len(values) == depth and len(set(values)) == depth and not any(re.search(r"\d", v) for v in values)
            for col, values in stacks.items() if col > 0
        )
        issues = []
        if depth > 1 and len(stacks[0]) > 1 and not label_is_stacked and not per_row_label_col:
            issues.append("label_joined")
        if any(1 < len(values) < depth for col, values in stacks.items() if col > 0):
            issues.append("value_lines_mismatch")
        structure = {"status": "uncertain" if issues else "ok", "issues": issues}

        for i in range(depth):
            labels = stacks[0]
            if not labels:
                row_label = ""
            elif label_is_stacked:
                row_label = labels[i].strip()
            else:
                row_label = " ".join(part.strip() for part in labels)

            # 첫 칸이 라벨이 아니라 값인 표가 있다 (예: 층수별 할증률).
            # 그때는 라벨로 쓰지 않고 다른 값처럼 열 이름을 붙인다.
            if row_label and names[0] and NUMERIC_RE.match(row_label):
                parts = [section_title, f"{names[0]} {row_label}"]
            else:
                parts = [section_title, row_label]

            for col in range(1, len(row)):
                values = stacks[col]
                if not values:
                    continue

                value = (values[i] if len(values) == depth else values[0]).strip()
                if value in ("", "-"):
                    continue

                name = names[col].strip()
                # 첫 칸과 머리글을 공유하는 칸(주로 직종)은 이름을 붙이면 '구분 콘크리트공'처럼 군더더기가 된다
                skip_name = not name or name == names[0].strip()
                parts.append(value if skip_name else f"{name} {value}")

            records.append(
                {"text": " | ".join(parts), "section": section_title, "page": page_no,
                 "structure": structure}
            )

    return records


# 대상보다 위에 있으면서 가장 가까운 제목. 절(6-1-1)을 중분류(6-1)보다 우선한다
def title_above(titles: list, top: float) -> str:
    above = [(title, is_section) for y, title, is_section in titles if y <= top + 2]
    if not above:
        return ""

    sections = [title for title, is_section in above if is_section]
    return sections[-1] if sections else above[-1][0]


def parse_pages(pdf_path: str, start_page: int, end_page: int) -> list:
    records = []
    # 표가 여러 쪽에 걸치면 제목이 앞 쪽에만 있으므로 직전 제목을 이어받는다
    last_title = ""

    with pymupdf.open(pdf_path) as doc:
        for page_no in range(start_page, end_page + 1):
            page = doc[page_no - 1]
            titles = read_titles(page)
            tables = read_tables(page)

            items = [(box[1], "table", (i, box, grid)) for i, (box, grid) in enumerate(tables)]
            items += [
                (y, "text", text)
                for y, text in read_text_blocks(page, [box for box, _ in tables])
            ]

            # 쪽 안에서 위에서 아래 순서로 처리해야 제목을 이어받는 순서가 맞는다
            for top, kind, content in sorted(items, key=lambda item: item[0]):
                title = title_above(titles, top) or last_title
                last_title = title

                if kind == "table":
                    # 원문 표로 돌아갈 수 있게 표 번호(쪽 안 find_tables 순서)와 bbox(pt, 왼쪽 위 원점)를 남긴다
                    index, box, grid = content
                    source = {"kind": "table", "table_id": f"p{page_no}-t{index}",
                              "bbox": [round(v, 1) for v in box]}
                    records += [{**r, **source} for r in table_to_records(clean_table(grid), title, page_no)]
                else:
                    records.append(
                        {"text": f"{title} | 설명 | {content}", "section": title, "page": page_no,
                         "kind": "text", "table_id": None, "bbox": None}
                    )

            if titles:
                last_title = titles[-1][1]

    # 같은 절 안에서 '(일당)' 같은 표기나 동일한 사양이 여러 표에 반복된다.
    # 글자가 완전히 같으면 검색에 보탬이 되지 않으므로 하나만 남긴다
    seen = set()
    unique = []
    for record in records:
        if record["text"] in seen:
            continue
        seen.add(record["text"])
        unique.append(record)

    return unique


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", default="data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf")
    parser.add_argument("--start", type=int, default=185)
    parser.add_argument("--end", type=int, default=185)
    parser.add_argument("--out", default="data/processed/parsed.jsonl")
    args = parser.parse_args()

    records = parse_pages(args.pdf, args.start, args.end)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"{args.start}~{args.end}쪽에서 레코드 {len(records)}건 -> {out_path}")


if __name__ == "__main__":
    main()
