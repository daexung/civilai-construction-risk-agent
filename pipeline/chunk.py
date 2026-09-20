"""2단계: data/processed/parsed.jsonl → 청크 → data/processed/chunks.jsonl

청킹 전략을 바꿔가며 비교할 수 있도록 파싱 결과를 파일에서 읽어 시작한다.

실행: python pipeline/chunk.py
"""


def load_records(path: str) -> list[dict]:
    """parsed.jsonl을 읽어 레코드 목록으로 반환."""
    raise NotImplementedError


def build_chunks(records: list[dict]) -> list[dict]:
    """레코드를 청크로 묶는다.

    청크에는 검색 대상 본문과 함께 출처(절 번호, 페이지)가 남아야 한다.
    """
    raise NotImplementedError


def main() -> None:
    """CLI 진입점. 청킹 결과를 data/processed/chunks.jsonl로 저장한다."""
    raise NotImplementedError


if __name__ == "__main__":
    main()
