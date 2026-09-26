"""Embedding inputs, model settings and API client shared by pipeline and serving."""

import hashlib
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL = "gemini-embedding-2"
DIM = 3072                      # 모델 기본 차원. 잘라 쓰지 않으므로 별도 정규화가 필요 없다


def api_key() -> str:
    """환경 변수, 없으면 저장소 .env에서 GEMINI_API_KEY를 읽는다. 값은 어디에도 출력하지 않는다."""
    key = os.environ.get("GEMINI_API_KEY")
    env = ROOT / ".env"
    if not key and env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            name, sep, value = line.partition("=")
            if sep and name.strip() == "GEMINI_API_KEY":
                key = value.strip().strip('"').strip("'")
    if not key:
        raise SystemExit("GEMINI_API_KEY가 없습니다(.env 또는 환경 변수)")
    return key


def document_input(chunk: dict) -> str:
    """문서 쪽 입력. 공식 문서의 검색 문서 형식 'title: {제목} | text: {내용}'."""
    sub = chunk.get("subsection")
    title = chunk["section"] + (f" {sub['no']}. {sub['title']}" if sub else "")
    return f"title: {title} | text: {chunk['text']}"


def query_input(query: str) -> str:
    """질문 쪽 입력. 공식 문서의 검색 질문 형식."""
    return f"task: search result | query: {query}"


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def client():
    from google import genai
    return genai.Client(api_key=api_key())


def embed_texts(cli, texts: list[str]) -> list[list[float]]:
    """입력마다 독립된 벡터를 받는다. 한 번의 API 호출(batchEmbedContents)."""
    from google.genai import types

    contents = [types.Content(parts=[types.Part(text=t)]) for t in texts]
    result = cli.models.embed_content(model=MODEL, contents=contents,
                                      config=types.EmbedContentConfig(output_dimensionality=DIM))
    vectors = [e.values for e in result.embeddings]
    if len(vectors) != len(texts):
        raise RuntimeError(f"입력 {len(texts)}개에 벡터 {len(vectors)}개: 입력이 합쳐졌을 수 있어 저장하지 않는다")
    if any(len(v) != DIM for v in vectors):
        raise RuntimeError(f"차원이 {DIM}이 아닌 벡터가 있다")
    return vectors

