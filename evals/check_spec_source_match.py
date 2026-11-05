"""AI 초안 명세를 파싱된 원문과 기계적으로 대조한다(외부 호출 없음).

검사:
- 표 값: 명세 표의 (행·열 → 값)이 원문 표의 같은 줄에 함께 있는지(cell), 숫자만 표 어딘가에 있는지(number_only),
  원문에 없는지(absent: 표에 없는 칸을 0 등으로 채운 추론 포함).
- 인용: 명세가 든 원문 인용(quote)이 해당 청크에 실제로 있는지.
- 주석: 같은 절의 [주] ①②… 가운데 명세가 한 번도 언급하지 않은 것(경고).

- 깨진 글자: 인코딩이 깨진 한글('???').
- 파싱 상태(parse_ok): 인용 표가 불확실(uncertain)로 파싱됐으면 글 대조의 한계라 표 이미지 확인이 필요하다.

판정: 불일치(absent·인용 없음·표 없음·깨진 글자) > 확인 필요(number_only) > 경고(주석 미언급) > 통과.

사용: python -B evals/check_spec_source_match.py [부문] [절 번호 접두어] [--json 출력경로]
예:   python -B evals/check_spec_source_match.py 공통 6-
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHUNKS = ROOT / "data/processed/chunks.all.jsonl"
SPECS = ROOT / "data/drafts/specs"
MARKERS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"


NUMERIC = re.compile(r"[-+]?\d[\d.,/]*%?")
# 주석 중 계산에 영향을 주는 것(별도 계상·할증·감산·참조). 나머지(포함 범위·기준 설명)는 참고로만 센다.
WEIGHTY = re.compile(r"별도|계상|할증|가산|감하|감한|%|따른다|적용한다|변경|추가")


def broken_text(node) -> bool:
    """한글·영문 뒤가 아닌 '?'(깨진 한글 한 글자)가 있는지. 정규식 문자열의 (?<!, (?: 등은 뺀다."""
    if isinstance(node, dict):
        return any(broken_text(k) or broken_text(v) for k, v in node.items())
    if isinstance(node, list):
        return any(map(broken_text, node))
    return (isinstance(node, str) and re.search(r"(?:^|[^가-힣A-Za-z)])\?", node) is not None
            and not re.search(r"\(\?[<!:=]", node))


def squash(text) -> str:
    return re.sub(r"[\s,'‘’\"“”·･()（）|]", "", str(text)).replace("~", "∼")


def rows(chunks) -> list[str]:
    """표 글의 논리 행. 칸 안 줄바꿈으로 쪼개진 줄을 '| 단위' 행 기준으로 다시 잇는다."""
    merged = []
    for chunk in chunks:
        lines = chunk["text"].split("\n")
        unit_rows = any("| 단위" in line for line in lines)
        start = len(merged)
        for line in lines:
            new_row = "|" in line and ("| 단위" in line or not unit_rows)
            if new_row or line.startswith("비고") or len(merged) == start:
                merged.append(line)
            else:
                merged[-1] += " " + line
    return merged


def has_word(row: str, key: str) -> bool:
    """키가 낱말 경계에 맞게 있는지('크레인'이 '크레인시공'에 걸리지 않게). 괄호 단위 표기는 무시한다."""
    tokens = [t for t in re.split(r"[|\s]+", row) if t]
    for i in range(len(tokens)):
        for j in range(i + 1, min(i + 7, len(tokens) + 1)):
            run = "".join(tokens[i:j])
            if key in (squash(run), squash(re.sub(r"\([^)]*\)", "", run))):
                return True
    return False


def cell_state(lines: list[str], keys: list[str], value: str, table_text: str) -> str:
    """'cell'(키가 맞는 행 모두에서 값 일치), 'ambiguous'(키가 같은 행끼리 값이 다름), 'none'."""
    present = [key for key in keys if key and key in table_text]
    if not present:
        return "none"
    for group in lines:  # 인용한 표의 행을 먼저, 없으면 같은 절의 다른 표(쪽 넘김) 행
        candidates = [row for row in group if all(has_word(row, key) for key in present)]
        candidates = candidates or [row for row in group if all(key in squash(row) for key in present)]
        if candidates:
            hits = [in_cell(row, present, value) for row in candidates]
            return "cell" if all(hits) else "ambiguous" if any(hits) else "none"
    return "none"


def in_cell(row: str, present: list[str], value: str) -> bool:
    """값이 열 키 바로 뒤에 있는지. 바로 뒤에 숫자가 오는 키가 없으면(행 이름만 있는 인원 행) '수량' 뒤를 본다."""
    flat = squash(row).replace(",", "")
    value = value.replace(",", "")
    if not has_number(row, value):
        return False
    # 압축한 행에서 값은 키 바로 뒤(단위 표기 몇 글자 허용)에 붙는다. 넓게 잡으면 다른 칸의 작은 정수를 잘못 인정한다.
    gap = r"[^\d\-가-힣]{0,3}?"  # 한글이 끼면('규격' 등) 다른 칸의 숫자다
    after = lambda anchor: [flat[m.end():] for m in re.finditer(re.escape(anchor), flat)]
    columns = [tail for key in present for tail in after(key) if re.match(rf"{gap}\d", tail)]
    tails = columns or after("수량")
    return any(re.match(rf"{gap}{re.escape(value)}(?![\d.])", tail) for tail in tails)


def has_number(line: str, value: str) -> bool:
    value = str(value).replace(",", "").strip()
    if not value:
        return False
    return re.search(rf"(?<![\d.]){re.escape(value)}(?![\d.])", line.replace(",", "")) is not None


def leaves(node, path=()):
    """중첩 dict의 (키 경로, 값) 목록."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from leaves(value, (*path, key))
    elif isinstance(node, list):
        for value in node:
            yield from leaves(value, path)
    else:
        yield path, node


def load_chunks():
    tables, sections, by_id = defaultdict(list), defaultdict(list), {}
    for line in CHUNKS.read_text(encoding="utf-8").splitlines():
        chunk = json.loads(line)
        by_id[chunk["chunk_id"]] = chunk
        if chunk["kind"] == "table" and chunk["source"].get("table_id"):
            tables[chunk["source"]["table_id"]].append(chunk)
        sections[(chunk.get("division"), chunk.get("section_no"))].append(chunk)
    return tables, sections, by_id


def notes(section_chunks) -> dict[str, str]:
    """절 본문의 [주] 번호별 문장."""
    text = "\n".join(c["text"] for c in section_chunks if c["kind"] != "table")
    if "[주]" not in text:
        return {}
    text = text[text.index("[주]"):]
    found = {}
    for marker, body in re.findall(rf"([{MARKERS}])\s*([^{MARKERS}]+)", text):
        found.setdefault(marker, body.split("\n")[0].strip())
    return found


def check(package: dict, tables, sections, by_id) -> dict:
    spec = package["draft"]
    problems, cells = [], Counter()
    for table in spec.get("tables", []):
        table_id = (table.get("cite") or {}).get("table_id") or table.get("id")
        source = tables.get(table_id)
        if not source:
            problems.append({"kind": "표 없음", "table": table_id})
            continue
        # 쪽을 넘어 이어지는 표는 다른 table_id로 갈라져 있으므로 같은 절의 표를 모두 본다.
        section_tables = [c for c in sections.get((spec["division"], spec["section_no"]), [])
                          if c["kind"] == "table" and c not in source]
        groups = [rows(source), rows(section_tables)]
        lines = [*groups[0], *groups[1]]
        whole = "\n".join(lines)
        table_text = squash(whole)
        for path, value in leaves(table.get("values") or {}):
            value = str(value).strip() if value is not None else ""
            if not NUMERIC.fullmatch(value):
                cells["text_skipped"] += 1  # 설명 문장 칸은 숫자 대조 대상이 아니다
                continue
            keys = [squash(part) for key in path for part in re.split(r"[|_]", str(key))]
            state = cell_state(groups, keys, value, table_text)
            if state == "cell":
                cells["cell"] += 1
            elif state == "ambiguous":
                cells["ambiguous_row"] += 1
                problems.append({"kind": "칸 확인 필요", "table": table_id, "path": list(path), "value": value,
                                 "note": "원문에 같은 이름의 행이 여러 개라 글만으로 구분 불가"})
            elif has_number(whole, value):
                cells["number_only"] += 1
                problems.append({"kind": "칸 확인 필요", "table": table_id, "path": list(path), "value": value})
            elif value in ("0", "-"):
                cells["blank_as_zero"] += 1  # 표에 없는 칸(장비 없음 등)을 0으로 채운 추론
                problems.append({"kind": "칸 확인 필요", "table": table_id, "path": list(path), "value": value,
                                 "note": "원문 빈칸을 0으로 채움"})
            else:
                cells["absent"] += 1
                problems.append({"kind": "원문에 없는 값", "table": table_id, "path": list(path), "value": value})
    dump = json.dumps(package, ensure_ascii=False)
    section_chunks = sections.get((spec["division"], spec["section_no"]), [])
    marks = re.compile(r"\n\s*(?:설명|비고|비\s*고)\s*\|")  # 파싱이 줄마다 붙인 표시(문장 중간에도 끼어 있다)
    section_text = squash(marks.sub(" ", "\n".join(c["text"] for c in section_chunks)))
    for cite in re.findall(r'\{[^{}]*"chunk_id": "([^"]+)"[^{}]*"quote": "((?:[^"\\]|\\.)*)"', dump):
        chunk_id, quote = cite[0], json.loads(f'"{cite[1]}"')
        chunk = by_id.get(chunk_id)
        haystack = squash(marks.sub(" ", chunk["text"]) if chunk else "") + section_text  # 옆 청크 인용도 인정
        # 복사하며 붙은 '설명 |'·'비고 |' 표시를 빼고, 중간 줄을 건너뛴 인용도 있어 조각마다 찾는다.
        quote = re.sub(r"(?:^|\n)\s*(?:설명|비고|비\s*고)\s*\|", " ", quote)
        pieces = [p for p in (squash(piece) for piece in re.split(r"[.。]\s|\s-\s|\n", quote)) if len(p) >= 8]
        if not all(piece in haystack for piece in pieces):
            problems.append({"kind": "인용 없음", "chunk": chunk_id, "quote": quote[:60],
                             "note": "인용 청크 없음" if chunk is None else ""})
    if broken_text(package):  # 인코딩이 깨진 한글. 질문 문장·선택지에 있으면 사용자에게 그대로 보인다
        problems.append({"kind": "깨진 글자", "fields": [
            f"input.{field['name']}" for field in spec.get("inputs", []) if broken_text(field)]})
    section_notes = notes(sections.get((spec["division"], spec["section_no"]), []))
    flat = squash(dump)
    missed = [(marker, body) for marker, body in section_notes.items()
              if marker not in dump and squash(body)[:15] not in flat]
    weighty = [f"{m} {b[:50]}" for m, b in missed if WEIGHTY.search(b)]
    scope_only = [f"{m} {b[:50]}" for m, b in missed if not WEIGHTY.search(b)]
    kinds = {p["kind"] for p in problems}
    verdict = ("불일치" if kinds & {"원문에 없는 값", "인용 없음", "표 없음", "깨진 글자"} else
               "확인 필요" if "칸 확인 필요" in kinds else "경고" if weighty else "통과")
    # 파싱 상태: 인용 표가 모두 structure=ok면 글 대조 판정을 믿을 수 있다. 아니면 표 이미지 확인이 필요하다.
    parse_ok = all(c.get("structure") not in (None, "uncertain") and not c.get("uncertain_record_ids")
                   for table in spec.get("tables", [])
                   for c in tables.get((table.get("cite") or {}).get("table_id") or table.get("id")) or [{}])
    return {"section_no": spec["section_no"], "title": spec["title"], "calc_type": package.get("calc_type"),
            "verdict": verdict, "parse_ok": parse_ok, "cells": dict(cells), "problems": problems,
            "unmentioned_notes": weighty, "unmentioned_scope_notes": scope_only}


def main(argv: list[str]) -> int:
    out = None
    if "--json" in argv:
        out = Path(argv[argv.index("--json") + 1])
        argv = argv[:argv.index("--json")]
    division = argv[0] if argv else "공통"
    prefix = argv[1] if len(argv) > 1 else ""
    executable = set(json.loads((ROOT / "data/drafts/executable.json").read_text(encoding="utf-8"))["executable"])
    tables, sections, by_id = load_chunks()
    results = []
    for path in sorted((SPECS / division).glob("*.json"), key=lambda p: [int(n) if n.isdigit() else n
                                                                         for n in re.split(r"(\d+)", p.stem)]):
        package = json.loads(path.read_text(encoding="utf-8"))
        spec = package.get("draft") or {}
        if not str(spec.get("section_no", "")).startswith(prefix) or spec.get("id") not in executable:
            continue
        results.append(check(package, tables, sections, by_id))
    sys.stdout.reconfigure(encoding="utf-8")
    for r in results:
        cells = " ".join(f"{k}={v}" for k, v in r["cells"].items())
        print(f"{r['verdict']:6} {r['section_no']:8} {r['title'][:28]:28} [{r['calc_type']}] {cells}")
        for p in r["problems"][:6]:
            print("        -", p)
        for note in r["unmentioned_notes"]:
            print("        - 계산 영향 주석 미언급:", note)
    total = Counter(r["verdict"] for r in results)
    print("\n합계", len(results), dict(total))
    if out:
        out.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


def _selftest():
    assert has_number("수량 3 | 무근구조물 23", "23") and not has_number("수량 3 | 무근구조물 23", "2")
    assert list(leaves({"a": {"b": "1"}})) == [(("a", "b"), "1")]
    row = "철근 | 단위 인 | 수량 2 | 시공량 20m 이하 5.0 | 시공량 40m 이하 4.0"
    assert cell_state([[row]], ["철근", "40m이하"], "4.0", squash(row)) == "cell"
    assert cell_state([[row]], ["철근", "40m이하"], "5.0", squash(row)) == "none"
    assert cell_state([[row]], ["철근"], "2", squash(row)) == "cell"
    twins = ["철공 보통인부 | 단위 인 | 수량 3", "철공 보통인부 | 단위 인 | 수량 1"]
    assert cell_state([twins], ["철공"], "3", squash("\n".join(twins))) == "ambiguous"
    assert not has_word("크레인시공 | 단위 대", "크레인") and has_word("시공량(㎡) 85", "시공량")
    assert broken_text({"a": ["PDF 586? 비고"]}) and broken_text("5?") and not broken_text("몇 ㎡입니까? (예)")
    assert not broken_text("Is it used?") and not broken_text(r"외벽(?!\s*아님)")


if __name__ == "__main__":
    _selftest()
    raise SystemExit(main(sys.argv[1:]))
