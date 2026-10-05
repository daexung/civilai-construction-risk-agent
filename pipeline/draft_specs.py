"""강한 모델(Gemini, Vertex)로 절별 계산 명세 초안을 일괄 생성한다.

이어하기 가능: data/drafts/specs/<division>/<section_no>.json이 이미 있으면 건너뛴다(--force로 덮어씀).
실행 예:
  python -m pipeline.draft_specs --only 공통/6-1-4,공통/6-1-1,공통/6-1-2,공통/6-1-3
  python -m pipeline.draft_specs --prefix 공통/6- --chunks data/processed/chunks.all.jsonl
  python -m pipeline.draft_specs --dry-run --prefix 공통/6-
"""

from __future__ import annotations

import argparse
import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from pipeline.validate_drafts import check_citations, chunks_by_id_from_list, file_sha256

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV = ROOT / ".env"
DEFAULT_CHUNKS = ROOT / "data/processed/chunks.all.jsonl"
DEFAULT_PAGE_MAP = ROOT / "data/processed/page_map.json"
DEFAULT_PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
DEFAULT_SPEC_FORMAT = ROOT / "docs/SPEC_FORMAT.md"
DEFAULT_EXAMPLE_SPEC = ROOT / "backend/agent/rules/specs/common/6-1-4_pump.json"
DEFAULT_OUT_DIR = ROOT / "data/drafts"
DEFAULT_CONFIG = Path(__file__).with_name("draft_specs_config.json")

EXAMPLE_TARGET = ("공통", "6-1-4")  # 정답이 있는 절: 채점용으로 예시를 빼고 형식 문서만 준다.

CALC_TYPES = {"daily_crew", "per_unit", "rate", "lookup_only", "not_calculable"}
CALC_TYPE_ALIASES = {"adjusted_daily_crew": "daily_crew"}  # 모델이 계산 함수 이름을 그대로 답하는 경우 정규화
REQUIRED_DRAFT_FIELDS = {"id", "edition", "division", "section_no", "title", "work", "review",
                          "source_pages", "inputs", "tables", "quantity_model"}
RETRY_DELAYS = (1, 2, 4, 8, 16)  # 초, 429/503 지수 대기 5회


class BudgetExceeded(Exception):
    """--max-usd 상한 도달. 새 호출을 시작하지 않고 멈춘다."""


# ---------------------------------------------------------------------------
# .env / 설정
# ---------------------------------------------------------------------------

def env_value(name: str, env_path: Path) -> str | None:
    """지정한 키 이름만 읽는다. 파일 내용을 로그로 남기거나 출력하지 않는다."""
    import os

    value = os.environ.get(name)
    if value:
        return value
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            key, sep, candidate = line.partition("=")
            if sep and key.strip() == name:
                return candidate.strip().strip('"').strip("'") or None
    return None


def load_pricing_config(path: Path) -> dict:
    config = json.loads(path.read_text(encoding="utf-8"))
    if not config.get("input_usd_per_million") or not config.get("output_usd_per_million"):
        raise SystemExit(
            f"{path}의 input_usd_per_million/output_usd_per_million이 비어 있습니다. "
            "검토자가 실제 단가를 채운 뒤 실행하세요."
        )
    return config


# ---------------------------------------------------------------------------
# 조각·쪽 대응 로딩
# ---------------------------------------------------------------------------

def load_chunks(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_page_map(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))["pages"]


def division_from_page_map(page_map: dict, pdf_page: int) -> str | None:
    record = page_map.get(str(pdf_page))
    if not record or not record.get("division"):
        return None
    return record["division"].removesuffix("부문")


def fill_divisions(chunks: list[dict], page_map: dict) -> list[dict]:
    for chunk in chunks:
        if chunk.get("division"):
            continue
        page = chunk.get("source", {}).get("page") or (chunk.get("pages") or [None])[0]
        if page is not None:
            chunk["division"] = division_from_page_map(page_map, page)
    return chunks


