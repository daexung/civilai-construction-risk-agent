"""청크 검색과 근거 묶음, 구조를 확인한 표에서만 하는 노무량 환산.

실행 예:
    python backend/rag.py search "레미콘 인력운반 타설 콘크리트공 인원"
    python backend/rag.py estimate --section 6-1-1 --method "인력운반 타설" --trade 콘크리트공 \\
        --column "시공량(㎥) 철근구조물" --volume 100

검색은 외부 API 없이 BM25(낱말 + 한글 두 글자 조각)로 한다. 답변 문장 생성(LLM)은 연결하지 않았다.
결과마다 절 번호, PDF 쪽, 원문 표 번호와 bbox를 붙여 원문으로 돌아갈 수 있게 한다.
"""

import argparse
import json
import math
import re
import unicodedata
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHUNKS = ROOT / "data/processed/chunks.jsonl"
PARSED = ROOT / "data/processed/parsed.jsonl"

WORD_RE = re.compile(r"\d+(?:-\d+)+|[0-9a-z.]+|[가-힣]+")
K1, B = 1.2, 0.75


def tokens(text: str) -> list[str]:
    text = unicodedata.normalize("NFKC", text).lower()
    out = []
    for word in WORD_RE.findall(text):
        out.append(word)
        if re.fullmatch(r"[가-힣]{3,}", word):
            out += [word[i:i + 2] for i in range(len(word) - 1)]
    return out


class Index:
    def __init__(self, chunks: list[dict]):
        self.chunks = chunks
        self.docs = [Counter(tokens(c["text"])) for c in chunks]
        self.lengths = [sum(d.values()) for d in self.docs]
        self.avg = sum(self.lengths) / len(self.lengths)
        df = Counter(t for d in self.docs for t in d)
        n = len(chunks)
        self.idf = {t: math.log(1 + (n - k + 0.5) / (k + 0.5)) for t, k in df.items()}

    def search(self, query: str, k: int = 5) -> list[tuple[float, dict]]:
        q = Counter(tokens(query))
        scored = []
        for doc, length, chunk in zip(self.docs, self.lengths, self.chunks):
            score = 0.0
            for t, qf in q.items():
                f = doc.get(t)
                if f:
                    score += qf * self.idf[t] * f * (K1 + 1) / (f + K1 * (1 - B + B * length / self.avg))
            if score > 0:
                scored.append((score, chunk))
        return sorted(scored, key=lambda s: -s[0])[:k]


def load(path: Path = CHUNKS) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def citation(chunk: dict) -> str:
    src = chunk["source"]
    where = f"표 {src['table_id']} bbox {src['bbox']}" if src["table_id"] else "줄글"
    sub = chunk.get("subsection")
    heading = f" {sub['no']}. {sub['title']}" if sub else ""
    return f"[{chunk['section_no'] or chunk['section']}{heading} | PDF {src['page']}쪽 | {where}]"


def parent_no(no: str | None) -> str | None:
    """6-1-4 → 6-1. 이미 상위 절이거나 번호가 없으면 None."""
    if not no or no.count("-") < 2:
        return None
    return no.rsplit("-", 1)[0]


def evidence(index: Index, query: str, k: int = 3) -> dict:
    """검색 상위 k개 청크를 절 단위 근거로 묶는다.

    - 선택된 청크가 속한 절은 그 절의 청크 전체를 원문 순서로 한 번만 담는다(여러 결과가 같은 절이면 묶는다).
    - 하위 절(6-1-4)이면 상위 절(6-1)의 청크 전체를 따로 한 번만 담는다. 상위 절 자체가 선택됐으면 중복하지 않는다.
    - 청크는 원래 필드(쪽·표 번호·bbox·기준 표기·구조 표시)를 그대로 유지한다.
    """
    hits = index.search(query, k)
    order = {c["chunk_id"]: n for n, c in enumerate(index.chunks)}
    sections: dict[str, dict] = {}
    for rank, (score, chunk) in enumerate(hits, 1):
        group = sections.setdefault(chunk["section"], {
            "section": chunk["section"], "section_no": chunk["section_no"], "hits": [],
            "chunks": [c for c in index.chunks if c["section"] == chunk["section"]]})
        group["hits"].append({"rank": rank, "score": round(score, 2), "chunk_id": chunk["chunk_id"]})

    selected_nos = {g["section_no"] for g in sections.values()}
    parents: dict[str, dict] = {}
    for group in sections.values():
        pno = parent_no(group["section_no"])
        if pno is None or pno in selected_nos or pno in parents:
            continue
        chunks = [c for c in index.chunks if c["section_no"] == pno]
        if chunks:
            parents[pno] = {"section": chunks[0]["section"], "section_no": pno, "chunks": chunks}
    for group in list(sections.values()) + list(parents.values()):
        group["chunks"].sort(key=lambda c: order[c["chunk_id"]])
    return {"query": query, "hits": [(round(s, 2), c) for s, c in hits],
            "sections": list(sections.values()), "parents": list(parents.values())}


def evidence_chunk_ids(ev: dict) -> list[str]:
    return [c["chunk_id"] for g in ev["sections"] + ev["parents"] for c in g["chunks"]]


# ---------------- 노무량 환산 (구조 확인한 표만) ----------------

