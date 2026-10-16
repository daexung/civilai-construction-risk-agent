"""Read-only, no-embedding adapter for the saved knowledge-v1 release.

The local trial calls the same Retriever.search implementation as knowledge-v1,
using a verified on-disk chunk/vector release and its exact query cache. It never
opens a DB, creates an embedding client, writes a cache, or falls back to BM25.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from collections import defaultdict
from functools import cache
from pathlib import Path
from typing import Any

import numpy as np


class SearchAssetsUnavailable(RuntimeError):
    """The pinned, read-only release is missing or inconsistent."""


class QueryCacheMiss(RuntimeError):
    """The query is not in the saved exact query cache; embedding is disabled."""


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SearchAssetsUnavailable(f"검색 자산을 읽을 수 없습니다: {path.name}") from exc
    if not isinstance(value, dict):
        raise SearchAssetsUnavailable(f"검색 자산 형식이 올바르지 않습니다: {path.name}")
    return value


def _rows(path: Path) -> list[dict[str, Any]]:
    try:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, ValueError) as exc:
        raise SearchAssetsUnavailable(f"검색 자산을 읽을 수 없습니다: {path.name}") from exc


def _verify_manifest_files(directory: Path, manifest: dict[str, Any]) -> None:
    expected = manifest.get("files_sha256")
    if not isinstance(expected, dict) or not expected:
        raise SearchAssetsUnavailable(f"파일 해시 목록이 없습니다: {manifest.get('release_id') or manifest.get('chunk_set_id')}")
    for relative, digest in expected.items():
        path = (directory / relative).resolve()
        if directory.resolve() not in path.parents or not path.is_file():
            raise SearchAssetsUnavailable(f"manifest 파일이 없거나 경로가 올바르지 않습니다: {Path(relative).name}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise SearchAssetsUnavailable(f"manifest 파일 해시가 다릅니다: {path.name}")


def _asset_root() -> Path:
    configured = os.environ.get("KNOWLEDGE_ASSET_DIR")
    root = Path(configured).expanduser() if configured else Path(__file__).resolve().parents[3] / "data/knowledge"
    if not root.is_absolute():
        root = Path.cwd() / root
    return root.resolve()


class LocalV1Search:
    """Use persisted v1 vectors and Retriever.search without DB or embedding calls."""

    def __init__(self) -> None:
        self.assets = _asset_root()
        project = self.assets.parent.parent
        self.manifest = _json(self.assets / "manifest.json")
        if not self.manifest.get("ready"):
            raise SearchAssetsUnavailable("저장된 knowledge-v1 벡터가 준비 상태가 아닙니다")
        self.chunk_set_id = str(self.manifest.get("chunk_set_id") or "")
        self.release_id = str(self.manifest.get("release_id") or "")
        if not self.chunk_set_id or not self.release_id:
            raise SearchAssetsUnavailable("검색 자산 manifest에 release/chunk set 정보가 없습니다")

        out = project / "experiments/retrieval-v1/out"
        chunk_dir = out / "chunks" / self.chunk_set_id
        release_dir = out / self.release_id
        chunk_manifest = _json(chunk_dir / "manifest.json")
        import_manifest = _json(chunk_dir / "import_manifest.json")
        release_manifest = _json(release_dir / "manifest.json")
        if (chunk_manifest.get("chunk_set_id") != self.chunk_set_id
                or import_manifest.get("chunk_set_id") != self.chunk_set_id
                or import_manifest.get("release_id") != self.release_id
                or release_manifest.get("release_id") != self.release_id
                or release_manifest.get("status") != "loaded_complete"):
            raise SearchAssetsUnavailable("release와 chunk set이 서로 맞지 않습니다")
        _verify_manifest_files(chunk_dir, chunk_manifest)
        _verify_manifest_files(release_dir, release_manifest)

        chunks_path = chunk_dir / "chunks.jsonl"
        chunks = _rows(chunks_path)
        if not chunks or any(row.get("chunk_set_id") != self.chunk_set_id
                             or row.get("release_id") != self.release_id for row in chunks):
            raise SearchAssetsUnavailable("chunk 파일의 release/chunk set이 일치하지 않습니다")
        self.by_id = {row["chunk_id"]: row for row in chunks if isinstance(row.get("chunk_id"), str)}
        if len(self.by_id) != len(chunks) or len(self.by_id) != self.manifest.get("targets"):
            raise SearchAssetsUnavailable("chunk ID가 중복되거나 manifest 개수와 다릅니다")

        vectors_path = self.assets / "vectors.parquet"
        if hashlib.sha256(vectors_path.read_bytes()).hexdigest() != self.manifest.get("vectors_parquet_sha256"):
            raise SearchAssetsUnavailable("벡터 파일 체크섬이 manifest와 다릅니다")
        try:
            import pyarrow.parquet as pq
            table = pq.read_table(vectors_path, columns=["chunk_id", "input_sha256", "model", "dim",
                                                         "input_format", "vector"])
            vector_rows = table.to_pylist()
        except Exception as exc:
            raise SearchAssetsUnavailable(f"벡터 파일을 읽을 수 없습니다: {type(exc).__name__}") from exc
        vectors = {row["chunk_id"]: row for row in vector_rows}
        if len(vectors) != len(vector_rows) or set(vectors) != set(self.by_id):
            raise SearchAssetsUnavailable("chunk와 vector의 ID 집합이 다릅니다")

        from backend.shared.embedding import sha256
        model, dim = self.manifest.get("model"), self.manifest.get("dim")
        input_format = self.manifest.get("input_format")
        matrix = []
        for chunk in chunks:
            row = vectors[chunk["chunk_id"]]
            expected = sha256(f"title: none | text: {chunk['text']}")
            if (row["input_sha256"] != expected or row["model"] != model or row["dim"] != dim
                    or row["input_format"] != input_format):
                raise SearchAssetsUnavailable("chunk 입력 해시와 저장 벡터의 버전이 다릅니다")
            vector = np.asarray(row["vector"], dtype=np.float32)
            if vector.shape != (dim,) or not np.isfinite(vector).all() or np.linalg.norm(vector) == 0:
                raise SearchAssetsUnavailable("저장 벡터의 차원 또는 값이 올바르지 않습니다")
            matrix.append(vector)
        self.matrix = np.stack(matrix)
        self.matrix /= np.linalg.norm(self.matrix, axis=1, keepdims=True)

        registry = _json(release_dir / "section_registry.json")
        if registry.get("release_id") != self.release_id or not isinstance(registry.get("sections"), list):
            raise SearchAssetsUnavailable("절 목록의 release가 일치하지 않습니다")
        self.sections = {item["section_id"]: item for item in registry["sections"]
                         if isinstance(item.get("section_id"), str)}
        if any(chunk.get("section_id") and chunk["section_id"] not in self.sections for chunk in chunks):
            raise SearchAssetsUnavailable("절 목록에 chunk의 section ID가 없습니다")
        for chunk in chunks:
            sources = chunk.get("sources")
            if not isinstance(sources, list) or any(not isinstance(source, dict)
                    or source.get("role") not in ("body", "scope_quote", "context_subheading", "context_basis")
                    or not isinstance(source.get("search_uid"), str) for source in sources):
                raise SearchAssetsUnavailable("chunk의 인용 출처 역할/UID가 올바르지 않습니다")

        cache_dir = out / "embeddings" / self.chunk_set_id / (
            f"{self.manifest.get('provider')}-{model}-{dim}-query-task-search-result-v1")
        query_cache_path = cache_dir / "queries.jsonl"
        query_rows = _rows(query_cache_path)
        self.query_cache: dict[tuple, dict[str, Any]] = {}
        for row in query_rows:
            key = (row.get("input_sha256"), row.get("provider"), row.get("model"), row.get("dim"),
                   row.get("input_format"), row.get("purpose"))
            if (row.get("provider") != self.manifest.get("provider") or row.get("model") != model
                    or row.get("dim") != dim or row.get("input_format") != "query-task-search-result-v1"
                    or row.get("purpose") != "query"):
                raise SearchAssetsUnavailable("질의 캐시의 임베딩 설정이 벡터 release와 다릅니다")
            decoded = np.frombuffer(base64.b64decode(row["vector_f32_b64"], validate=True), dtype="<f4")
            if decoded.shape != (dim,) or not np.isfinite(decoded).all() or np.linalg.norm(decoded) == 0:
                raise SearchAssetsUnavailable("저장된 질의 벡터가 올바르지 않습니다")
            self.query_cache[key] = row
        if not self.query_cache:
            raise SearchAssetsUnavailable("재사용할 질의 캐시가 없습니다")
        # Retriever.query_vector clears the cache at 128 entries. A full 128-row
        # read-only cache would therefore be discarded before its lookup.
        if len(self.query_cache) >= 128:
            raise SearchAssetsUnavailable("기존 Retriever의 질의 캐시 한도(127개)를 넘어 안전한 재사용을 중단했습니다")

        # Build only the fields used by the existing Retriever.search implementation.
        # Its normal constructor opens a DB and permits embedding; this object deliberately
        # skips that constructor and supplies the verified immutable release artifacts.
        from backend.knowledge import retrieve as rv
        from backend.agent.tools.search.bm25 import Index
        from backend.knowledge import embed_index as ei

        if ei.CS != self.chunk_set_id or ei.CFG.model != model or ei.CFG.dim != dim:
            raise SearchAssetsUnavailable("실행 코드 설정과 저장된 v1 release가 다릅니다")
        rt = rv.Retriever.__new__(rv.Retriever)
        rt.own = False
        rt.conn = None
        rt.reader = None
        rt.items = chunks
        rt.by_id = self.by_id
        rt.has_vectors = True
        rt.manifest = self.manifest
        rt.matrix = self.matrix
        rt.ids = [chunk["chunk_id"] for chunk in chunks]
        rt.pos = {chunk_id: pos for pos, chunk_id in enumerate(rt.ids)}
        rt.division_of = np.asarray([self.by_id[cid].get("division") or "" for cid in rt.ids])
        rt.chunk_dicts = [{"chunk_id": cid, "text": self.by_id[cid]["text"],
                           "division": self.by_id[cid].get("division")} for cid in rt.ids]
        rt.bm25_all = Index(rt.chunk_dicts)
        rt.bm25_div = {}
        rt.quotes = defaultdict(set)
        for chunk in chunks:
            for source in chunk.get("sources") or []:
                if source.get("role") in ("body", "scope_quote") and source.get("search_uid"):
                    rt.quotes[chunk["chunk_id"]].add(source["search_uid"])
        rt.q_cache = self.query_cache
        rt.embed_queries = False
        rt.client = None
        rt.api_calls = 0
        rt.api_new_vectors = 0
        rt.api_cache_hits = 0
        self.retriever = rt
        self.sections_by_id = self.sections

    def search(self, query: str, limit: int = 10) -> dict[str, Any]:
        before_hits = self.retriever.api_cache_hits
        try:
            result = self.retriever.search(query, mode="hybrid")
        except RuntimeError as exc:
            if "캐시에 없고 임베딩 호출이 꺼져 있음" in str(exc):
                raise QueryCacheMiss("이 질문의 기존 임베딩 캐시가 없어 검색하지 않았습니다") from None
            raise
        hits = []
        for rank, selected in enumerate(result["fused"][:limit], 1):
            chunk = self.by_id[selected["chunk_id"]]
            section = self.sections_by_id.get(chunk.get("section_id"), {})
            number, title = section.get("number"), section.get("title") or chunk.get("title") or ""
            hits.append({"rank": rank, "score": selected["score"], "chunk_id": chunk["chunk_id"],
                         "kind": chunk.get("kind"), "section_no": number,
                         "division": (section.get("division") or chunk.get("division") or "").removesuffix("부문"),
                         "section": f"{number or ''} {title}".strip(),
                         "page": chunk.get("page_first"), "table_id": None,
                         "structure": {}, "text": chunk.get("text", "")[:200]})
        if self.retriever.api_calls != 0:
            raise SearchAssetsUnavailable("검색 중 외부 임베딩 호출이 감지되었습니다")
        return {"hits": hits, "search_info": {
            "method": "knowledge-v1-hybrid-local-cache", "queries": [query], "api_calls": 0,
            "query_cache_hit": self.retriever.api_cache_hits > before_hits,
            "release_id": self.release_id, "chunk_set_id": self.chunk_set_id,
            "vectors_sha256": self.manifest.get("vectors_parquet_sha256")}}


@cache
def get_local_v1_search() -> LocalV1Search:
    return LocalV1Search()