# ---------------------------------------------------------------------------
# 대상 절 목록
# ---------------------------------------------------------------------------

def group_sections(chunks: list[dict]) -> dict[tuple[str, str], list[dict]]:
    """(division, section_no)별로 묶되, kind=='table' 조각이 1개 이상인 절만 남긴다."""
    groups: dict[tuple[str, str], list[dict]] = {}
    for chunk in chunks:
        division = chunk.get("division")
        section_no = chunk.get("section_no")
        if not division or not section_no:
            continue
        groups.setdefault((division, section_no), []).append(chunk)
    return {key: value for key, value in groups.items() if any(c["kind"] == "table" for c in value)}


def _parse_only(only: str) -> set[tuple[str, str]]:
    result = set()
    for item in only.split(","):
        item = item.strip()
        if not item:
            continue
        division, sep, section_no = item.partition("/")
        if not sep:
            raise SystemExit(f"--only 형식 오류(부문/절 아님): {item}")
        result.add((division.strip(), section_no.strip()))
    return result


def filter_targets(sections: dict[tuple[str, str], list[dict]], *, only: str | None,
                    prefix: str | None, limit: int | None) -> list[tuple[str, str]]:
    keys = sorted(sections.keys())
    if only:
        wanted = _parse_only(only)
        keys = [key for key in keys if key in wanted]
    if prefix:
        division, sep, section_prefix = prefix.partition("/")
        if not sep:
            raise SystemExit(f"--prefix 형식 오류(부문/접두 아님): {prefix}")
        keys = [key for key in keys if key[0] == division.strip() and key[1].startswith(section_prefix.strip())]
    if limit is not None:
        keys = keys[:limit]
    return keys


# ---------------------------------------------------------------------------
# 모델 요청 구성
# ---------------------------------------------------------------------------

def section_pages(chunks_for_section: list[dict]) -> list[int]:
    pages = sorted({chunk["source"]["page"] for chunk in chunks_for_section})
    if pages:
        pages.append(pages[-1] + 1)  # 절이 이어지는 다음 쪽 1쪽까지
    return sorted(set(pages))


def build_pdf_excerpt(pdf_path: Path, pages: list[int]) -> bytes:
    import pymupdf

    with pymupdf.open(pdf_path) as document:
        valid_pages = [page for page in pages if 1 <= page <= document.page_count]
        excerpt = pymupdf.open()
        for page in valid_pages:
            excerpt.insert_pdf(document, from_page=page - 1, to_page=page - 1)
        return excerpt.tobytes()


def build_parsed_payload(chunks_for_section: list[dict]) -> list[dict]:
    payload = []
    for chunk in sorted(chunks_for_section, key=lambda c: c["chunk_id"]):
        if chunk["kind"] == "table":
            payload.append({"kind": "table", "table_id": chunk["source"]["table_id"], "text": chunk["text"]})
        else:
            payload.append({"kind": "text", "chunk_id": chunk["chunk_id"], "text": chunk["text"]})
    return payload


