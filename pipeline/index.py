"""4단계: 청크와 벡터를 벡터 DB에 적재

실행: python pipeline/index.py
"""


def init_store() -> None:
    """저장소(테이블·컬렉션)를 준비한다."""
    raise NotImplementedError


def upsert(chunks: list[dict], vectors: list[list[float]]) -> int:
    """청크와 벡터를 적재하고 건수를 반환."""
    raise NotImplementedError


def main() -> None:
    """CLI 진입점."""
    raise NotImplementedError


if __name__ == "__main__":
    main()