def one_value(parts: list[str], prefix: str) -> Decimal:
    values = [p[len(prefix):] for p in parts if p.startswith(prefix)]
    if len(values) != 1:
        raise ValueError(f"'{prefix.strip()}' 값이 정확히 1개여야 합니다. 실제: {values}")
    value = Decimal(values[0].replace(",", ""))
    if not value.is_finite() or value <= 0:
        raise ValueError(f"'{prefix.strip()}' 값이 양수가 아닙니다: {values[0]}")
    return value


def estimate_labor(chunks: list[dict], records: list[dict], section: str, method: str | None,
                   trade: str, column: str, volume: str) -> dict:
    """직종 노무량(인·일) = 물량 ÷ 일당 시공량 × 작업조 인원.

    자동 계산은 아래를 모두 만족할 때만 한다. 하나라도 어긋나면 계산하지 않고 이유와 출처를 돌려준다.
      - 그 절에서 조건(method)·직종(trade)에 맞는 행이 정확히 한 표, 한 행
      - 그 표의 구조가 ok (행 합침·줄 수 불일치로 표시된 행이 없음)
      - 표 바로 위 기준 표기가 '(일당)'
      - 행에 '단위 인', '수량 x', '{column} y'가 각각 하나
    """
    tables = [c for c in chunks if c["kind"] == "table" and c["section_no"] == section]
    matches, loose = [], []
    for c in tables:
        for rid in c["record_ids"]:
            parts = [p.strip() for p in records[rid]["text"].split("|")]
            if method is not None and method not in parts:
                continue
            if trade in parts:
                matches.append((c, rid, parts))
            if any(trade in p for p in parts[1:]):
                # '형틀목공 보통인부'처럼 합쳐진 라벨 안에 든 경우도 모은다
                loose.append((c, rid))
    base = {"section": section, "method": method, "trade": trade, "column": column, "volume": volume}
    uncertain = [(c, rid) for c, rid in loose if rid in c["uncertain_record_ids"]]
    if uncertain:
        return {**base, "status": "refused", "sources": sorted({citation(c) for c, _ in uncertain}),
                "reason": "해당 직종이 구조가 불확실한 행(행 합침 또는 줄 수 불일치)에 있습니다. 원문 표를 확인해야 합니다.",
                "uncertain_rows": [records[rid]["text"] for _, rid in uncertain]}
    if len(matches) != 1:
        return {**base, "status": "refused", "reason": f"조건에 맞는 행이 {len(matches)}개입니다(정확히 1개 필요).",
                "sources": [citation(c) for c, _, _ in matches] or [citation(c) for c in tables]}
    chunk, rid, parts = matches[0]
    src = [citation(chunk)]
    if chunk["structure"] != "ok":
        return {**base, "status": "refused", "sources": src,
                "reason": "원문 표 구조가 불확실합니다(같은 표에 행 합침 또는 줄 수 불일치가 있음). 원문 표를 확인해야 합니다.",
                "uncertain_rows": [records[i]["text"] for i in chunk["uncertain_record_ids"]]}
    if chunk["basis"] != "(일당)":
        return {**base, "status": "refused", "sources": src,
                "reason": f"표의 기준 표기가 '(일당)'이 아닙니다: {chunk['basis']}"}
    if "단위 인" not in parts:
        return {**base, "status": "refused", "sources": src, "reason": "인력 단위(인)가 아닙니다."}
    try:
        crew = one_value(parts, "수량 ")
        output = one_value(parts, f"{column} ")
        days = Decimal(volume) / output * crew
    except (ValueError, InvalidOperation) as exc:
        return {**base, "status": "refused", "sources": src, "reason": str(exc)}
    return {**base, "status": "ok", "sources": src, "row": records[rid]["text"],
            "crew": str(crew), "daily_output": str(output), "person_days": str(days.normalize()),
            "note": "고정 조건의 노무량 환산만 한다. 할증·감산, 단가·금액은 적용하지 않았다."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("search")
    s.add_argument("query")
    s.add_argument("-k", type=int, default=3)
    e = sub.add_parser("estimate")
    e.add_argument("--section", required=True)
    e.add_argument("--method")
    e.add_argument("--trade", required=True)
    e.add_argument("--column", required=True)
    e.add_argument("--volume", required=True)
    args = parser.parse_args()

    chunks = load()
    if args.command == "search":
        ev = evidence(Index(chunks), args.query, args.k)
        print("검색 상위:")
        for n, (score, chunk) in enumerate(ev["hits"], 1):
            print(f"  #{n} {citation(chunk)} 점수 {score}")
        for label, groups in (("선택된 절", ev["sections"]), ("상위 절 설명", ev["parents"])):
            for group in groups:
                print(f"\n=== {label}: {group['section']} (청크 {len(group['chunks'])}개)")
                for chunk in group["chunks"]:
                    flag = " ※구조 불확실: 원문 확인 필요" if chunk["structure"] == "uncertain" else ""
                    print(f"\n{citation(chunk)}{flag}")
                    print(chunk["text"].split("\n", 1)[1] if "\n" in chunk["text"] else chunk["text"])
    else:
        records = [json.loads(line) for line in PARSED.read_text(encoding="utf-8").splitlines() if line.strip()]
        result = estimate_labor(chunks, records, args.section, args.method, args.trade, args.column, args.volume)
        print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
