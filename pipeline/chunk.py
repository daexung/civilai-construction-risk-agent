# 파싱 레코드(parsed.jsonl)를 검색 단위(청크)로 묶는 단계
#
# 실행: python pipeline/chunk.py
#
# 경계는 원문 구조만 쓴다. 글자 수로 자르거나 겹쳐 넣지 않는다(슬라이딩 윈도우 없음).
#   절:     레코드의 section (6-1 상위 절, 6-1-4 하위 절)
#   소제목: 절 안에 인쇄된 '1. 적용범위', '2. 인력편성' 같은 줄. 파싱 결과에 남은 것만 쓰고 추측하지 않는다
#   표:     find_tables 표 하나가 청크 하나. 바로 위의 기준 표기('(일당)', '(100㎡당)')를 함께 붙인다
#   줄글:   같은 절·같은 소제목·같은 쪽에서 이어지는 설명([주], 가. 나. 항목 등)
#
# 모든 청크는 절 번호, 소제목, PDF 쪽, 원문 표 번호와 bbox, 원본 레코드 줄 번호를 가진다.
# 행 하나라도 구조가 불확실하면 그 표 청크 전체를 structure=uncertain으로 두고 자동 적산에 쓰지 않는다.

import argparse
import json
import re
import unicodedata
from pathlib import Path

PDF = "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"

SECTION_NO_RE = re.compile(r"^(\d+-\d+(?:-\d+)?)")
# 표 바로 위에 따로 인쇄되는 기준 표기: (일당), (㎥당), (100㎡당), (ton당), (개소당)
BASIS_RE = re.compile(r"^\([^()]*당\)$")
# 절 안의 번호 소제목. PDF 글자 블록이 소제목과 뒤따르는 글을 한 레코드로 줄 때가 있다
#   '2. 인력편성' / '3. 장비조합 설치 및 해체 (일당)' / '1. 사용횟수 - 사용횟수는 …' / '1. 적용범위 ① 본 품은 …'
HEADING_RE = re.compile(r"^(\d{1,2})\.\s*(\S.*)$")
TRAILING_BASIS_RE = re.compile(r"\s*(\([^()]*당\))\s*$")
# 소제목 이름 뒤에 본문이 이어지는 표시: '- ', 원문자 번호, '가.'
BODY_START_RE = re.compile(r"\s(?=-\s|[①-⑳]|가\.\s)")


def body(record: dict) -> str:
    """레코드 글자에서 앞의 절 제목을 뺀 부분."""
    prefix = f"{record['section']} | "
    text = record["text"]
    return text[len(prefix):] if text.startswith(prefix) else text


def section_no(title: str) -> str | None:
    match = SECTION_NO_RE.match(title)
    return match.group(1) if match else None


def parse_heading(content: str) -> dict | None:
    """'2. 인력편성 (일당)' → {no, title, basis, has_body}. 소제목이 아니면 None."""
    # 전각 번호('２.')만 반각으로 바꾼다. 전체를 정규화하면 본문의 '①'이 '1'이 되어 본문 시작을 놓친다
    head = re.match(r"^\S{1,3}", content)
    if head:
        content = unicodedata.normalize("NFKC", head.group(0)) + content[head.end():]
    match = HEADING_RE.match(content)
    if not match:
        return None
    rest = match.group(2)
    parts = BODY_START_RE.split(rest, maxsplit=1)
    title, has_body = parts[0].strip(), len(parts) > 1
    basis = None
    if not has_body:
        found = TRAILING_BASIS_RE.search(title)
        if found:
            basis, title = found.group(1), title[:found.start()].strip()
    return {"no": match.group(1), "title": title, "basis": basis, "has_body": has_body}


