"""원격 main 파서와 현재 파서를 PDF 전 페이지에서 쪽별 비교한다.

실행: .venv/Scripts/python.exe evals/check_parse_regression.py
기존 레코드의 글자뿐 아니라 상태·출처도 보존되어야 통과한다.
"""

import json
import subprocess
import sys
import types
from collections import Counter
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
from parse import parse_pages  # noqa: E402

PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
BASE = "origin/main"


def git_output(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, encoding="utf-8"
    )
    return result.stdout


def main_parser():
    source = git_output("show", f"{BASE}:pipeline/parse.py")
    module = types.ModuleType("main_parse_baseline")
    module.__file__ = f"{BASE}:pipeline/parse.py"
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    return module.parse_pages


def record_key(record: dict) -> str:
    return json.dumps(record, ensure_ascii=False, sort_keys=True)


def text_key(record: dict) -> tuple:
    return record.get("kind"), record.get("table_id"), record["text"]


def main() -> int:
    original_parse = main_parser()
    revision = git_output("rev-parse", BASE).strip()[:12]
    with pymupdf.open(PDF) as doc:
        page_count = len(doc)
    print(f"기준: {BASE} ({revision}), 대상: 1~{page_count}쪽", flush=True)

    old_total = new_total = changed_pages = text_changed = errors = 0
    for page_no in range(1, page_count + 1):
        try:
            original = original_parse(str(PDF), page_no, page_no)
            current = parse_pages(str(PDF), page_no, page_no)
        except Exception as exc:
            errors += 1
            print(f"p{page_no}: 파싱 오류 {type(exc).__name__}: {exc}", flush=True)
            continue

        old = sum((Counter(map(record_key, original)) - Counter(map(record_key, current))).values())
        new = sum((Counter(map(record_key, current)) - Counter(map(record_key, original))).values())
        old_text = sum((Counter(map(text_key, original)) - Counter(map(text_key, current))).values())
        old_total += old
        new_total += new
        text_changed += old_text
        if old or new:
            changed_pages += 1
            print(f"p{page_no}: 기존 변경·삭제 {old} (글자 {old_text}), 새 레코드 {new}", flush=True)
        if page_no % 100 == 0:
            print(f"진행 {page_no}/{page_count}쪽", flush=True)

    print(
        f"합계: 기존 변경·삭제 {old_total}건 (글자 {text_changed}건), "
        f"새 레코드 {new_total}건, 차이 쪽 {changed_pages}쪽, 오류 {errors}쪽"
    )
    if old_total or errors:
        print("FAIL 기존 레코드가 바뀌거나 사라졌음")
        return 1
    print("PASS 기존 레코드 변경·삭제 0건")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
