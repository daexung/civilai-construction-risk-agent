"""Exact cosine search over model-checked Parquet vectors."""

from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

from shared.embedding import (ROOT, client, document_fingerprint, embed_texts,
                              query_input, retryable_error, settings)
from agent.rules.scope import enabled_divisions

DEFAULT_CONFIG = Path(__file__).with_name("index_config.json")


class ModelMismatchError(ValueError):
    """The selected index cannot be queried with the configured embedding model."""


class MissingVectorsError(ValueError):
    """An enabled division has chunks without current embeddings."""


def load_index_config(path: str | Path | None = None) -> dict:
    source = Path(path or os.environ.get("INDEX_CONFIG") or DEFAULT_CONFIG)
    if not source.is_absolute():
        source = ROOT / source
    data = json.loads(source.read_text(encoding="utf-8"))
    for field in ("chunks", "vectors", "embed_provider"):
        if field not in data:
            raise ValueError(f"색인 설정 누락: {field} ({source})")
    result = dict(data)
    if path is None and not os.environ.get("INDEX_CONFIG"):
        result["divisions"] = enabled_divisions()
    for field in ("chunks", "vectors"):
        location = Path(data[field])
        result[field] = location if location.is_absolute() else ROOT / location
    result["config_path"] = source
    return result


class VectorIndex:
    def __init__(self, chunks_path: Path | None = None, vectors_path: Path | None = None,
                 *, config_path: Path | None = None, embed_fn=None, client_factory=None,
                 sleep_fn=time.sleep):
        import pyarrow.parquet as pq

        index_config = load_index_config(config_path)
        selected_provider = (index_config["embed_provider"] if config_path is not None else
                             os.environ.get("EMBED_PROVIDER") or index_config["embed_provider"])
        selected_model = (index_config.get("embed_model") if config_path is not None else
                          os.environ.get("EMBED_MODEL") or index_config.get("embed_model"))
        self.embedding = settings(selected_provider, selected_model)
        chunks_path = chunks_path or index_config["chunks"]
        vectors_path = vectors_path or index_config["vectors"]
        self.chunks = [json.loads(line) for line in Path(chunks_path).read_text(encoding="utf-8").splitlines()
                       if line.strip()]
        if "divisions" in index_config:
            enabled = set(index_config["divisions"])
            self.chunks = [chunk for chunk in self.chunks if chunk.get("division") in enabled]
        self.by_id = {chunk["chunk_id"]: chunk for chunk in self.chunks}
        table = pq.read_table(vectors_path).to_pylist()
        models = {row["model"] for row in table}
        if models != {self.embedding.model}:
            raise ModelMismatchError(
                f"색인 모델 {sorted(models)}과 질문 모델 {self.embedding.model}이 다릅니다: {vectors_path}")
        if any(row["dim"] != self.embedding.dim for row in table):
            raise ModelMismatchError(f"색인 차원과 질문 차원이 다릅니다: {vectors_path}")
        if "divisions" in index_config:
            table = [row for row in table if row["chunk_id"] in self.by_id]
        self.stale = [row["chunk_id"] for row in table if
                      row["chunk_id"] not in self.by_id or
                      row["text_sha256"] != document_fingerprint(self.by_id[row["chunk_id"]], self.embedding)]
        rows = [row for row in table if row["chunk_id"] in self.by_id and row["chunk_id"] not in self.stale]
        self.missing = [chunk["chunk_id"] for chunk in self.chunks
                        if chunk["chunk_id"] not in {row["chunk_id"] for row in rows}]
        if self.missing and "divisions" in index_config:
            counts = Counter(self.by_id[chunk_id]["division"] for chunk_id in self.missing)
            detail = ", ".join(f"{division} {counts[division]}개" for division in index_config["divisions"]
                               if counts[division])
            raise MissingVectorsError(f"켜진 부문의 임베딩 벡터 누락: {detail}")
        self.ids = [row["chunk_id"] for row in rows]
        if not rows:
            raise ValueError(f"사용 가능한 임베딩 벡터가 없습니다: {vectors_path}")
        matrix = np.array([row["vector"] for row in rows], dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        if np.any(norms == 0):
            raise ValueError(f"길이 0인 임베딩 벡터가 있습니다: {vectors_path}")
        self.matrix = matrix / norms
        self._client = None
        self._client_factory = client_factory or (lambda: client(self.embedding))
        self._embed_fn = embed_fn or embed_texts
        self._sleep_fn = sleep_fn
        self.api_calls = 0
        self.last_embed_sec = 0.0

    def embed_queries(self, queries: list[str]) -> list[np.ndarray]:
        if self._client is None:
            self._client = self._client_factory()
        started = time.perf_counter()
        inputs = [query_input(query, self.embedding) for query in queries]
        for attempt in range(3):
            try:
                self.api_calls += 1
                raw_vectors = self._embed_fn(self._client, inputs, config=self.embedding, task="query")
                vectors = []
                for raw in raw_vectors:
                    vector = np.asarray(raw, dtype=np.float32)
                    norm = np.linalg.norm(vector)
                    if norm == 0:
                        raise ValueError("query embedding has zero norm")
                    vectors.append(vector / norm)
                self.last_embed_sec = time.perf_counter() - started
                return vectors
            except Exception as exc:
                if not retryable_error(exc) or attempt == 2:
                    self.last_embed_sec = time.perf_counter() - started
                    raise
                self._sleep_fn((1, 2)[attempt])
        raise RuntimeError("query embedding retry exhausted")

    def embed_query(self, query: str) -> np.ndarray:
        return self.embed_queries([query])[0]

    def search_many(self, queries: list[str], k: int = 5) -> list[list[tuple[float, dict]]]:
        vectors = self.embed_queries(queries)
        results = []
        for vector in vectors:
            scores = self.matrix @ vector
            top = np.argsort(-scores)[:k]
            results.append([(float(scores[index]), self.by_id[self.ids[index]]) for index in top])
        return results

    def search(self, query: str, k: int = 5) -> list[tuple[float, dict]]:
        return self.search_many([query], k)[0]


def main() -> None:
    query = " ".join(sys.argv[1:]) or "콘크리트 펌프차 타설 인력편성"
    index = VectorIndex()
    if index.stale or index.missing:
        print(f"주의: 옛 벡터 {len(index.stale)}개, 벡터 없는 청크 {len(index.missing)}개")
    for score, chunk in index.search(query, 5):
        src = chunk["source"]
        lines = chunk["text"].splitlines()
        preview = lines[1][:60] if len(lines) > 1 else ""
        print(f"{score:.4f} {chunk['chunk_id']:10} {chunk.get('division')} "
              f"{chunk['section_no']} PDF {src['page']}쪽 {src['table_id'] or '줄글'} | {preview}")
    print(f"API 호출 {index.api_calls}회 (질문 임베딩 {index.last_embed_sec:.2f}초)")


if __name__ == "__main__":
    main()
