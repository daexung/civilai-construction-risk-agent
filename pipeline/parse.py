"""1단계: PDF → 구조화된 레코드 → data/processed/parsed.jsonl

실행: python pipeline/parse.py --start 185 --end 185
"""
import pymupdf

Table = list[list[str | None]]


def read_page_text(doc: pymupdf.Document, page_no: int) -> str:
    """page_no(1부터)의 텍스트를 반환."""
    raise NotImplementedError


def read_tables(doc: pymupdf.Document, page_no: int) -> list[Table]:
    """page_no(1부터)의 표를 행/열 격자로 반환."""
    raise NotImplementedError


def find_section_titles(doc: pymupdf.Document, page_no: int) -> list[tuple[float, str]]:
    """페이지 안의 절 제목을 (세로 위치, 제목) 목록으로 반환.

    표가 어느 절에 속하는지 판단하는 데 쓴다. 예: (327.0, "6-1-1 레디믹스트콘크리트 타설")
    """
    raise NotImplementedError


def clean_table(table: Table) -> Table:
    """표를 정리한다.

    - 글자 사이 공백 제거 ("인 력 운 반" -> "인력운반")
    - 병합 셀 때문에 비어 있는 라벨 칸을 채움 (숫자 칸은 채우지 않는다)
    """
    raise NotImplementedError


def table_to_records(table: Table, section_title: str) -> list[dict]:
    """정리된 표를 레코드 목록으로 변환한다.

    레코드 하나가 표의 한 행(구분 + 직종)에 대응하며, 그 자체로 의미가 완결돼야 한다.
    셀에 '\\n'으로 쌓인 값들은 행으로 풀어서 짝을 맞춘다.
    """
    raise NotImplementedError


def parse_pages(pdf_path: str, start_page: int, end_page: int) -> list[dict]:
    """페이지 범위를 파싱해 레코드 목록을 반환한다."""
    raise NotImplementedError


def main() -> None:
    """CLI 진입점. 파싱 결과를 data/processed/parsed.jsonl로 저장한다."""
    raise NotImplementedError


if __name__ == "__main__":
    main()
