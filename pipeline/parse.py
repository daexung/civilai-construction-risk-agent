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

# "3", "0.15", "3\n3" 처럼 숫자만 들어있는 칸
NUMERIC_RE = re.compile(r"^\d+(\.\d+)?(\n\d+(\.\d+)?)*$")


# text 추출 함수
def extract_text(pdf_path: str, page_no: int) -> str:
    with pymupdf.open(pdf_path) as doc:
        text = doc[page_no - 1].get_text()

    return text


# table 추출 함수 (표의 세로 위치도 함께)
def extract_tables_with_pos(pdf_path: str, page_no: int) -> list:
    with pymupdf.open(pdf_path) as doc:
        page = doc[page_no - 1]
        tables = []
        for table in page.find_tables().tables:
            tables.append((table.bbox[1], table.extract()))
    return tables


# table 추출 함수
def extract_tables(pdf_path: str, page_no: int) -> list:
    return [grid for _, grid in extract_tables_with_pos(pdf_path, page_no)]


# 절 제목 추출 함수 (세로 위치, 제목)
def find_section_titles(pdf_path: str, page_no: int) -> list:
    titles = []
    with pymupdf.open(pdf_path) as doc:
        page = doc[page_no - 1]
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                text = "".join(span["text"] for span in line["spans"]).strip()
                if SECTION_RE.match(text):
                    titles.append((line["bbox"][1], text))
    return titles


# 칸 하나 정리: 한 글자씩 띄어 쓴 줄만 공백을 없앤다
def clean_cell(cell):
    if cell is None:
        return None

    lines = []
    for line in cell.split("\n"):
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
            records.append({"text": text, "section": section_title, "page": page_no})
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

        for i in range(depth):
            labels = stacks[0]
            if not labels:
                row_label = ""
            elif label_is_stacked:
                row_label = labels[i].strip()
            else:
                row_label = " ".join(part.strip() for part in labels)

            parts = [section_title, row_label]
            for col in range(1, len(row)):
                values = stacks[col]
                if not values:
                    continue

                value = (values[i] if len(values) == depth else values[0]).strip()
                if value in ("", "-"):
                    continue

                name = names[col].strip()
                # 직종 칸(첫 값 칸)은 열 이름을 붙이지 않는다
                parts.append(value if col == 1 or not name else f"{name} {value}")

            records.append(
                {"text": " | ".join(parts), "section": section_title, "page": page_no}
            )

    return records


# 표보다 위에 있으면서 가장 가까운 절 제목
def title_for_table(titles: list, table_top: float) -> str:
    above = [title for y, title in titles if y <= table_top + 2]
    return above[-1] if above else ""


def parse_pages(pdf_path: str, start_page: int, end_page: int) -> list:
    records = []
    # 표가 여러 쪽에 걸치면 제목이 앞 쪽에만 있으므로 직전 제목을 이어받는다
    last_title = ""

    for page_no in range(start_page, end_page + 1):
        titles = find_section_titles(pdf_path, page_no)

        for table_top, grid in extract_tables_with_pos(pdf_path, page_no):
            title = title_for_table(titles, table_top) or last_title
            last_title = title
            records += table_to_records(clean_table(grid), title, page_no)

        if titles:
            last_title = titles[-1][1]

    return records


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
