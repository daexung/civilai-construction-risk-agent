"""Parquet 벡터로 하는 정확한 코사인 검색.

실행 예:
    python agent/search/vector.py "콘크리트 펌프차 타설 인력편성"

질문만 Gemini로 임베딩하고(API 호출 1회), 청크 벡터는 embeddings.parquet에서 메모리로 읽어
전체 청크와 코사인 유사도를 모두 계산한다(근사 탐색 없음).
rag.Index와 같은 모양(.chunks, .search)이라 rag.evidence로 같은 절 단위 근거를 만들 수 있다.
"""

import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline"))
from embed import DIM, MODEL, client, document_input, embed_texts, query_input, sha256  # noqa: E402

CHUNKS = ROOT / "data/processed/chunks.jsonl"
VECTORS = ROOT / "data/processed/embeddings.parquet"


class VectorIndex:
    def __init__(self, chunks_path: Path = CHUNKS, vectors_path: Path = VECTORS):
        import pyarrow.parquet as pq

        self.chunks = [json.loads(line) for line in chunks_path.read_text(encoding="utf-8").splitlines()
                       if line.strip()]
        by_id = {c["chunk_id"]: c for c in self.chunks}
        table = pq.read_table(vectors_path).to_pylist()
        rows = [r for r in table if r["model"] == MODEL and r["dim"] == DIM]
        # 청크 글자가 바뀌었는데 벡터가 옛것이면 쓰지 않는다
        self.stale = [r["chunk_id"] for r in rows
                      if r["chunk_id"] not in by_id or r["text_sha256"] != sha256(document_input(by_id[r["chunk_id"]]))]
        rows = [r for r in rows if r["chunk_id"] not in self.stale]
        self.missing = [c["chunk_id"] for c in self.chunks if c["chunk_id"] not in {r["chunk_id"] for r in rows}]
        self.ids = [r["chunk_id"] for r in rows]
        matrix = np.array([r["vector"] for r in rows], dtype=np.float32)
        self.matrix = matrix / np.linalg.norm(matrix, axis=1, keepdims=True)
        self.by_id = by_id
        self._client = None
        self.api_calls = 0
        self.last_embed_sec = 0.0

    def embed_query(self, query: str) -> np.ndarray:
        if self._client is None:
            self._client = client()
        started = time.perf_counter()
        vec = np.array(embed_texts(self._client, [query_input(query)])[0], dtype=np.float32)
        self.last_embed_sec = time.perf_counter() - started
        self.api_calls += 1
        return vec / np.linalg.norm(vec)

    def search(self, query: str, k: int = 5) -> list[tuple[float, dict]]:
        scores = self.matrix @ self.embed_query(query)
        top = np.argsort(-scores)[:k]
        return [(float(scores[i]), self.by_id[self.ids[i]]) for i in top]


def main() -> None:
    query = " ".join(sys.argv[1:]) or "콘크리트 펌프차 타설 인력편성"
    index = VectorIndex()
    if index.stale or index.missing:
        print(f"주의: 옛 벡터 {len(index.stale)}개, 벡터 없는 청크 {len(index.missing)}개. pipeline/embed.py를 다시 실행")
    for score, chunk in index.search(query, 5):
        src = chunk["source"]
        lines = chunk["text"].splitlines()
        preview = lines[1][:60] if len(lines) > 1 else ""
        print(f"{score:.4f} {chunk['chunk_id']:10} {chunk['section_no']} PDF {src['page']}쪽 "
              f"{src['table_id'] or '줄글'} | {preview}")
    print(f"API 호출 {index.api_calls}회 (질문 임베딩 {index.last_embed_sec:.2f}초)")


if __name__ == "__main__":
    main()
