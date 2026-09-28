"""Embedding configuration and model-specific inputs shared by pipeline and serving."""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = Path(__file__).with_name("embedding_config.json")
MODEL = "gemini-embedding-2"  # Existing index and saved evaluation metadata.
DIM = 3072
MODELS = {"studio": MODEL, "vertex": "gemini-embedding-001"}


@dataclass(frozen=True)
class EmbeddingSettings:
    provider: str
    model: str
    dim: int


def settings(provider: str | None = None) -> EmbeddingSettings:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    override = provider or os.environ.get("EMBED_PROVIDER")
    selected = override or config["provider"]
    if selected not in MODELS:
        raise ValueError(f"지원하지 않는 EMBED_PROVIDER: {selected}")
    if not override and config["model"] != MODELS[selected]:
        raise ValueError(f"임베딩 설정의 provider/model 조합이 다릅니다: {selected}/{config['model']}")
    return EmbeddingSettings(selected, MODELS[selected], int(config["dim"]))


def api_key(config: EmbeddingSettings | None = None) -> str:
    """Read only the selected credential name; never print the credential."""
    selected = config or settings()
    key_name = "VERTEX_API_KEY" if selected.provider == "vertex" else "GEMINI_API_KEY"
    key = os.environ.get(key_name)
    env = ROOT / ".env"
    if not key and env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            name, sep, value = line.partition("=")
            if sep and name.strip() == key_name:
                key = value.strip().strip('"').strip("'")
                break
    if not key:
        raise RuntimeError(f"{key_name}가 없습니다(.env 또는 환경 변수)")
    return key


def document_title(chunk: dict) -> str:
    sub = chunk.get("subsection")
    return chunk["section"] + (f" {sub['no']}. {sub['title']}" if sub else "")


def document_input(chunk: dict, config: EmbeddingSettings | None = None) -> str:
    selected = config or settings()
    if selected.provider == "vertex":
        return chunk["text"]
    return f"title: {document_title(chunk)} | text: {chunk['text']}"


def document_fingerprint(chunk: dict, config: EmbeddingSettings | None = None) -> str:
    selected = config or settings()
    body = document_input(chunk, selected)
    if selected.provider == "vertex":
        body = f"title: {document_title(chunk)} | text: {body}"
    return sha256(body)


def query_input(query: str, config: EmbeddingSettings | None = None) -> str:
    selected = config or settings()
    return query if selected.provider == "vertex" else f"task: search result | query: {query}"


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def client(config: EmbeddingSettings | None = None):
    from google import genai

    selected = config or settings()
    key = api_key(selected)
    return (genai.Client(vertexai=True, api_key=key) if selected.provider == "vertex"
            else genai.Client(api_key=key))


def _vectors(result, expected: int, dim: int) -> list[list[float]]:
    embeddings = result.embeddings or []
    vectors = [embedding.values for embedding in embeddings]
    if len(vectors) != expected:
        raise RuntimeError(f"입력 {expected}개에 벡터 {len(vectors)}개: 입력이 합쳐졌을 수 있어 저장하지 않는다")
    if any(len(vector) != dim for vector in vectors):
        raise RuntimeError(f"차원이 {dim}이 아닌 벡터가 있다")
    return vectors


def embed_texts(cli, texts: list[str], *, config: EmbeddingSettings | None = None,
                task: str = "document", titles: list[str] | None = None) -> list[list[float]]:
    """Return one vector per input, using each Vertex document's own title."""
    from google.genai import types

    selected = config or settings()
    if task not in ("document", "query"):
        raise ValueError(f"알 수 없는 임베딩 task: {task}")
    if titles is not None and len(titles) != len(texts):
        raise ValueError("제목 수와 입력 수가 다릅니다")
    if not texts:
        return []
    if selected.provider == "studio":
        contents = [types.Content(parts=[types.Part(text=text)]) for text in texts]
        result = cli.models.embed_content(model=selected.model, contents=contents,
            config=types.EmbedContentConfig(output_dimensionality=selected.dim))
        return _vectors(result, len(texts), selected.dim)

    # A document title is request-wide in the SDK config. Send each document
    # separately so the title cannot be applied to another input. Concurrency 1 <= 5.
    vectors = []
    for index, text in enumerate(texts):
        options = {"task_type": "RETRIEVAL_DOCUMENT" if task == "document" else "RETRIEVAL_QUERY"}
        if task == "document" and titles is not None:
            options["title"] = titles[index]
        result = cli.models.embed_content(model=selected.model, contents=text,
            config=types.EmbedContentConfig(**options))
        vector = _vectors(result, 1, selected.dim)[0]
        norm = math.sqrt(sum(value * value for value in vector))
        if not math.isfinite(norm) or norm == 0:
            raise RuntimeError("정규화할 수 없는 임베딩 벡터")
        vectors.append([value / norm for value in vector] if abs(norm - 1) > 1e-5 else vector)
    if len(vectors) != len(texts):
        raise RuntimeError(f"입력 {len(texts)}개에 벡터 {len(vectors)}개")
    return vectors


def retryable_error(exc: Exception) -> bool:
    code = getattr(exc, "code", None)
    if callable(code):
        try:
            code = code()
        except Exception:
            code = None
    code = code or getattr(getattr(exc, "response", None), "status_code", None)
    return code in (429, 503, "429", "503") or any(
        marker in f"{type(exc).__name__}: {exc}".upper()
        for marker in ("429", "503", "UNAVAILABLE", "RESOURCE_EXHAUSTED")
    )