INSTRUCTIONS_TEMPLATE = """\
당신은 2026년 건설공사표준품셈을 읽고 계산 가능한 명세 초안을 쓰는 전문가입니다.
대상 절: {division}/{section_no}

첨부한 PDF 원문 쪽과 아래 "우리 파싱 결과"(같은 절의 조각들)를 함께 보고, 아래 "명세 형식"을 그대로 따라
JSON 하나만 출력하세요. 형식 밖 필드를 만들지 말고, 형식에 없는 값을 지어내지 마세요.

[출력 JSON 최상위 구조]
{{
  "draft": {{ ... 명세 형식의 최상위 필드 전부 (review는 항상 "AI 초안 · 검토 전") ... }},
  "calc_type": "daily_crew" | "per_unit" | "rate" | "lookup_only" | "not_calculable" 중 하나,
  "calc_type_reason": "이 분류를 고른 이유(한국어 한두 문장)",
  "citations": [
    {{"table_id": "...", "row": "...", "column": "...", "value": "..."}},
    {{"chunk_id": "...", "quote": "..."}}
    // draft 안에서 쓴 숫자 하나하나에 대해, 표 인용 또는 줄글 인용 하나씩. 두 형식 외에는 쓰지 않는다.
  ],
  "open_questions": ["원문이 애매해 추측하지 않고 남겨둔 지점"],
  "questions": ["이 절을 찾을 현장 질문 3개: 쉬운 것 1개, 애매한 것 1개, 입력이 빠진 것 1개"]
}}

[calc_type — 다음 다섯 값만 허용]
- "daily_crew": 일당 작업조형(기준 일일시공량 × 계수 → 작업일수 → 직종별 인·일). 계산 함수 이름(예: adjusted_daily_crew)이
  아니라 반드시 이 값 "daily_crew"를 쓴다.
- "per_unit": 단위당 품이 표에 직접 있는 경우
- "rate": 물량에 비율(%)만 곱하는 계산이 본 작업인 경우
- "lookup_only": 조건에 따라 표 값 하나를 찾아 보여주기만 하면 되는 경우
- "not_calculable": 자동 계산할 만큼 원문이 명확하지 않거나 판단이 크게 필요한 경우
이 다섯 값 외의 문자열(함수 이름, 새로 만든 분류 등)을 쓰지 않는다.

[규칙]
- draft.id는 "2026-정오표1차/{division}/{section_no}/<작업이름>" 형식.
- 표(tables[].id)는 "우리 파싱 결과"에 있는 table_id만 쓴다. 지어내지 않는다.
- 숫자·표 값·인원·규칙 하나하나에 citations로 출처를 남긴다. 출처를 못 찾으면 open_questions에 적고 draft에는 넣지 않는다.
- 계산 함수가 없는 calc_type(rate/lookup_only/not_calculable)이면 draft.quantity_model.params는 {{}}로 두고
  draft.quantity_model.steps에 사람이 볼 근거만 짧게 남긴다.
- 원문이 애매하면 추측하지 말고 open_questions에 적는다.
- **표의 비고·[주] 칸에 있는 인원 증감·조건**(예: "○○ 타설: 특별인부 1인 추가")은 절대 빠뜨리지 말고 반드시
  crew_rules/blocked/cost_rules 중 하나로 옮기고, 그 조건 판단에 필요한 입력을 draft.inputs에 추가한다.
- **원문이 두 가지 이상으로 읽히면 계산식에 넣지 말고**, draft.blocked에 조건·이유·출처를 적고 open_questions에도
  같은 내용을 적는다(예: 재셋팅·감산이 여러 번 겹칠 때 누적 방식이 원문에 명시되지 않은 경우). 짐작으로 계산 규칙을
  만들지 않는다.
- citations는 두 형식만 쓴다. 표: {{"table_id","row","column","value"}} — row/column은 "우리 파싱 결과" 조각
  텍스트에 있는 글자를 **그대로 복사**한다(새 이름을 합쳐 만들지 않는다. 예: "기계비빔타설_콘크리트공"처럼 원문에 없는
  행 이름을 만들지 않는다). 줄글: {{"chunk_id","quote"}} — quote는 조각 텍스트의 **연속된 부분 문자열을 그대로**
  복사한다(의역·요약·띄어쓰기 변경 금지). {{"section_no","marker"}}처럼 이 두 형식 밖의 인용을 쓰지 않는다.
- "우리 파싱 결과"에 없는 chunk_id/table_id를 만들지 않는다.

[명세 형식]
{spec_format}
{example_block}
[우리 파싱 결과: {division}/{section_no}]
{parsed_json}
"""

EXAMPLE_BLOCK_TEMPLATE = """
[완성 예시: 2026-정오표1차/공통/6-1-4/펌프차타설]
{example_json}
"""

