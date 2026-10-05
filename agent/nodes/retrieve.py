"""질문과 가까운 품셈 청크를 상태에 전달한다."""

import os
from functools import cache

from agent.state import AgentState
from agent.tools.search.bm25 import Index, load
from agent.tools.search.vector import MissingVectorsError, ModelMismatchError, load_index_config


class _Fallback:
    """하이브리드 질의가 실패하면 같은 질문을 BM25로 재검색한다."""

    def __init__(self, primary, bm25: Index):
        self.primary = primary
        self.bm25 = bm25
        self.used = "hybrid"
        self.error: str | None = None
        self.fallback_reason: str | None = None

    @property
    def api_calls(self) -> int:
        return self.primary.api_calls

    def search_many(self, queries: list[str], k: int = 10):
        self.used, self.error, self.fallback_reason = "hybrid", None, None
        try:
            if hasattr(self.primary, "search_many"):
                return self.primary.search_many(queries, k)
            return _merge_query_hits([(query, self.primary.search(query, k)) for query in queries], k)
        except Exception as exc:
            self.used = "bm25(fallback)"
            self.fallback_reason = type(exc).__name__
            self.error = f"Hybrid search failed; using BM25: {self.fallback_reason}"
            return _merge_query_hits([(query, self.bm25.search(query, k)) for query in queries], k)

    def search(self, query: str, k: int = 10):
        self.used, self.error, self.fallback_reason = "hybrid", None, None
        try:
            return self.primary.search(query, k)
        except Exception as exc:  # API·벡터 검색 오류
            self.used = "bm25(대체)"
            self.fallback_reason = type(exc).__name__
            self.error = f"하이브리드 검색 실패로 BM25로 대신했습니다: {self.fallback_reason}"
            return self.bm25.search(query, k)


def _merge_query_hits(results, k: int):
    from agent.tools.search.hybrid import K
    chunks, scores = {}, {}
    for _query, hits in results:
        for rank, (score, chunk) in enumerate(hits, 1):
            cid = chunk["chunk_id"]
            chunks[cid] = chunk
            scores[cid] = scores.get(cid, 0.0) + 1 / (K + rank)
    return [(score, chunks[cid]) for cid, score in sorted(scores.items(), key=lambda item: -item[1])[:k]]


def make_search_index(offline: bool, hybrid_factory=None):
    """검색 인덱스와 초기 검색 방식·경고를 만든다."""
    config = load_index_config()
    chunks = load(config["chunks"])
    if "divisions" in config:
        enabled = set(config["divisions"])
        chunks = [chunk for chunk in chunks if chunk.get("division") in enabled]
    bm25 = Index(chunks)
    if offline:
        return bm25, "bm25(오프라인)", None
    try:
        if hybrid_factory is None:
            from agent.tools.search.hybrid import HybridIndex
            hybrid_factory = HybridIndex
        return _Fallback(hybrid_factory(bm25=bm25), bm25), "hybrid", None
    except (ModelMismatchError, MissingVectorsError):
        raise
    except Exception as exc:  # 패키지·벡터 파일 오류
        return bm25, "bm25(대체)", f"하이브리드 검색을 준비하지 못해 BM25로 대신했습니다: {type(exc).__name__}: {str(exc)[:120]}"


@cache
def get_search():
    """프로세스에서 검색 인덱스를 한 번 준비한다."""
    return make_search_index(os.getenv("AGENT_OFFLINE") == "1")


def retrieve(state: AgentState) -> dict:
    index, method, warning = get_search()
    queries = [state["query"]]
    search_query = state.get("search_query", "").strip()
    if state.get("route_source") in ("llm", "llm_low_confidence") and search_query and search_query != queries[0]:
        queries.append(search_query)
    before = getattr(index, "api_calls", 0)
    if len(queries) == 1:
        found = index.search(queries[0], 10)
    elif hasattr(index, "search_many"):
        found = index.search_many(queries, 10)
    else:
        found = _merge_query_hits([(query, index.search(query, 10)) for query in queries], 10)
    if isinstance(index, _Fallback):
        method = index.used
        warning = index.error
    hits = [
        {"rank": rank, "score": score, "chunk_id": chunk["chunk_id"], "kind": chunk["kind"],
         "section_no": chunk["section_no"], "division": chunk.get("division", "??"),
         "section": chunk["section"], "page": chunk["source"]["page"],
         "table_id": chunk["source"].get("table_id"), "structure": chunk["structure"],
         "text": chunk["text"][:200]}
        for rank, (score, chunk) in enumerate(found, 1)
    ]
    return {"hits": hits, "search_info": {
        "method": method, "queries": queries,
        "api_calls": getattr(index, "api_calls", 0) - before,
        "warnings": [warning] if warning else [],
        "fallback_reason": index.fallback_reason if isinstance(index, _Fallback) else None,
    }}
