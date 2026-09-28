"""초안 명세를 오프라인으로 검증한다(네트워크 호출 없음).

data/drafts/specs/**/*.json을 모두 읽어 형식·출처를 점검하고 data/drafts/report.json에 요약을 남긴다.
실행: python -m pipeline.validate_drafts
      python -m pipeline.validate_drafts --chunks <원래 폴더>/data/processed/chunks.all.jsonl
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL_ROOT = Path(r"C:\Users\daeseong\Desktop\PROJECTS\civilai-construction-risk-agent")

DEFAULT_CHUNKS = ORIGINAL_ROOT / "data/processed/chunks.jsonl"  # draft_specs.py 기본값과 동일하게
DEFAULT_DRAFTS_DIR = ROOT / "data/drafts"

REQUIRED_DRAFT_FIELDS = {"id", "edition", "division", "section_no", "title", "work", "review",
                          "source_pages", "inputs", "tables", "quantity_model"}
ID_PATTERN = re.compile(r"^2026-정오표1차/[^/]+/[^/]+/[^/]+$")


def chunks_by_id_from_list(chunks: list[dict]) -> dict[str, dict]:
    """table_id/chunk_id -> 조각. 조각 ID는 파일마다 다를 수 있으니 같은 chunks 목록으로만 대조한다."""
    chunks_by_id: dict[str, dict] = {}
    for chunk in chunks:
        if chunk["kind"] == "table":
            table_id = chunk["source"].get("table_id")
            if table_id:
                chunks_by_id[table_id] = chunk
        else:
            chunks_by_id[chunk["chunk_id"]] = chunk
    return chunks_by_id


def load_chunks_file(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_chunks(path: Path) -> dict[str, dict]:
    """table_id/chunk_id -> 조각. chunks 파일이 없으면 빈 사전(출처 대조는 전부 불일치로 표시)."""
    return chunks_by_id_from_list(load_chunks_file(path))


def file_sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", text).replace(",", "")


def check_table_citation(chunks_by_id: dict, citation: dict) -> str | None:
    """None이면 일치, 아니면 불일치 사유 문자열."""
    table_id = citation.get("table_id")
    chunk = chunks_by_id.get(table_id)
    if chunk is None:
        return f"table_id 없음: {table_id}"
    text = _normalize(chunk.get("text", ""))
    row = citation.get("row")
    column = citation.get("column")
    value = citation.get("value")
    if row is not None and _normalize(str(row)) not in text:
        return f"row '{row}'이 {table_id} 조각 텍스트에 없음"
    if column is not None and _normalize(str(column)) not in text:
        return f"column '{column}'이 {table_id} 조각 텍스트에 없음"
    if value is not None and _normalize(str(value)) not in text:
        return f"value '{value}'이 {table_id} 조각 텍스트에 없음"
    return None


def check_text_citation(chunks_by_id: dict, citation: dict) -> str | None:
    chunk_id = citation.get("chunk_id")
    chunk = chunks_by_id.get(chunk_id)
    if chunk is None:
        return f"chunk_id 없음: {chunk_id}"
    quote = citation.get("quote")
    if quote and _normalize(str(quote)) not in _normalize(chunk.get("text", "")):
        return f"quote가 {chunk_id} 조각 텍스트에 없음"
    return None


def check_citations(chunks_by_id: dict, citations: list[dict]) -> list[str]:
    issues = []
    for citation in citations:
        if "table_id" in citation:
            issue = check_table_citation(chunks_by_id, citation)
        elif "chunk_id" in citation:
            issue = check_text_citation(chunks_by_id, citation)
        else:
            issue = f"인용 형식 아님(table_id/chunk_id 없음): {citation}"
        if issue:
            issues.append(issue)
    return issues


def check_required_fields(draft: dict) -> list[str]:
    missing = REQUIRED_DRAFT_FIELDS - draft.keys()
    return [f"필수 필드 누락: {sorted(missing)}"] if missing else []


def check_id_format(draft: dict) -> list[str]:
    draft_id = draft.get("id", "")
    return [] if ID_PATTERN.match(draft_id) else [f"id 형식 오류: {draft_id!r}"]


def validate_one(path: Path, drafts_dir: Path, chunks_by_id: dict, chunks_sha256: str | None) -> dict:
    record = json.loads(path.read_text(encoding="utf-8"))
    draft = record.get("draft", {})
    issues = check_required_fields(draft) + check_id_format(draft)
    citation_issues = check_citations(chunks_by_id, record.get("citations", []))
    meta_sha256 = record.get("meta", {}).get("chunks_sha256")
    chunks_mismatch = bool(meta_sha256 and chunks_sha256 and meta_sha256 != chunks_sha256)
    return {
        "path": str(path.relative_to(drafts_dir)),
        "division": draft.get("division"), "section_no": draft.get("section_no"),
        "calc_type": record.get("calc_type"), "open_questions": len(record.get("open_questions", [])),
        "format_issues": issues, "citation_issues": citation_issues, "chunks_mismatch": chunks_mismatch,
        "ok": not issues and not citation_issues,
    }


def build_report(drafts_dir: Path, chunks_by_id: dict, chunks_sha256: str | None = None) -> dict:
    paths = sorted((drafts_dir / "specs").rglob("*.json"))
    results = [validate_one(path, drafts_dir, chunks_by_id, chunks_sha256) for path in paths]
    calc_type_counts: dict[str, int] = {}
    for result in results:
        calc_type = result["calc_type"] or "없음"
        calc_type_counts[calc_type] = calc_type_counts.get(calc_type, 0) + 1
    return {
        "total": len(results),
        "ok": sum(1 for r in results if r["ok"]),
        "with_format_issues": sum(1 for r in results if r["format_issues"]),
        "with_citation_issues": sum(1 for r in results if r["citation_issues"]),
        "with_chunks_mismatch": sum(1 for r in results if r["chunks_mismatch"]),
        "total_open_questions": sum(r["open_questions"] for r in results),
        "calc_type_counts": calc_type_counts,
        "results": results,
    }


def print_summary(report: dict) -> None:
    print(f"초안 {report['total']}개: 정상 {report['ok']}, 형식 문제 {report['with_format_issues']}, "
          f"인용 불일치 {report['with_citation_issues']}, chunks 불일치 {report['with_chunks_mismatch']}")
    print(f"open_questions 합계: {report['total_open_questions']}")
    print("calc_type 분포:", ", ".join(f"{k}={v}" for k, v in sorted(report["calc_type_counts"].items())))
    for result in report["results"]:
        label = f"{result['division']}/{result['section_no']}"
        if result["chunks_mismatch"]:
            print(f"  경고 {label}: 초안을 만들 때 쓴 chunks 파일과 지금 검증에 쓴 chunks 파일이 다름")
        if not result["ok"]:
            for issue in result["format_issues"] + result["citation_issues"]:
                print(f"  FAIL {label}: {issue}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--chunks", default=str(DEFAULT_CHUNKS))
    parser.add_argument("--drafts-dir", default=str(DEFAULT_DRAFTS_DIR))
    args = parser.parse_args()

    chunks_path = Path(args.chunks)
    chunks_by_id = load_chunks(chunks_path)
    chunks_sha256 = file_sha256(chunks_path)
    drafts_dir = Path(args.drafts_dir)
    report = build_report(drafts_dir, chunks_by_id, chunks_sha256)
    print_summary(report)

    report_path = drafts_dir / "report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"보고서: {report_path}")
    return 0 if report["with_format_issues"] == 0 and report["with_citation_issues"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