PARSE_RETRY_SUFFIX = """

[재요청 — 이전 응답이 JSON으로 파싱되지 않았습니다]
오류: {error}
반드시 위 [출력 JSON 최상위 구조]와 정확히 같은 하나의 JSON 객체만 출력하세요. 설명 문장이나 코드블록 표시(```) 없이
JSON 본문만 출력하세요.
"""

CITATION_RETRY_SUFFIX = """

[재요청 — 이전 응답의 인용이 조각 텍스트와 일치하지 않습니다]
아래 불일치를 고쳐 같은 절의 명세를 다시 작성하세요. row/column/value/quote는 "우리 파싱 결과"에 있는 글자를
그대로 복사해야 합니다. 원문에서 확인할 수 없으면 그 숫자를 draft에서 빼고 open_questions에 적으세요.

불일치 목록:
{issues}
"""


def build_instructions(division: str, section_no: str, parsed: list[dict], spec_format_text: str,
                        example_spec_text: str | None) -> str:
    example_block = "" if example_spec_text is None else EXAMPLE_BLOCK_TEMPLATE.format(example_json=example_spec_text)
    return INSTRUCTIONS_TEMPLATE.format(
        division=division, section_no=section_no, spec_format=spec_format_text,
        example_block=example_block, parsed_json=json.dumps(parsed, ensure_ascii=False, indent=2),
    )


# ---------------------------------------------------------------------------
# 모델 호출 (request_fn 주입 가능 — 오프라인 검사용)
# ---------------------------------------------------------------------------

RequestFn = Callable[[str, bytes, str, int], tuple[str, int, int]]
"""(model, pdf_bytes, instructions_text, max_output_tokens) -> (response_text, input_tokens, output_tokens)"""


def make_vertex_request_fn(api_key: str) -> RequestFn:
    from google import genai
    from google.genai import types

    client = genai.Client(vertexai=True, api_key=api_key)

    def request_fn(model: str, pdf_bytes: bytes, instructions_text: str, max_output_tokens: int) -> tuple[str, int, int]:
        parts = [types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
                 types.Part(text=instructions_text)]
        config = types.GenerateContentConfig(
            temperature=0, response_mime_type="application/json", max_output_tokens=max_output_tokens,
        )
        response = client.models.generate_content(model=model, contents=parts, config=config)
        usage = response.usage_metadata
        input_tokens = getattr(usage, "prompt_token_count", 0) or 0
        output_tokens = getattr(usage, "candidates_token_count", 0) or 0
        return (response.text or ""), input_tokens, output_tokens

    return request_fn


def call_with_retry(request_fn: RequestFn, model: str, pdf_bytes: bytes, instructions_text: str,
                     max_output_tokens: int, *, sleep_fn: Callable[[float], None] = time.sleep) -> tuple[str, int, int]:
    last_error: Exception | None = None
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            return request_fn(model, pdf_bytes, instructions_text, max_output_tokens)
        except Exception as exc:  # noqa: BLE001 — 429/503만 재시도, 나머지는 즉시 올림
            status = getattr(exc, "code", None)
            if callable(status):
                try:
                    status = status()
                except Exception:
                    status = None
            message = f"{type(exc).__name__}: {exc}".upper()
            transient = status in (429, 503, "429", "503") or any(t in message for t in ("429", "503", "UNAVAILABLE", "RESOURCE_EXHAUSTED"))
            last_error = exc
            if not transient or attempt == len(RETRY_DELAYS):
                raise
            sleep_fn(RETRY_DELAYS[attempt])
    raise last_error  # pragma: no cover — 위 루프에서 항상 반환하거나 올림


# ---------------------------------------------------------------------------
# 저장
# ---------------------------------------------------------------------------

def draft_path(out_dir: Path, division: str, section_no: str) -> Path:
    return out_dir / "specs" / division / f"{section_no}.json"


