"""Check embedding provider, model safety, retry fallback and division without API calls."""

from __future__ import annotations

import os
import sys
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
from pipeline.chunk import page_divisions  # noqa: E402
from shared.embedding import (document_input, document_title, embed_texts,  # noqa: E402
                              query_input, settings)


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
    for name, passed in checks:
        print(f"{'PASS' if passed else 'FAIL'} {name}")
    print(f"통과 {sum(passed for _, passed in checks)} / 전체 {len(checks)}")
    return 0 if all(passed for _, passed in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
