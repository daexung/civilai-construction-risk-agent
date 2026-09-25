"""BM25와 벡터 검색 결과를 RRF(Reciprocal Rank Fusion)로 합치는 하이브리드 검색.

실행 예:
    python backend/hybrid.py "펌프차 타설 현장조건 f2 계수"

점수 = Σ 1 / (K + 순위). 각 방식에서 상위 CANDIDATES개까지만 순위를 매긴다.
두 방식의 점수 크기(BM25 점수, 코사인)를 섞지 않고 순위만 쓰므로 가중치 조정이 필요 없다.
질문마다 임베딩 API를 1회 호출한다(벡터 쪽). BM25·벡터 코드는 그대로 가져다 쓴다.
rag.Index와 같은 모양(.chunks, .search)이라 rag.evidence로 같은 절 단위 근거를 만들 수 있다.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from rag import CHUNKS, Index, load  # noqa: E402
from vector import VectorIndex  # noqa: E402

K = 60             # RRF 표준 상수
CANDIDATES = 20    # 방식마다 합치기에 쓰는 상위 순위 수


class HybridIndex:
    def __init__(self, bm25: Index | None = None, vector: VectorIndex | None = None):
        self.vector = vector or VectorIndex()
        self.bm25 = bm25 or Index(load(CHUNKS))
        self.chunks = self.vector.chunks
        self.by_id = {c["chunk_id"]: c for c in self.chunks}
        self.last_ranks: dict[str, dict] = {}

    @property
    def api_calls(self) -> int:
        return self.vector.api_calls

    def search(self, query: str, k: int = 5) -> list[tuple[float, dict]]:
        ranks: dict[str, dict] = {}
        for name, hits in (("bm25", self.bm25.search(query, CANDIDATES)),
                           ("vector", self.vector.search(query, CANDIDATES))):
            for rank, (_, chunk) in enumerate(hits, 1):
                ranks.setdefault(chunk["chunk_id"], {})[name] = rank
        scored = [(sum(1 / (K + r) for r in rs.values()), cid) for cid, rs in ranks.items()]
        scored.sort(key=lambda s: -s[0])
        self.last_ranks = ranks
        return [(score, self.by_id[cid]) for score, cid in scored[:k]]


def main() -> None:
    query = " ".join(sys.argv[1:]) or "펌프차 타설 현장조건 f2 계수"
    index = HybridIndex()
    for score, chunk in index.search(query, 5):
        r = index.last_ranks[chunk["chunk_id"]]
        src = chunk["source"]
        print(f"{score:.4f} {chunk['chunk_id']:10} {chunk['section_no']} PDF {src['page']}쪽 "
              f"{src['table_id'] or '줄글'} (BM25 {r.get('bm25', '-')}위, 벡터 {r.get('vector', '-')}위)")
    print(f"임베딩 API 호출 {index.api_calls}회")


if __name__ == "__main__":
    main()