def raw_path(out_dir: Path, division: str, section_no: str) -> Path:
    return out_dir / "raw" / division / f"{section_no}.json"


def parse_response(response_text: str) -> dict:
    parsed = json.loads(response_text)
    if not isinstance(parsed, dict):
        raise ValueError("응답이 JSON 객체가 아님")
    missing_top = {"draft", "calc_type"} - parsed.keys()
    if missing_top:
        raise ValueError(f"최상위 필드 누락: {sorted(missing_top)}")
    raw_calc_type = parsed["calc_type"]
    normalized_calc_type = CALC_TYPE_ALIASES.get(raw_calc_type, raw_calc_type)
    if normalized_calc_type not in CALC_TYPES:
        raise ValueError(f"알 수 없는 calc_type: {raw_calc_type}")
    parsed["calc_type"] = normalized_calc_type
    parsed["calc_type_raw"] = raw_calc_type
    missing_draft = REQUIRED_DRAFT_FIELDS - parsed["draft"].keys()
    if missing_draft:
        raise ValueError(f"draft 필드 누락: {sorted(missing_draft)}")
    return parsed


def save_draft(out_dir: Path, division: str, section_no: str, parsed: dict, *, model: str,
               input_tokens: int, output_tokens: int, source_pages: list[int], prompt_sha256: str,
               chunks_path: str, chunks_sha256: str | None, citation_retry_used: bool = False,
               citation_issues_after_retry: list[str] | None = None) -> Path:
    record = {
        "draft": parsed["draft"],
        "calc_type": parsed["calc_type"],
        "calc_type_raw": parsed.get("calc_type_raw", parsed["calc_type"]),
        "calc_type_reason": parsed.get("calc_type_reason", ""),
        "citations": parsed.get("citations", []),
        "open_questions": parsed.get("open_questions", []),
        "questions": parsed.get("questions", []),
        "meta": {
            "model": model, "created_at": datetime.now(timezone.utc).isoformat(),
            "input_tokens": input_tokens, "output_tokens": output_tokens,
            "source_pages": source_pages, "prompt_sha256": prompt_sha256,
            "chunks_path": chunks_path, "chunks_sha256": chunks_sha256,
            "citation_retry_used": citation_retry_used,
            "citation_issues_after_retry": citation_issues_after_retry or [],
        },
    }
    path = draft_path(out_dir, division, section_no)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def save_raw(out_dir: Path, division: str, section_no: str, response_text: str, *, suffix: str = "") -> Path:
    path = raw_path(out_dir, division, section_no)
    if suffix:
        path = path.with_name(f"{path.stem}{suffix}{path.suffix}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(response_text, encoding="utf-8")
    return path


def append_failure(out_dir: Path, division: str, section_no: str, error: str, attempts: int) -> None:
    path = out_dir / "failures.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"division": division, "section_no": section_no, "error": error[:500],
              "attempts": attempts, "at": datetime.now(timezone.utc).isoformat()}
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# 절 하나 처리
# ---------------------------------------------------------------------------

class CostTracker:
    def __init__(self, max_usd: float, input_price: float, output_price: float):
        self.max_usd = max_usd
        self.input_price = input_price
        self.output_price = output_price
        self._lock = threading.Lock()
        self.total_usd = 0.0
        self.exceeded = False

    def check(self) -> None:
        with self._lock:
            if self.exceeded:
                raise BudgetExceeded(f"누적 비용 ${self.total_usd:.2f}이 상한 ${self.max_usd:.2f}을 넘음")

    def add(self, input_tokens: int, output_tokens: int) -> None:
        with self._lock:
            self.total_usd += (input_tokens / 1_000_000) * self.input_price
            self.total_usd += (output_tokens / 1_000_000) * self.output_price
            if self.total_usd >= self.max_usd:
                self.exceeded = True


