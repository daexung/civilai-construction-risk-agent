"""Prepare search and handle hybrid failures."""

from agent.tools.search.bm25 import CHUNKS, Index, load

def make_search_index(offline: bool, hybrid_factory=None):
    """(검색 인덱스, 방식 이름, 경고). 하이브리드를 만들 수 없으면 BM25로 대신한다."""
    bm25 = Index(load(CHUNKS))
    if offline:
        return bm25, "bm25(오프라인 지정)", None
    try:
        if hybrid_factory is None:
            from agent.tools.search.hybrid import HybridIndex
            hybrid_factory = HybridIndex
        return hybrid_factory(bm25=bm25), "hybrid", None
    except Exception as exc:  # noqa: BLE001 - 패키지·벡터 파일 문제
        return bm25, "bm25(대체)", f"하이브리드 검색을 준비하지 못해 BM25로 대신했습니다: {type(exc).__name__}"


class _Fallback:
    """하이브리드 검색이 질문 처리 중 실패하면(키 없음·호출 한도·네트워크) BM25로 한 번 대신한다."""

    def __init__(self, primary, bm25):
        self.primary, self.bm25 = primary, bm25
        self.chunks = primary.chunks
        self.used, self.error = "hybrid", None

    def search(self, query, k=5):
        try:
            return self.primary.search(query, k)
        except Exception as exc:  # noqa: BLE001
            self.used, self.error = "bm25(대체)", f"{type(exc).__name__}: {str(exc)[:120]}"
            return self.bm25.search(query, k)


