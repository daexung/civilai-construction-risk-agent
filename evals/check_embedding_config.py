"""Check embedding provider, model safety, retry fallback and division without API calls."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.nodes.retrieve import _Fallback, make_search_index, retrieve  # noqa: E402
from agent.state import new_state  # noqa: E402
from agent.tools.search.bm25 import Index, load  # noqa: E402
from agent.tools.search.vector import ModelMismatchError, VectorIndex  # noqa: E402
from api.main import _search_out  # noqa: E402
from evals.build_draft_questions import collect as collect_draft_questions  # noqa: E402
from evals.compare_embedding_models import QueryCache  # noqa: E402
from pipeline.chunk import page_divisions  # noqa: E402
from pipeline import embed as embed_pipeline  # noqa: E402
from shared.embedding import (api_key, document_fingerprint, document_input, document_title,  # noqa: E402
                              embed_texts, query_input, rate_limit_error, settings)


class FakeModels:
    def __init__(self):
        self.calls = []

    def embed_content(self, *, model, contents, config):
        self.calls.append((model, contents, config))
        count = len(contents) if isinstance(contents, list) else 1
        vector = [1.0] + [0.0] * 3071
        return SimpleNamespace(embeddings=[SimpleNamespace(values=vector) for _ in range(count)])


class FakeServiceError(Exception):
    code = 503


class FakeLimitError(Exception):
    code = 429


def main() -> int:
    checks = []
    studio, vertex = settings("studio"), settings("vertex")
    chunk = {"section": "6-1-4 콘크리트 펌프차 타설", "subsection": None, "text": "작업조 설명"}
    checks.append(("provider별 모델", studio.model == "gemini-embedding-2"
                   and vertex.model == "gemini-embedding-001" and studio.dim == vertex.dim == 3072))
    with patch.dict(os.environ, {"EMBED_PROVIDER": "vertex"}):
        env_model = settings().model
    checks.append(("환경변수 제공처 우선", env_model == vertex.model))
    checks.append(("studio 입력 형식", document_input(chunk, studio) ==
                   "title: 6-1-4 콘크리트 펌프차 타설 | text: 작업조 설명"
                   and query_input("질문", studio) == "task: search result | query: 질문"))
    checks.append(("vertex 입력 형식", document_input(chunk, vertex) == "작업조 설명"
                   and query_input("질문", vertex) == "질문"))

    fake = SimpleNamespace(models=FakeModels())
    embed_texts(fake, [document_input(chunk, vertex)], config=vertex, titles=[document_title(chunk)])
    embed_texts(fake, [query_input("질문", vertex)], config=vertex, task="query")
    document_call, query_call = fake.models.calls
    checks.append(("vertex task type과 제목", document_call[0] == vertex.model
                   and document_call[2].task_type == "RETRIEVAL_DOCUMENT"
                   and document_call[2].title == document_title(chunk)
                   and query_call[2].task_type == "RETRIEVAL_QUERY"
                   and query_call[2].title is None))

    with patch.dict(os.environ, {"EMBED_PROVIDER": "vertex"}):
        try:
            make_search_index(offline=False)
        except ModelMismatchError as exc:
            mixed = "gemini-embedding-2" in str(exc) and vertex.model in str(exc)
        else:
            mixed = False
    checks.append(("색인·질문 모델 불일치 오류", mixed))

    attempts = []

    def succeeds_third(_client, _texts, **_kwargs):
        attempts.append(1)
        if len(attempts) < 3:
            raise FakeServiceError("UNAVAILABLE")
        return [[1.0] + [0.0] * 3071]

    index = VectorIndex(embed_fn=succeeds_third, client_factory=lambda: object(), sleep_fn=lambda _delay: None)
    index.embed_query("펌프차")
    checks.append(("질문 503 두 번 후 성공", len(attempts) == 3 and index.api_calls == 3))

    def always_fails(_client, _texts, **_kwargs):
        raise FakeServiceError("UNAVAILABLE")

    failed_vector = VectorIndex(embed_fn=always_fails, client_factory=lambda: object(),
                                sleep_fn=lambda _delay: None)

    class Primary:
        @property
        def api_calls(self):
            return failed_vector.api_calls

        def search(self, query, k):
            return failed_vector.search(query, k)

    bm25 = Index(load())
    fallback = _Fallback(Primary(), bm25)
    with patch("agent.nodes.retrieve.get_search", return_value=(fallback, "hybrid", None)):
        result = retrieve(new_state("펌프차"))
    checks.append(("질문 503 소진 시 BM25 대체", result["search_info"]["method"] == "bm25(대체)"
                   and result["search_info"]["fallback_reason"] == "FakeServiceError"
                   and result["search_info"]["api_calls"] == 3
                   and _search_out(result)["fallback_reason"] == "FakeServiceError"))

    divisions = page_divisions()
    checks.append(("쪽별 부문", divisions[186] == "공통" and divisions[982] == "유지관리"))

    multilingual = settings("vertex", "text-multilingual-embedding-002")
    checks.append(("vertex 모델 선택·차원", multilingual.model == "text-multilingual-embedding-002"
                   and multilingual.dim == 768))
    with patch.dict(os.environ, {"EMBED_PROVIDER": "vertex", "EMBED_MODEL": "text-multilingual-embedding-002"}):
        checks.append(("EMBED_MODEL 환경변수", settings().dim == 768))
    try:
        settings("vertex", "no-such-model")
    except ValueError:
        rejects_unknown_model = True
    else:
        rejects_unknown_model = False
    checks.append(("알 수 없는 EMBED_MODEL 거부", rejects_unknown_model))

    with patch.dict(os.environ, {"VERTEX_API_KEY_BULK": "bulk-key", "VERTEX_KEY_NAME": "VERTEX_API_KEY_BULK"}):
        checks.append(("VERTEX_KEY_NAME 설정", api_key(vertex) == "bulk-key"))

    with tempfile.TemporaryDirectory() as mismatch_dir:
        import pyarrow as pa
        import pyarrow.parquet as pq

        chunk = {"chunk_id": "m1", "section": "6-1-1", "subsection": None,
                 "section_no": "6-1-1", "source": {"pdf": "x", "page": 1, "table_id": None, "bbox": []},
                 "text": "임베딩 차원 확인용 텍스트"}
        root = Path(mismatch_dir)
        chunks_path = root / "chunks.jsonl"
        chunks_path.write_text(json.dumps(chunk, ensure_ascii=False) + "\n", encoding="utf-8")
        vectors_path = root / "vectors.parquet"
        schema = pa.schema([("chunk_id", pa.string()), ("model", pa.string()), ("dim", pa.int32()),
                            ("text_sha256", pa.string()), ("vector", pa.list_(pa.float32()))])
        row = {"chunk_id": "m1", "model": multilingual.model, "dim": 3072,  # Wrong dim for this model.
               "text_sha256": document_fingerprint(chunk, multilingual), "vector": [0.0] * 3072}
        pq.write_table(pa.Table.from_pylist([row], schema=schema), vectors_path)
        index_config_path = root / "index_config.json"
        index_config_path.write_text(json.dumps({
            "chunks": str(chunks_path), "vectors": str(vectors_path),
            "embed_provider": "vertex", "embed_model": "text-multilingual-embedding-002",
        }, ensure_ascii=False), encoding="utf-8")
        try:
            VectorIndex(config_path=index_config_path)
        except ModelMismatchError as exc:
            dim_mismatch = "차원" in str(exc)
        else:
            dim_mismatch = False
    checks.append(("차원 불일치 오류", dim_mismatch))

    with tempfile.TemporaryDirectory() as drafts_dir:
        root = Path(drafts_dir)
        for name, division, section_no, questions in (
            ("d1.json", "공통", "6-1-1", ["질문 하나", "", "질문 하나", "질문 둘"]),
            ("d2.json", "토목", "1-2-3", ["다른 질문", "다른 질문", "   "]),
        ):
            (root / name).write_text(json.dumps({
                "draft": {"division": division, "section_no": section_no}, "questions": questions,
            }, ensure_ascii=False), encoding="utf-8")
        draft_rows = collect_draft_questions(root)
        checks.append(("초안 질문 세트 생성", len(draft_rows) == 3
                       and [row["question"] for row in draft_rows] == ["질문 하나", "질문 둘", "다른 질문"]
                       and draft_rows[0]["division"] == "공통" and draft_rows[0]["section_no"] == "6-1-1"
                       and draft_rows[0]["order"] == 1 and draft_rows[1]["order"] == 4
                       and draft_rows[2]["division"] == "토목"))

    checks.append(("429 판별", rate_limit_error(FakeLimitError())
                   and not rate_limit_error(FakeServiceError())))
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "queries.jsonl"
        waits = []
        calls = []
        clock = [0.0]

        def sleep(seconds):
            waits.append(seconds)
            clock[0] += seconds

        def embed_once(_query):
            calls.append(1)
            if len(calls) == 1:
                raise FakeLimitError()
            return __import__("numpy").array([1.0] + [0.0] * 3071, dtype="float32")

        cache = QueryCache(path, pause=5, sleep_fn=sleep, clock_fn=lambda: clock[0])
        fake_index = SimpleNamespace(vector=SimpleNamespace(embedding=vertex))
        first = cache.embed(fake_index, "질문", embed_once)
        cache.embed(fake_index, "다른 질문", embed_once)
        second = QueryCache(path).embed(fake_index, "질문", lambda _query: (_ for _ in ()).throw(AssertionError()))
        checks.append(("비교 질문 429 60초 대기·캐시 재사용",
                       len(calls) == 3 and waits == [60, 5] and first.tolist() == second.tolist()))

        chunks = Path(directory) / "chunks.jsonl"
        chunks.write_text('{"chunk_id":"missing","section":"test","text":"test"}\n', encoding="utf-8")
        argv = ["embed", "--chunks", str(chunks), "--cache", str(Path(directory) / "empty.jsonl"),
                "--out", str(Path(directory) / "empty.parquet"), "--limit", "0"]
        with patch.object(sys, "argv", argv), patch.object(embed_pipeline, "write_parquet", return_value=0):
            try:
                embed_pipeline.main()
            except SystemExit as exc:
                incomplete = "누락된 임베딩 1개" in str(exc)
            else:
                incomplete = False
        checks.append(("임베딩 누락 시 실패 종료", incomplete))

        attempts, waits = [], []

        def vertex_embed(*_args, **_kwargs):
            attempts.append(1)
            if len(attempts) == 1:
                raise FakeLimitError()
            return [[1.0] + [0.0] * 3071]

        vertex_argv = ["embed", "--chunks", str(chunks), "--cache", str(Path(directory) / "vertex.jsonl"),
                       "--out", str(Path(directory) / "vertex.parquet"), "--pause", "0"]
        with patch.object(sys, "argv", vertex_argv), \
                patch.object(embed_pipeline, "settings", return_value=vertex), \
                patch.object(embed_pipeline, "client", return_value=object()), \
                patch.object(embed_pipeline, "embed_texts", side_effect=vertex_embed), \
                patch.object(embed_pipeline, "write_parquet", return_value=1), \
                patch.object(embed_pipeline.time, "sleep", side_effect=waits.append):
            embed_pipeline.main()
        checks.append(("Vertex 429 60초 뒤 재시도", len(attempts) == 2 and waits == [60]))
    for name, passed in checks:
        print(f"{'PASS' if passed else 'FAIL'} {name}")
    print(f"통과 {sum(passed for _, passed in checks)} / 전체 {len(checks)}")
    return 0 if all(passed for _, passed in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