def process_section(division: str, section_no: str, chunks_for_section: list[dict], *, pdf_path: Path,
                     spec_format_text: str, example_spec_text: str | None, out_dir: Path, model: str,
                     max_output_tokens: int, request_fn: RequestFn, cost_tracker: CostTracker,
                     force: bool, chunks_path: str = "", chunks_sha256: str | None = None) -> str:
    """돌려주는 상태: "skipped" | "saved" | "failed"."""
    path = draft_path(out_dir, division, section_no)
    if path.exists() and not force:
        return "skipped"

    cost_tracker.check()

    example = None if (division, section_no) == EXAMPLE_TARGET else example_spec_text
    parsed_payload = build_parsed_payload(chunks_for_section)
    base_instructions = build_instructions(division, section_no, parsed_payload, spec_format_text, example)
    prompt_sha256 = hashlib.sha256(base_instructions.encode("utf-8")).hexdigest()
    pages = section_pages(chunks_for_section)
    pdf_bytes = build_pdf_excerpt(pdf_path, pages)
    section_chunks_by_id = chunks_by_id_from_list(chunks_for_section)

    def call(instructions: str) -> tuple[str, int, int]:
        response_text, input_tokens, output_tokens = call_with_retry(
            request_fn, model, pdf_bytes, instructions, max_output_tokens,
        )
        cost_tracker.add(input_tokens, output_tokens)
        return response_text, input_tokens, output_tokens

    # 1. 요청, 실패하면 JSON 파싱·calc_type 실패는 1회 재요청.
    total_input_tokens = total_output_tokens = 0
    parsed = None
    for parse_attempt in range(2):
        instructions = base_instructions if parse_attempt == 0 else (
            base_instructions + PARSE_RETRY_SUFFIX.format(error=str(last_parse_error)))
        try:
            response_text, input_tokens, output_tokens = call(instructions)
        except Exception as exc:  # noqa: BLE001
            append_failure(out_dir, division, section_no, f"{type(exc).__name__}: {exc}", len(RETRY_DELAYS) + 1)
            return "failed"
        total_input_tokens += input_tokens
        total_output_tokens += output_tokens
        save_raw(out_dir, division, section_no, response_text, suffix=f".parse{parse_attempt + 1}" if parse_attempt else "")
        try:
            parsed = parse_response(response_text)
            break
        except Exception as exc:  # noqa: BLE001
            last_parse_error = exc
            if parse_attempt == 1:
                append_failure(out_dir, division, section_no, f"응답 파싱 실패(재요청 후): {exc}", 2)
                return "failed"

    # 2. 인용 자체 점검, 불일치가 있으면 불일치 목록을 붙여 같은 절을 한 번만 다시 요청.
    citation_issues = check_citations(section_chunks_by_id, parsed.get("citations", []))
    citation_retry_used = False
    if citation_issues:
        citation_retry_used = True
        retry_instructions = base_instructions + CITATION_RETRY_SUFFIX.format(
            issues="\n".join(f"- {issue}" for issue in citation_issues))
        try:
            response_text, input_tokens, output_tokens = call(retry_instructions)
            total_input_tokens += input_tokens
            total_output_tokens += output_tokens
            save_raw(out_dir, division, section_no, response_text, suffix=".citation_retry")
            retried = parse_response(response_text)
            parsed = retried
            citation_issues = check_citations(section_chunks_by_id, parsed.get("citations", []))
        except Exception as exc:  # noqa: BLE001
            # 재요청 자체가 실패하면 첫 응답을 그대로 저장하고 불일치를 report용으로 남긴다.
            append_failure(out_dir, division, section_no, f"인용 재요청 실패, 첫 응답 유지: {exc}", 1)

    save_draft(out_dir, division, section_no, parsed, model=model, input_tokens=total_input_tokens,
               output_tokens=total_output_tokens, source_pages=pages, prompt_sha256=prompt_sha256,
               chunks_path=chunks_path, chunks_sha256=chunks_sha256, citation_retry_used=citation_retry_used,
               citation_issues_after_retry=citation_issues)
    return "saved"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--chunks", default=str(DEFAULT_CHUNKS))
    parser.add_argument("--page-map", default=str(DEFAULT_PAGE_MAP))
    parser.add_argument("--pdf", default=str(DEFAULT_PDF))
    parser.add_argument("--env", default=str(DEFAULT_ENV))
    parser.add_argument("--spec-format", default=str(DEFAULT_SPEC_FORMAT))
    parser.add_argument("--example-spec", default=str(DEFAULT_EXAMPLE_SPEC))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--only", help="예: 공통/6-1-4,공통/6-1-1")
    parser.add_argument("--prefix", help="예: 공통/6-")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--max-usd", type=float, default=50.0)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="대상 절만 세고 모델을 호출하지 않는다")
    return parser


