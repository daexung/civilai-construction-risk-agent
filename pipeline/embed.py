"""3단계: data/processed/chunks.jsonl → 벡터

백엔드의 질의 임베딩과 반드시 같은 모델을 써야 한다.

실행: python pipeline/embed.py
"""


def load_chunks(path: str) -> list[dict]:
    """chunks.jsonl을 읽어 청크 목록으로 반환."""
    raise NotImplementedError


def embed_texts(texts: list[str]) -> list[list[float]]:
    """텍스트 목록을 벡터 목록으로 변환."""
    raise NotImplementedError


def main() -> None:
    """CLI 진입점."""
    raise NotImplementedError


if __name__ == "__main__":
    main()
