"""청크 검색과 근거 묶음.

실행 예:
    python -m agent.tools.search.bm25 search "레미콘 인력운반 타설 콘크리트공 인원"


검색은 외부 API 없이 BM25(낱말 + 한글 두 글자 조각)로 한다. 답변 문장 생성(LLM)은 연결하지 않았다.
결과마다 절 번호, PDF 쪽, 원문 표 번호와 bbox를 붙여 원문으로 돌아갈 수 있게 한다.
"""

import argparse
import json
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["search"])
    parser.add_argument("query")
    parser.add_argument("-k", type=int, default=3)
    args = parser.parse_args()
    ev = evidence(Index(load()), args.query, args.k)
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


if __name__ == "__main__":
    main()
