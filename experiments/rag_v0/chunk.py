# 파싱 레코드(parsed.jsonl)를 검색 단위(청크)로 묶는 단계
#
# 실행: python pipeline/chunk.py
#
# 청크 두 종류
#   table: 표 하나(find_tables 한 개)의 모든 행 + 바로 위의 기준 표기('(일당)', '(100㎡당)' 등)
#   text:  같은 절·같은 쪽에서 이어지는 줄글([주], ◦ 항목 등). 길면 레코드 경계에서 나눈다
#
# 모든 청크는 절 번호, PDF 쪽, 원문 표 번호와 bbox, 원본 레코드 줄 번호를 가진다.
# 행 하나라도 구조가 불확실하면 그 표 청크 전체를 structure=uncertain으로 두고 자동 적산에 쓰지 않는다.

import argparse
import json
import re
from pathlib import Path

PDF = "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"

SECTION_NO_RE = re.compile(r"^(\d+-\d+(?:-\d+)?)")
# 표 바로 위에 따로 인쇄되는 기준 표기: (일당), (㎥당), (100㎡당), (ton당), (개소당)
BASIS_RE = re.compile(r"^\([^()]*당\)$")
MAX_TEXT_CHARS = 1200


def body(record: dict) -> str:
    """레코드 글자에서 앞의 절 제목을 뺀 부분."""
    prefix = f"{record['section']} | "
    text = record["text"]
    return text[len(prefix):] if text.startswith(prefix) else text


def section_no(title: str) -> str | None:
    match = SECTION_NO_RE.match(title)
    return match.group(1) if match else None


def make_chunks(records: list[dict], pdf: str = PDF) -> list[dict]:
    chunks = []
    pending_basis = None     # (레코드 번호, 글자): 다음 표에 붙일 기준 표기
    text_group = []          # 이어지는 줄글 레코드 번호

    def flush_text():
        if not text_group:
            return
        groups, current, size = [], [], 0
        for i in text_group:
            length = len(body(records[i]))
            if current and size + length > MAX_TEXT_CHARS:
                groups.append(current)
                current, size = [], 0
            current.append(i)
            size += length
        groups.append(current)
        for ids in groups:
            first = records[ids[0]]
            chunks.append({
                "chunk_id": f"p{first['page']}-x{ids[0]}",
                "kind": "text",
                "section": first["section"],
                "section_no": section_no(first["section"]),
                "pages": [first["page"]],
                "source": {"pdf": pdf, "page": first["page"], "table_id": None, "bbox": None},
                "basis": None,
                "structure": "n/a",
                "uncertain_record_ids": [],
                "record_ids": ids,
                "text": "\n".join([first["section"]] + [body(records[i]) for i in ids]),
            })
        text_group.clear()

    i = 0
    while i < len(records):
        record = records[i]
        if record["kind"] == "table":
            flush_text()
            table_id = record["table_id"]
            ids = []
            while i < len(records) and records[i]["table_id"] == table_id:
                ids.append(i)
                i += 1
            basis = None
            if pending_basis and records[pending_basis[0]]["section"] == record["section"] \
                    and records[pending_basis[0]]["page"] == record["page"]:
                basis = pending_basis[1]
            pending_basis = None
            uncertain = [j for j in ids if records[j]["structure"]["status"] != "ok"]
            lines = [record["section"]] + ([f"기준 {basis}"] if basis else []) + [body(records[j]) for j in ids]
            chunks.append({
                "chunk_id": table_id,
                "kind": "table",
                "section": record["section"],
                "section_no": section_no(record["section"]),
                "pages": [record["page"]],
                "source": {"pdf": pdf, "page": record["page"], "table_id": table_id, "bbox": record["bbox"]},
                "basis": basis,
                "structure": "uncertain" if uncertain else "ok",
                "uncertain_record_ids": uncertain,
                "record_ids": ids,
                "text": "\n".join(lines),
            })
            continue

        content = body(record).removeprefix("설명 | ").strip()
        if BASIS_RE.match(content):
            # 기준 표기는 줄글 청크가 아니라 다음 표의 조건이다. 같은 줄글 흐름은 여기서 끊는다
            flush_text()
            pending_basis = (i, content)
        else:
            if text_group and (records[text_group[-1]]["section"] != record["section"]
                               or records[text_group[-1]]["page"] != record["page"]):
                flush_text()
            text_group.append(i)
        i += 1
    flush_text()
    return chunks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parsed", default="data/processed/parsed.jsonl")
    parser.add_argument("--out", default="data/processed/chunks.jsonl")
    args = parser.parse_args()

    lines = Path(args.parsed).read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines if line.strip()]
    missing = [n for n, r in enumerate(records) if "kind" not in r]
    if missing:
        raise SystemExit(f"추적 필드가 없는 레코드 {len(missing)}건: parse.py로 다시 추출해야 한다")

    chunks = make_chunks(records)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(chunk, ensure_ascii=False) + "\n")

    tables = [c for c in chunks if c["kind"] == "table"]
    print(f"레코드 {len(records)}건 -> 청크 {len(chunks)}개 (표 {len(tables)}, 줄글 {len(chunks) - len(tables)}) -> {out}")
    print(f"구조 불확실 표 {sum(c['structure'] == 'uncertain' for c in tables)}개, "
          f"기준 표기 없는 표 {sum(not c['basis'] for c in tables)}개")


if __name__ == "__main__":
    main()