def resolve_targets(args) -> tuple[dict[tuple[str, str], list[dict]], list[tuple[str, str]]]:
    chunks = load_chunks(Path(args.chunks))
    page_map = load_page_map(Path(args.page_map))
    chunks = fill_divisions(chunks, page_map)
    sections = group_sections(chunks)
    targets = filter_targets(sections, only=args.only, prefix=args.prefix, limit=args.limit)
    return sections, targets


def main() -> int:
    args = build_arg_parser().parse_args()
    sections, targets = resolve_targets(args)

    by_division: dict[str, int] = {}
    for division, _ in targets:
        by_division[division] = by_division.get(division, 0) + 1
    print(f"대상 절 {len(targets)}개")
    for division, count in sorted(by_division.items()):
        print(f"  {division}: {count}개")

    if args.dry_run:
        for division, section_no in targets:
            print(f"  - {division}/{section_no}")
        return 0

    if not targets:
        return 0

    config = load_pricing_config(Path(args.config))
    model = config["model"]
    max_output_tokens = config.get("max_output_tokens", 8192)
    api_key = env_value("VERTEX_API_KEY_BULK", Path(args.env))
    if not api_key:
        raise SystemExit("VERTEX_API_KEY_BULK가 없습니다(.env 또는 환경 변수)")

    spec_format_text = Path(args.spec_format).read_text(encoding="utf-8")
    example_spec_text = Path(args.example_spec).read_text(encoding="utf-8")
    out_dir = Path(args.out_dir)
    pdf_path = Path(args.pdf)
    chunks_path = Path(args.chunks)
    chunks_sha256 = file_sha256(chunks_path)

    request_fn = make_vertex_request_fn(api_key)
    cost_tracker = CostTracker(args.max_usd, config["input_usd_per_million"], config["output_usd_per_million"])

    counts = {"saved": 0, "skipped": 0, "failed": 0}
    counts_lock = threading.Lock()

    def run_one(target: tuple[str, str]) -> None:
        division, section_no = target
        try:
            status = process_section(
                division, section_no, sections[target], pdf_path=pdf_path,
                spec_format_text=spec_format_text, example_spec_text=example_spec_text,
                out_dir=out_dir, model=model, max_output_tokens=max_output_tokens,
                request_fn=request_fn, cost_tracker=cost_tracker, force=args.force,
                chunks_path=str(chunks_path), chunks_sha256=chunks_sha256,
            )
        except BudgetExceeded as exc:
            append_failure(out_dir, division, section_no, str(exc), 0)
            status = "failed"
        with counts_lock:
            counts[status] += 1
        print(f"{status.upper()} {division}/{section_no}")

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run_one, target) for target in targets]
        for future in as_completed(futures):
            future.result()

    print(f"저장 {counts['saved']}, 건너뜀 {counts['skipped']}, 실패 {counts['failed']}")
    print(f"누적 비용 ${cost_tracker.total_usd:.2f} / 상한 ${cost_tracker.max_usd:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
