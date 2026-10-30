"""기존 품셈 명세 초안을 별도 후보로 정제하고 출처·형식을 오프라인 검증한다.

안전 기본값은 prepare/validate/candidate이며 모델 호출은 `refine --execute-model`에서만 한다.
어떤 명령도 data/drafts 또는 운영 명세 파일을 덮어쓰지 않는다.

예:
  python -m pipeline.refine_spec_rules prepare --division 공통 --section 6-3-1 --out-dir tmp/refine-6-3-1
  python -m pipeline.refine_spec_rules validate --bundle tmp/refine-6-3-1/input.json --candidate tmp/refine-6-3-1/candidate.json
  python -m pipeline.refine_spec_rules candidate --bundle tmp/refine-6-3-1/input.json --candidate-json edited.json --out tmp/refine-6-3-1/candidate.json
  python -m pipeline.refine_spec_rules refine --bundle tmp/refine-6-3-1/input.json --out tmp/refine-6-3-1/candidate.json --execute-model
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
DEFAULT_CHUNKS = ROOT / "data/processed/chunks.all.jsonl"
DEFAULT_PAGE_MAP = ROOT / "data/processed/page_map.json"
DEFAULT_DRAFTS = ROOT / "data/drafts/specs"
DEFAULT_CONFIG = ROOT / "pipeline/draft_specs_config.json"
PROTECTED_DIRS = (ROOT / "data/drafts", ROOT / "data/specs", ROOT / "backend/agent/rules/specs")
REQUIRED = {"id", "edition", "division", "section_no", "title", "work", "review", "source_pages", "inputs", "tables", "quantity_model"}
NUMBER_RE = re.compile(r"(?<![\w])\d+(?:\.\d+)?\s*(?:%|㎜|mm|m|㎡|㎥|t/㎡|인·일|회|대)?")
MODEL_RESPONSE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object", "required": ["draft", "calc_type", "citations", "open_questions"],
    "properties": {
        "draft": {"type": "object", "required": sorted(REQUIRED), "additionalProperties": True},
        "calc_type": {"type": "string", "enum": ["daily_crew", "per_unit", "rate", "lookup_only", "not_calculable"]},
        "citations": {"type": "array", "items": {"oneOf": [
            {"type": "object", "required": ["chunk_id", "quote"], "properties": {"chunk_id": {"type": "string"}, "quote": {"type": "string"}}, "additionalProperties": False},
            {"type": "object", "required": ["table_id", "row", "column", "value"], "properties": {"table_id": {"type": "string"}, "row": {"type": "string"}, "column": {"type": "string"}, "value": {"type": "string"}}, "additionalProperties": False},
        ]}},
        "open_questions": {"type": "array", "items": {"type": "string"}},
        "refinement_notes": {"type": "array", "items": {"type": "string"}},
    }, "additionalProperties": True,
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_chunks(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def assert_new_output(path: Path, protected_files: tuple[Path, ...] | list[Path] = ()) -> Path:
    target = path.resolve()
    for protected_dir in PROTECTED_DIRS:
        try:
            target.relative_to(protected_dir.resolve())
        except ValueError:
            continue
        raise ValueError(f"보호 경로에는 출력할 수 없습니다: {target}")
    blocked = [p.resolve() for p in protected_files if p is not None]
    if target in blocked:
        raise ValueError(f"입력/원본 파일 경로에는 출력할 수 없습니다: {target}")
    if target.exists():
        raise FileExistsError(f"기존 출력 파일 덮어쓰기는 허용되지 않습니다: {target}")
    return target


def json_write(path: Path, value: Any, *, protected_files: tuple[Path, ...] | list[Path] = ()) -> None:
    path = assert_new_output(path, protected_files)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def prepare(args: argparse.Namespace) -> int:
    out = Path(args.out_dir).resolve()
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"출력 폴더가 비어 있지 않습니다: {out}")
    chunks_path, pdf_path, page_map_path = map(Path, (args.chunks, args.pdf, args.page_map))
    draft_path = Path(args.draft) if args.draft else DEFAULT_DRAFTS / args.division / f"{args.section}.json"
    protected_inputs = [draft_path, chunks_path, pdf_path, page_map_path]
    for filename in ("source_excerpt.pdf", "manifest.json", "input.json"):
        assert_new_output(out / filename, protected_inputs)
    chunks = [c for c in read_chunks(chunks_path) if c.get("division") == args.division and c.get("section_no") == args.section]
    if not chunks:
        raise SystemExit(f"파싱 조각이 없습니다: {args.division}/{args.section} ({chunks_path})")
    if not draft_path.exists():
        raise SystemExit(f"기존 draft를 찾을 수 없습니다: {draft_path}")
    draft_record = json.loads(draft_path.read_text(encoding="utf-8"))
    page_map = json.loads(page_map_path.read_text(encoding="utf-8")).get("pages", {}) if page_map_path.exists() else {}
    source_pages = sorted({int(p) for c in chunks for p in (c.get("pages") or [c.get("source", {}).get("page")]) if p})
    # 절의 모든 파싱 페이지와 마지막 페이지 다음 쪽(이어지는 비고)을 기본 포함한다.
    pdf_pages = sorted(set(source_pages + ([source_pages[-1] + 1] if source_pages else []) + args.extra_pdf_page))
    import pymupdf
    with pymupdf.open(pdf_path) as source_pdf:
        invalid = [p for p in pdf_pages if p < 1 or p > source_pdf.page_count]
        if invalid:
            raise SystemExit(f"PDF 페이지 범위 오류(1부터 세는 PDF index): {invalid}; 전체 {source_pdf.page_count}쪽")
        excerpt = pymupdf.open()
        page_records = []
        for pdf_page in pdf_pages:
            page = source_pdf[pdf_page - 1]
            text = page.get_text()
            excerpt.insert_pdf(source_pdf, from_page=pdf_page - 1, to_page=pdf_page - 1)
            page_records.append({"pdf_page_index_1based": pdf_page,
                                 "printed_page": page_map.get(str(pdf_page), {}).get("printed_page"),
                                 "text": text})
        out.mkdir(parents=True, exist_ok=True)
        excerpt.save(out / "source_excerpt.pdf")
        excerpt.close()
    source_ids = {}
    parsed = []
    for chunk in chunks:
        kind = chunk.get("kind")
        if kind == "table":
            ident = chunk.get("source", {}).get("table_id")
        else:
            ident = chunk.get("chunk_id")
        if ident:
            source_ids[ident] = {"kind": kind, "text": chunk.get("text", ""), "pdf_pages": chunk.get("pages", [])}
        parsed.append(chunk)
    warnings = []
    old_pages = draft_record.get("draft", {}).get("source_pages", [])
    printed_pages = [p["printed_page"] for p in page_records]
    if old_pages and not set(old_pages).intersection(pdf_pages):
        if set(old_pages).intersection(printed_pages):
            warnings.append(f"기존 draft.source_pages={old_pages}는 PDF 내부 page index가 아니라 인쇄 쪽 번호로 보입니다. 대응 PDF index는 {pdf_pages}; 인쇄 쪽 {printed_pages}입니다.")
        else:
            warnings.append(f"draft의 source_pages={old_pages}와 첨부 PDF page index={pdf_pages}가 겹치지 않습니다. 인쇄 쪽 번호와 PDF index를 manifest에서 대조하세요.")
    # 사용자 지정 중요 사례에 대한 원문/파싱 불일치 경고. 의미 판정은 하지 않는다.
    pdf_text = "\n".join(p["text"] for p in page_records)
    parsed_text = "\n".join(x.get("text", "") for x in parsed)
    for phrase in ("본 품은 수직고 7m까지 적용", "매 3m마다 시공량을 9%", "상시적인 크레인을 활용"):
        if phrase in pdf_text and phrase not in parsed_text:
            warnings.append(f"원문에는 있으나 파싱 조각에 해당 문구가 없습니다: {phrase}")
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(), "division": args.division, "section_no": args.section,
        "pdf": str(pdf_path.resolve()), "pdf_sha256": sha(pdf_path),
        "pdf_pages": [{k: p[k] for k in ("pdf_page_index_1based", "printed_page")} for p in page_records],
        "page_number_note": "pdf_page_index_1based는 PDF 내부 index(1-based); printed_page는 인쇄 쪽 번호이며 서로 다를 수 있음.",
        "chunks": str(chunks_path.resolve()), "chunks_sha256": sha(chunks_path),
        "draft": str(draft_path.resolve()), "draft_sha256": sha(draft_path), "warnings": warnings,
    }
    bundle = {"manifest": manifest, "source_ids": source_ids, "parsed_chunks": parsed,
              "pdf_pages": page_records, "draft_record": draft_record,
              "guardrails": {"status": "candidate_only", "human_review_required": True,
                             "production_promotion_allowed": False}}
    json_write(out / "manifest.json", manifest)
    json_write(out / "input.json", bundle)
    print(f"준비 완료: {out}\nPDF page index: {pdf_pages}; 인쇄 쪽: {[p['printed_page'] for p in page_records]}\n경고: {len(warnings)}건")
    for warning in warnings:
        print(f"경고: {warning}")
    return 0


def candidate_record(value: Any) -> dict:
    # Accept an existing draft record or the model response envelope.
    if not isinstance(value, dict):
        raise ValueError("후보 최상위 JSON은 객체여야 합니다")
    if "draft" not in value or not isinstance(value["draft"], dict):
        raise ValueError("후보 JSON은 {draft: {...}, citations: [...], open_questions: [...]} 구조여야 합니다")
    if value.get("calc_type") not in {"daily_crew", "per_unit", "rate", "lookup_only", "not_calculable"}:
        raise ValueError("calc_type은 허용된 분류 중 하나여야 합니다")
    if not isinstance(value.get("citations", []), list):
        raise ValueError("citations는 배열이어야 합니다")
    if not isinstance(value.get("open_questions", []), list) or not all(isinstance(q, str) for q in value.get("open_questions", [])):
        raise ValueError("open_questions는 문자열 배열이어야 합니다")
    if not all(isinstance(c, dict) for c in value.get("citations", [])):
        raise ValueError("citations 원소는 객체여야 합니다")
    value.setdefault("citations", [])
    value.setdefault("open_questions", [])
    return value


def validate(bundle_path: Path, candidate_path: Path) -> tuple[dict, int]:
    try:
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        if not isinstance(bundle, dict) or not isinstance(bundle.get("manifest"), dict) or not isinstance(bundle.get("source_ids"), dict):
            raise ValueError("bundle은 manifest와 source_ids 객체가 있어야 합니다")
        candidate = candidate_record(json.loads(candidate_path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
        return ({"status": "invalid_input", "errors": [f"입력 JSON/구조 오류: {exc}"], "warnings": [],
                 "open_questions": [], "original_draft_unchanged": False,
                 "machine_checks_do_not_mean_source_semantics_reviewed": True,
                 "production_promotion_allowed": False}, 1)
    draft = candidate["draft"]
    errors: list[str] = []
    warnings: list[str] = list(bundle["manifest"].get("warnings", []))
    missing = sorted(REQUIRED - draft.keys())
    if missing:
        errors.append(f"명세 필수 필드 누락: {missing}")
    for key in ("division", "section_no"):
        if draft.get(key) != bundle["manifest"].get(key):
            errors.append(f"{key}가 bundle 대상과 다릅니다")
    if draft.get("review") != "AI 초안 · 검토 전":
        errors.append("review는 반드시 'AI 초안 · 검토 전'이어야 합니다")
    for field in ("inputs", "tables", "source_pages"):
        if not isinstance(draft.get(field), list):
            errors.append(f"draft.{field}는 배열이어야 합니다")
    if not isinstance(draft.get("quantity_model"), dict):
        errors.append("draft.quantity_model은 객체여야 합니다")
    citation_text = []
    valid_citation_count = 0
    known = bundle.get("source_ids", {})
    for citation in candidate.get("citations", []):
        errors_before = len(errors)
        if not isinstance(citation, dict):
            errors.append("citation 원소가 객체가 아닙니다")
            continue
        if "chunk_id" in citation:
            ident, quote = citation.get("chunk_id"), citation.get("quote")
            if not isinstance(ident, str):
                errors.append("chunk_id는 문자열이어야 합니다")
                continue
            source = known.get(ident)
            if not source:
                errors.append(f"근거 없는 chunk_id: {ident}")
            elif not isinstance(quote, str) or not quote or quote not in source["text"]:
                errors.append(f"{ident} 인용 quote가 파싱 원문에 연속 부분문자열로 없습니다")
            else:
                citation_text.append(quote)
        elif "table_id" in citation:
            ident = citation.get("table_id")
            if not isinstance(ident, str):
                errors.append("table_id는 문자열이어야 합니다")
                continue
            source = known.get(ident)
            if not source or source.get("kind") != "table":
                errors.append(f"근거 없는 table_id: {ident}")
            else:
                missing_citation_fields = {"row", "column", "value"} - citation.keys()
                if missing_citation_fields:
                    errors.append(f"{ident} 표 citation 필드 누락: {sorted(missing_citation_fields)}")
                # 값과 행/열 표기가 실제 파싱 조각에 있는지 확인한다.
                for field in ("row", "column", "value"):
                    value = citation.get(field)
                    if not isinstance(value, str):
                        errors.append(f"{ident} citation의 {field}는 문자열이어야 합니다")
                        continue
                    if value is not None and str(value) not in source["text"]:
                        errors.append(f"{ident}의 {field}={value!r}가 파싱 표 텍스트에 없습니다")
                citation_text.append(source["text"])
        else:
            errors.append("citation에 chunk_id 또는 table_id가 없습니다")
        if len(errors) == errors_before:
            valid_citation_count += 1
    if not candidate.get("citations"):
        errors.append("출처 인용이 하나도 없습니다")
    # 명세 안의 표/규칙 참조 ID가 입력 bundle에 존재하는지 검사한다.
    def scan_ids(value: Any, path: str = "draft") -> None:
        if isinstance(value, dict):
            for k, v in value.items():
                if k in ("table", "table_id", "chunk_id") and isinstance(v, str) and v not in known:
                    errors.append(f"{path}.{k}에 근거 없는 source ID: {v}")
                scan_ids(v, f"{path}.{k}")
        elif isinstance(value, list):
            for i, v in enumerate(value):
                scan_ids(v, f"{path}[{i}]")
    scan_ids(draft)
    # 수치/단위 값이 인용 원문 corpus에 아예 없는 경우를 탐지한다. 이는 의미 검증을 대신하지 않는다.
    cited_corpus = "\n".join(citation_text)
    def collect_internal_cites(value: Any) -> None:
        if isinstance(value, dict):
            cite = value.get("cite")
            cite_items = cite if isinstance(cite, list) else [cite]
            for ref in cite_items:
                if isinstance(ref, dict):
                    ident = ref.get("table_id") or ref.get("chunk_id")
                    if ident in known:
                        citation_text.append(known[ident]["text"])
            for child in value.values():
                collect_internal_cites(child)
        elif isinstance(value, list):
            for child in value:
                collect_internal_cites(child)
    collect_internal_cites(draft)
    cited_corpus = "\n".join(citation_text)
    numeric_candidates = []
    def collect_claim_text(value: Any, key: str = "") -> list[str]:
        if key in {"source_pages", "section_no", "id", "source", "rate_codes", "edition"}:
            return []
        if isinstance(value, dict):
            return [item for k, child in value.items() for item in collect_claim_text(child, k)]
        if isinstance(value, list):
            return [item for child in value for item in collect_claim_text(child, key)]
        return [value] if isinstance(value, str) else []
    for claim in collect_claim_text(draft):
        for match in NUMBER_RE.finditer(claim):
            token = match.group(0).strip()
            if token and token not in cited_corpus:
                numeric_candidates.append(token)
    if numeric_candidates:
        errors.append("인용 근거에서 그대로 찾지 못한 숫자/단위 표현: " + ", ".join(sorted(set(numeric_candidates))))
    open_questions = candidate.get("open_questions")
    if not isinstance(open_questions, list):
        errors.append("open_questions는 배열이어야 합니다")
        open_questions = ["invalid"]
    if open_questions:
        warnings.append(f"미확정 사항 {len(open_questions)}건이 남아 있어 사람 검토가 필요합니다")
    # High-risk interpretation rules for the known formwork note. These checks only
    # reject unsafe wording; passing them never certifies that the source was understood.
    is_formwork_case = bundle["manifest"].get("division") == "공통" and bundle["manifest"].get("section_no") == "6-3-1"
    draft_text = " ".join(collect_claim_text(draft))
    if is_formwork_case:
        sentences = re.split(r"[.!?。\n]", draft_text)
        unsafe_9 = any("9%" in s and re.search(r"(해야|하여야|반드시|무조건|의무적으로|고정적으로)", s)
                       and not any(word in s for word in ("까지", "최대", "이하", "상한")) for s in sentences)
        unsafe_9 |= any("9%" in re.sub(r"\s+", "", s) and re.search(r"(?:감산|감소|감한다|감산한다|줄인다|차감)(?:한다|함|적용|해야|하여야)?", re.sub(r"\s+", "", s))
                        and not any(word in s for word in ("까지", "최대", "이하", "상한")) for s in sentences)
        if unsafe_9:
            errors.append("공통 6-3-1에서 9% 감산을 고정·의무 규칙으로 표현했습니다. '최대' 등의 단어가 다른 문장에 있는지는 이 판정에 영향을 주지 않습니다.")
        compact = re.sub(r"\s+", "", draft_text)
        if any(term in compact for term in ("물량을감산", "물량감산", "실제물량감소", "물량×0.91", "물량*0.91",
                                             "물량에0.91을곱", "volume*0.91")):
            errors.append("공통 6-3-1의 시공량 조정 규칙을 물리 물량 감소로 표현했습니다")
        compact_questions = [re.sub(r"\s+", "", q) for q in open_questions]
        if "9%" in draft_text and not any("3m" in q and any(word in q for word in ("누적", "잔여", "구간별", "각구간")) for q in compact_questions):
            errors.append("공통 6-3-1의 매 3m 누적/잔여 구간 방식을 미확정 질문으로 남겨야 합니다")
    text_only_blocks = [i for i, block in enumerate(draft.get("blocked", []))
                        if isinstance(block, dict) and block.get("condition") and not block.get("blocked_if")]
    if text_only_blocks:
        warnings.append(
            "기계 판정 조건이 없는 blocked 항목이 있습니다(인덱스: "
            + ", ".join(map(str, text_only_blocks))
            + "). 설명상 보류와 실행 시 자동 차단은 다르므로 실행 경로에서 별도 처리가 필요합니다."
        )
    manifest = bundle["manifest"]
    draft_source = Path(manifest.get("draft", ""))
    try:
        original_hash_now = sha(draft_source) if draft_source.is_file() else None
        original_unchanged = original_hash_now == manifest.get("draft_sha256")
    except OSError:
        original_unchanged = False
    if not original_unchanged:
        errors.append("입력 draft 원본 파일이 prepare 이후 변경되었습니다")
    diff = "\n".join(difflib.unified_diff(
        json.dumps(bundle["draft_record"].get("draft", {}), ensure_ascii=False, indent=2).splitlines(),
        json.dumps(draft, ensure_ascii=False, indent=2).splitlines(), fromfile="original-draft", tofile="candidate-draft", lineterm=""))
    result = {"status": "needs_human_review" if (errors or warnings or open_questions) else "machine_checks_passed_review_still_required",
              "errors": errors, "warnings": warnings, "open_questions": open_questions,
              "original_draft_unchanged": original_unchanged, "candidate_diff": diff,
              "machine_checks_do_not_mean_source_semantics_reviewed": True,
              "production_promotion_allowed": False,
              "citation_text_matches": valid_citation_count}
    return result, (1 if errors or open_questions else 0)


def validate_cmd(args: argparse.Namespace) -> int:
    result, status = validate(Path(args.bundle), Path(args.candidate))
    if args.report:
        protected = [Path(args.bundle), Path(args.candidate)]
        try:
            bundle = json.loads(Path(args.bundle).read_text(encoding="utf-8"))
            for key in ("draft", "pdf", "chunks"):
                value = bundle.get("manifest", {}).get(key) if isinstance(bundle.get("manifest"), dict) else None
                if value:
                    protected.append(Path(value))
        except (OSError, json.JSONDecodeError, AttributeError):
            pass
        try:
            json_write(Path(args.report), result, protected_files=protected)
        except (ValueError, FileExistsError) as exc:
            print(f"검토 보고서를 쓰지 않았습니다: {exc}")
            return 1
    print(json.dumps({k: v for k, v in result.items() if k != "candidate_diff"}, ensure_ascii=False, indent=2))
    if args.report:
        print(f"차이/검토 보고서: {args.report}")
    return status


def candidate_cmd(args: argparse.Namespace) -> int:
    # Copy a human/offline-authored candidate into a distinct review location, then validate.
    source, out = Path(args.candidate_json), Path(args.out)
    bundle = json.loads(Path(args.bundle).read_text(encoding="utf-8"))
    protected = [source, Path(args.bundle)]
    for key in ("draft", "pdf", "chunks"):
        value = bundle.get("manifest", {}).get(key)
        if value:
            protected.append(Path(value))
    assert_new_output(out, protected)
    report_path = out.with_suffix(".review.json")
    assert_new_output(report_path, protected + [out])
    candidate_record(json.loads(source.read_text(encoding="utf-8")))
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, out)
    report, code = validate(Path(args.bundle), out)
    json_write(report_path, report, protected_files=protected + [out])
    print(f"후보: {out}\n검토 보고서: {out.with_suffix('.review.json')}\n상태: {report['status']}")
    return code


def refine_cmd(args: argparse.Namespace) -> int:
    if not args.execute_model:
        print("모델 호출은 실행되지 않았습니다. 실제 호출은 --execute-model을 명시해야 합니다.")
        return 0
    bundle_path, out_path = Path(args.bundle), Path(args.out)
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    protected = [bundle_path]
    for key in ("draft", "pdf", "chunks"):
        value = bundle.get("manifest", {}).get(key)
        if value:
            protected.append(Path(value))
    assert_new_output(out_path, protected)
    report_path = out_path.with_suffix(".review.json")
    assert_new_output(report_path, protected + [out_path])
    from pipeline import draft_specs
    config = draft_specs.load_pricing_config(Path(args.config))
    api_key = draft_specs.env_value("VERTEX_API_KEY_BULK", Path(args.env))
    if not api_key:
        raise SystemExit("VERTEX_API_KEY_BULK가 없습니다(.env 또는 환경 변수). 모델 호출은 시작하지 않았습니다.")
    target_rules = ""
    if bundle["manifest"].get("division") == "공통" and bundle["manifest"].get("section_no") == "6-3-1":
        target_rules = (
            "6-3-1 주의: '9%까지'는 최대 감산 표현이므로 9%를 매번 의무 적용한다고 단정하지 마세요."
            "시공량 규칙을 물리 물량 감산으로 바꾸지 마세요. 매 3m 구간의 누적/잔여 계산법이 명시되지 않으면 open_questions로 남기세요."
            "상시 크레인 문구의 장비 추가 및 시공량 감산 없음 해석은 원문 인용과 함께 검토하세요.\n"
        )
    prompt = (
        "[명세 형식]\n" + (ROOT / "docs/SPEC_FORMAT.md").read_text(encoding="utf-8") + "\n"
        "2026 건설공사표준품셈 규칙 명세 후보를 정제하세요. 다음 JSON bundle만 근거로 사용하고 Python/eval 코드 생성은 금지합니다.\n"
        "숫자, 대상, 조건, 단위, 예외, 출처 인용을 명시하세요. 원문 의미가 정해지지 않으면 open_questions에 남기고 계산 규칙을 추측하지 마세요.\n"
        + target_rules
        + "반드시 다음 JSON Schema를 따르세요:\n" + json.dumps(MODEL_RESPONSE_SCHEMA, ensure_ascii=False) + "\n"
        "candidate의 review는 'AI 초안 · 검토 전'이어야 합니다. bundle:\n" + json.dumps(bundle, ensure_ascii=False)
    )
    pdf_bytes = (bundle_path.parent / "source_excerpt.pdf").read_bytes()
    request = draft_specs.make_vertex_request_fn(api_key)
    response, input_tokens, output_tokens = draft_specs.call_with_retry(
        request, config["model"], pdf_bytes, prompt, config.get("max_output_tokens", 8192))
    candidate = candidate_record(json.loads(response))
    candidate["meta"] = {"model": config["model"], "input_tokens": input_tokens, "output_tokens": output_tokens,
                         "created_at": datetime.now(timezone.utc).isoformat(), "source_bundle_sha256": sha(bundle_path),
                         "candidate_only": True}
    json_write(out_path, candidate, protected_files=protected)
    report, code = validate(bundle_path, out_path)
    json_write(report_path, report, protected_files=protected + [out_path])
    return code


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare", help="원문 PDF 발췌, 파싱 조각, 기존 draft 입력 bundle 준비")
    prep.add_argument("--division", required=True); prep.add_argument("--section", required=True)
    prep.add_argument("--out-dir", required=True); prep.add_argument("--draft")
    prep.add_argument("--pdf", default=str(DEFAULT_PDF)); prep.add_argument("--chunks", default=str(DEFAULT_CHUNKS))
    prep.add_argument("--page-map", default=str(DEFAULT_PAGE_MAP)); prep.add_argument("--extra-pdf-page", type=int, action="append", default=[], help="추가할 PDF 내부 페이지 index(1부터 셈); 인쇄 쪽 번호와 구별")
    prep.set_defaults(func=prepare)
    val = sub.add_parser("validate", help="후보의 필수 형식, source ID, 인용, 숫자 근거 및 원본 불변 검사")
    val.add_argument("--bundle", required=True); val.add_argument("--candidate", required=True); val.add_argument("--report")
    val.set_defaults(func=validate_cmd)
    cand = sub.add_parser("candidate", help="편집한 JSON 후보를 별도 경로에 복사하고 검토 보고서 생성")
    cand.add_argument("--bundle", required=True); cand.add_argument("--candidate-json", required=True); cand.add_argument("--out", required=True)
    cand.set_defaults(func=candidate_cmd)
    ref = sub.add_parser("refine", help="Gemini로 후보 생성; --execute-model 없이는 모델을 호출하지 않음")
    ref.add_argument("--bundle", required=True); ref.add_argument("--out", required=True); ref.add_argument("--execute-model", action="store_true")
    ref.add_argument("--config", default=str(DEFAULT_CONFIG)); ref.add_argument("--env", default=str(ROOT / ".env"))
    ref.set_defaults(func=refine_cmd)
    return p


def main() -> int:
    args = parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
