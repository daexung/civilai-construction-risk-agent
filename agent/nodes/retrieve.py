"""질문과 가까운 품셈 청크를 상태에 전달한다."""

import os
from functools import cache

from agent.state import AgentState
from agent.tools.search.bm25 import CHUNKS, Index, load


class _Fallback:
    """하이브리드 질의가 실패하면 같은 질문을 BM25로 재검색한다."""

    def __init__(self, primary, bm25: Index):
        self.primary = primary
        self.bm25 = bm25
        self.used = "hybrid"
        self.error: str | None = None

    @property
    def api_calls(self) -> int:
        return self.primary.api_calls

    def search(self, query: str, k: int = 10):
        self.used, self.error = "hybrid", None
        try:
            return self.primary.search(query, k)
        except Exception as exc:  # API·벡터 검색 오류
            self.used = "bm25(대체)"
            self.error = f"하이브리드 검색 실패로 BM25로 대신했습니다: {type(exc).__name__}: {str(exc)[:120]}"
            return self.bm25.search(query, k)


def make_search_index(offline: bool, hybrid_factory=None):
    """검색 인덱스와 초기 검색 방식·경고를 만든다."""
    bm25 = Index(load(CHUNKS))
    if offline:
        return bm25, "bm25(오프라인)", None
    try:
        if hybrid_factory is None:
            from agent.tools.search.hybrid import HybridIndex
            hybrid_factory = HybridIndex
        return _Fallback(hybrid_factory(bm25=bm25), bm25), "hybrid", None
    except Exception as exc:  # 패키지·벡터 파일 오류
        return bm25, "bm25(대체)", f"하이브리드 검색을 준비하지 못해 BM25로 대신했습니다: {type(exc).__name__}: {str(exc)[:120]}"


@cache
def get_search():
    """프로세스에서 검색 인덱스를 한 번 준비한다."""
    return make_search_index(os.getenv("AGENT_OFFLINE") == "1")


def retrieve(state: AgentState) -> dict:
    index, method, warning = get_search()
    before = getattr(index, "api_calls", 0)
    found = index.search(state["query"], 10)
    if isinstance(index, _Fallback):
        method = index.used
        warning = index.error
    hits = [
        {
            "rank": rank,
            "score": score,
            "chunk_id": chunk["chunk_id"],
            "kind": chunk["kind"],
            "section_no": chunk["section_no"],
            "section": chunk["section"],
            "page": chunk["source"]["page"],
            "table_id": chunk["source"].get("table_id"),
            "structure": chunk["structure"],
            "text": chunk["text"][:200],
        }
        for rank, (score, chunk) in enumerate(found, 1)
    ]
    return {"hits": hits, "search_info": {
        "method": method,
        "api_calls": getattr(index, "api_calls", 0) - before,
        "warnings": [warning] if warning else [],
    }}
