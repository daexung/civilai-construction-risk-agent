"""draft_specs.py / validate_drafts.py를 네트워크 없이 검사한다.

가짜 모델 응답 2개(정상 1, 인용 숫자가 틀린 것 1)로 저장·이어하기(스킵)·비용 상한·대상 목록 필터·
출처 대조 검증을 확인한다. run_quick.py에는 넣지 않고 단독 실행한다.
실행: python evals/check_drafts.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline import draft_specs as ds  # noqa: E402
from pipeline import validate_drafts as vd  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((name, condition, detail))
    print(f"{'PASS' if condition else 'FAIL'} {name}{': ' + detail if detail and not condition else ''}")


# ---------------------------------------------------------------------------
# 고정 자료
# ---------------------------------------------------------------------------

CHUNK_TABLE = {
    "chunk_id": "p1-t0", "kind": "table", "division": "테스트", "section_no": "9-9-9",
    "source": {"page": 1, "table_id": "p1-t0"},
    "text": "콘크리트공 | 단위 인 | 수량 3",
}
CHUNK_TEXT = {
    "chunk_id": "p1-x0", "kind": "text", "division": "테스트", "section_no": "9-9-9",
    "source": {"page": 1, "table_id": None},
    "text": "이것은 테스트 본문입니다.",
}
SECTION_CHUNKS = [CHUNK_TABLE, CHUNK_TEXT]

GOOD_DRAFT = {
    "id": "2026-정오표1차/테스트/9-9-9/테스트작업", "edition": "2026-정오표1차", "division": "테스트",
    "section_no": "9-9-9", "title": "테스트", "work": "테스트", "review": "AI 초안 · 검토 전",
    "source_pages": [1], "inputs": [], "tables": [],
    "quantity_model": {"name": "not_calculable", "params": {}, "steps": [], "source": "", "rounding": ""},
}

GOOD_RESPONSE = json.dumps({
    "draft": GOOD_DRAFT, "calc_type": "not_calculable", "calc_type_reason": "테스트",
    "citations": [{"table_id": "p1-t0", "row": "콘크리트공", "column": "단위", "value": "3"}],
    "open_questions": [], "questions": ["쉬운 질문", "애매한 질문", "빠진 입력 질문"],
}, ensure_ascii=False)

BAD_CITATION_DRAFT = {**GOOD_DRAFT, "id": "2026-정오표1차/테스트/8-8-8/틀린인용", "section_no": "8-8-8"}
BAD_CITATION_RESPONSE = json.dumps({
    "draft": BAD_CITATION_DRAFT, "calc_type": "not_calculable", "calc_type_reason": "테스트",
    "citations": [{"table_id": "p1-t0", "row": "콘크리트공", "column": "단위", "value": "999"}],
    "open_questions": [], "questions": ["쉬운 질문", "애매한 질문", "빠진 입력 질문"],
}, ensure_ascii=False)


def make_request_fn(response_text: str, calls: list):
    def request_fn(model: str, pdf_bytes: bytes, instructions: str, max_output_tokens: int):
        calls.append((model, len(pdf_bytes), len(instructions), max_output_tokens))
        return response_text, 10, 20
    return request_fn


def cost_tracker(max_usd: float = 1000.0) -> ds.CostTracker:
    return ds.CostTracker(max_usd=max_usd, input_price=0.0, output_price=0.0)


# ---------------------------------------------------------------------------
# 저장 · 이어하기(스킵) · --force
# ---------------------------------------------------------------------------

def check_save_resume_force(tmp: Path) -> None:
    out_dir = tmp / "drafts"
    calls: list = []
    request_fn = make_request_fn(GOOD_RESPONSE, calls)

    status1 = ds.process_section(
        "테스트", "9-9-9", SECTION_CHUNKS, pdf_path=ds.DEFAULT_PDF, spec_format_text="형식 문서",
        example_spec_text=None, out_dir=out_dir, model="fake-model", max_output_tokens=100,
        request_fn=request_fn, cost_tracker=cost_tracker(), force=False,
    )
    check("첫 실행은 저장됨", status1 == "saved", status1)
    check("모델을 1회 호출함", len(calls) == 1, str(len(calls)))

    path = ds.draft_path(out_dir, "테스트", "9-9-9")
    check("초안 파일 생성됨", path.exists())
    saved = json.loads(path.read_text(encoding="utf-8"))
    check("draft.id 저장됨", saved["draft"]["id"] == GOOD_DRAFT["id"])
    check("meta.model 저장됨", saved["meta"]["model"] == "fake-model")
    check("meta.input_tokens 저장됨", saved["meta"]["input_tokens"] == 10)

    status2 = ds.process_section(
        "테스트", "9-9-9", SECTION_CHUNKS, pdf_path=ds.DEFAULT_PDF, spec_format_text="형식 문서",
        example_spec_text=None, out_dir=out_dir, model="fake-model", max_output_tokens=100,
        request_fn=request_fn, cost_tracker=cost_tracker(), force=False,
    )
    check("재실행은 건너뜀(이어하기)", status2 == "skipped", status2)
    check("건너뛸 때 모델을 다시 호출하지 않음", len(calls) == 1, str(len(calls)))

    status3 = ds.process_section(
        "테스트", "9-9-9", SECTION_CHUNKS, pdf_path=ds.DEFAULT_PDF, spec_format_text="형식 문서",
        example_spec_text=None, out_dir=out_dir, model="fake-model", max_output_tokens=100,
        request_fn=request_fn, cost_tracker=cost_tracker(), force=True,
    )
    check("--force는 다시 저장함", status3 == "saved", status3)
    check("--force는 모델을 다시 호출함", len(calls) == 2, str(len(calls)))


# ---------------------------------------------------------------------------
# 대상 목록 필터
# ---------------------------------------------------------------------------

def check_filter_targets() -> None:
    sections = {
        ("공통", "6-1-4"): SECTION_CHUNKS, ("공통", "6-1-1"): SECTION_CHUNKS,
        ("전기", "3-2-1"): SECTION_CHUNKS,
    }
    only = ds.filter_targets(sections, only="공통/6-1-4,전기/3-2-1", prefix=None, limit=None)
    check("--only는 지정한 절만 남김", set(only) == {("공통", "6-1-4"), ("전기", "3-2-1")}, str(only))

    prefix = ds.filter_targets(sections, only=None, prefix="공통/6-", limit=None)
    check("--prefix는 부문+접두만 남김", set(prefix) == {("공통", "6-1-4"), ("공통", "6-1-1")}, str(prefix))

    limited = ds.filter_targets(sections, only=None, prefix=None, limit=1)
    check("--limit은 개수를 제한함", len(limited) == 1, str(limited))


def check_group_sections_requires_table() -> None:
    text_only_chunk = {**CHUNK_TEXT, "division": "공통", "section_no": "0-0-0"}
    groups = ds.group_sections([text_only_chunk])
    check("표 조각이 없는 절은 대상에서 빠짐", ("공통", "0-0-0") not in groups, str(list(groups)))

    with_table = ds.group_sections([text_only_chunk, {**CHUNK_TABLE, "division": "공통", "section_no": "0-0-0"}])
    check("표 조각이 있으면 대상에 포함됨", ("공통", "0-0-0") in with_table, str(list(with_table)))


# ---------------------------------------------------------------------------
# 비용 상한
# ---------------------------------------------------------------------------

def check_budget_cap() -> None:
    tracker = ds.CostTracker(max_usd=0.01, input_price=1_000_000.0, output_price=0.0)
    tracker.check()  # 아직 0원 — 통과해야 함
    tracker.add(input_tokens=1, output_tokens=0)  # 1/1,000,000 * 1,000,000 = $1.00 >= $0.01
    check("상한 도달 시 exceeded=True", tracker.exceeded)
    raised = False
    try:
        tracker.check()
    except ds.BudgetExceeded:
        raised = True
    check("상한 도달 후 check()는 BudgetExceeded를 올림", raised)


def check_budget_stops_processing(tmp: Path) -> None:
    out_dir = tmp / "drafts_budget"
    calls: list = []
    request_fn = make_request_fn(GOOD_RESPONSE, calls)
    tracker = ds.CostTracker(max_usd=0.0, input_price=0.0, output_price=0.0)
    tracker.exceeded = True  # 이미 상한 도달한 상태를 흉내

    raised = False
    try:
        ds.process_section(
            "테스트", "9-9-9", SECTION_CHUNKS, pdf_path=ds.DEFAULT_PDF, spec_format_text="형식 문서",
            example_spec_text=None, out_dir=out_dir, model="fake-model", max_output_tokens=100,
            request_fn=request_fn, cost_tracker=tracker, force=False,
        )
    except ds.BudgetExceeded:
        raised = True
    check("비용 상한 도달 시 process_section이 멈춤", raised)
    check("비용 상한 도달 시 모델을 호출하지 않음", len(calls) == 0, str(len(calls)))


# ---------------------------------------------------------------------------
# 출처 대조 검증 (정상 1 + 인용 숫자 틀린 것 1)
# ---------------------------------------------------------------------------

def check_validation(tmp: Path) -> None:
    out_dir = tmp / "drafts_validate"
    good_calls: list = []
    ds.process_section(
        "테스트", "9-9-9", SECTION_CHUNKS, pdf_path=ds.DEFAULT_PDF, spec_format_text="형식 문서",
        example_spec_text=None, out_dir=out_dir, model="fake-model", max_output_tokens=100,
        request_fn=make_request_fn(GOOD_RESPONSE, good_calls), cost_tracker=cost_tracker(), force=False,
    )
    bad_calls: list = []
    ds.process_section(
        "테스트", "8-8-8", [{**CHUNK_TABLE, "section_no": "8-8-8"}, {**CHUNK_TEXT, "section_no": "8-8-8"}],
        pdf_path=ds.DEFAULT_PDF, spec_format_text="형식 문서", example_spec_text=None, out_dir=out_dir,
        model="fake-model", max_output_tokens=100,
        request_fn=make_request_fn(BAD_CITATION_RESPONSE, bad_calls), cost_tracker=cost_tracker(), force=False,
    )
    check("정상 응답도 저장됨(스키마는 맞으므로)", ds.draft_path(out_dir, "테스트", "9-9-9").exists())
    check("틀린 인용도 저장됨(스키마는 맞으므로)", ds.draft_path(out_dir, "테스트", "8-8-8").exists())

    chunks_path = tmp / "chunks.jsonl"
    chunks_path.write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in [
            {**CHUNK_TABLE, "section_no": "9-9-9"}, {**CHUNK_TEXT, "section_no": "9-9-9"},
            {**CHUNK_TABLE, "section_no": "8-8-8"}, {**CHUNK_TEXT, "section_no": "8-8-8"},
        ]),
        encoding="utf-8",
    )
    chunks_by_id = vd.load_chunks(chunks_path)
    report = vd.build_report(out_dir, chunks_by_id)
    check("검증 대상 2개", report["total"] == 2, str(report["total"]))
    check("정상 응답은 인용 문제 없음", report["with_citation_issues"] == 1, json.dumps(report["results"]))
    check("정상 응답은 ok", any(r["ok"] and r["section_no"] == "9-9-9" for r in report["results"]))
    bad_result = next(r for r in report["results"] if r["section_no"] == "8-8-8")
    check("틀린 인용은 citation_issues에 잡힘", len(bad_result["citation_issues"]) == 1, str(bad_result))
    check("id 형식 검사 통과", vd.check_id_format(GOOD_DRAFT) == [])


# ---------------------------------------------------------------------------

def main() -> int:
    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        check_save_resume_force(tmp)
        check_filter_targets()
        check_group_sections_requires_table()
        check_budget_cap()
        check_budget_stops_processing(tmp)
        check_validation(tmp)

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"통과 {passed} / 전체 {total}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