def make_chunks(records: list[dict], pdf: str = PDF) -> list[dict]:
    chunks = []
    pending_basis = None     # (레코드 번호, 글자): 다음 표에 붙일 기준 표기
    text_group = []          # 이어지는 줄글 레코드 번호
    sub = None               # 현재 소제목 {no, title, record_id, section}

    def current_sub(section):
        if not (sub and sub["section"] == section):
            return None
        sub["used"] = True
        return {k: sub[k] for k in ("no", "title", "record_id")}

    def close_sub():
        """뒤따르는 청크 없이 끝난 소제목(다음 표가 0레코드 등)은 소제목만 담은 줄글 청크로 남긴다."""
        flush_text()
        if sub and not sub["used"]:
            text_group.append(sub["record_id"])
            flush_text()

    def header_lines(first, subsection, skip_heading):
        lines = [first["section"]]
        if subsection and not skip_heading:
            lines.append(f"{subsection['no']}. {subsection['title']}")
        return lines

    def flush_text():
        if not text_group:
            return
        ids = list(text_group)
        first = records[ids[0]]
        subsection = current_sub(first["section"])
        starts_with_heading = subsection is not None and subsection["record_id"] == ids[0]
        chunks.append({
            "chunk_id": f"p{first['page']}-x{ids[0]}",
            "kind": "text",
            "section": first["section"],
            "section_no": section_no(first["section"]),
            "subsection": subsection,
            "pages": [first["page"]],
            "source": {"pdf": pdf, "page": first["page"], "table_id": None, "bbox": None},
            "basis": None,
            "structure": "n/a",
            "uncertain_record_ids": [],
            "record_ids": ids,
            "text": "\n".join(header_lines(first, subsection, starts_with_heading) + [body(records[i]) for i in ids]),
        })
        text_group.clear()

    i = 0
    while i < len(records):
        record = records[i]
        if sub and sub["section"] != record["section"]:
            # 절이 바뀌면 이전 절의 줄글을 그 소제목으로 먼저 내보낸 뒤 소제목을 비운다
            close_sub()
            sub = None
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
            subsection = current_sub(record["section"])
            uncertain = [j for j in ids if records[j]["structure"]["status"] != "ok"]
            lines = header_lines(record, subsection, False) + ([f"기준 {basis}"] if basis else []) \
                + [body(records[j]) for j in ids]
            chunks.append({
                "chunk_id": table_id,
                "kind": "table",
                "section": record["section"],
                "section_no": section_no(record["section"]),
                "subsection": subsection,
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
        heading = parse_heading(content)
        if heading:
            # 소제목은 새 경계다. 소제목만 있는 줄은 청크를 만들지 않고 뒤따르는 청크들의 subsection으로 남긴다
            close_sub()
            pending_basis = (i, heading["basis"]) if heading["basis"] else None
            sub = {"no": heading["no"], "title": heading["title"], "record_id": i, "section": record["section"],
                   "used": False}
            if heading["has_body"]:
                text_group.append(i)
        elif BASIS_RE.match(content):
            # 기준 표기는 줄글 청크가 아니라 다음 표의 조건이다. 같은 줄글 흐름은 여기서 끊는다
            flush_text()
            pending_basis = (i, content)
        else:
            if text_group and (records[text_group[-1]]["section"] != record["section"]
                               or records[text_group[-1]]["page"] != record["page"]):
                flush_text()
            text_group.append(i)
        i += 1
    close_sub()
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
    sections = {c["section"] for c in chunks}
    with_sub = {c["section"] for c in chunks if c["subsection"]}
    print(f"레코드 {len(records)}건 -> 청크 {len(chunks)}개 (표 {len(tables)}, 줄글 {len(chunks) - len(tables)}) -> {out}")
    print(f"절 {len(sections)}개 중 소제목이 있는 절 {len(with_sub)}개")
    print(f"구조 불확실 표 {sum(c['structure'] == 'uncertain' for c in tables)}개, "
          f"기준 표기 없는 표 {sum(not c['basis'] for c in tables)}개")


if __name__ == "__main__":
    main()
