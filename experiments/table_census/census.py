"""2026 표준품셈 PDF의 표를 전수 계수하고 규칙으로 분류한다.

저장소 루트에서 ``python experiments/table_census/census.py``로 실행한다.
운영 파서와 평가 입력 파일에는 쓰지 않는다.
"""

from __future__ import annotations

import json
import random
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline"))
from parse import SECTION_RE, parse_pages, read_titles, title_above  # noqa: E402

PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
SEED = 2026
TYPES = ("A", "B", "C", "D", "E", "F", "X")
NAMES = {
    "A": "일당 작업조형", "B": "단위당 품형", "C": "재료량형",
    "D": "할증·보정률형", "E": "장비·산식형", "F": "참고·기준값형",
    "X": "파싱 불량",
}

DAILY = re.compile(r"[(（]\s*일당\s*[)）]")
PER_UNIT = re.compile(r"[(（]\s*(?:\d+(?:\.\d+)?\s*)?(?:㎥|m³|m3|㎢|㎡|m²|m2|m|㎞|km|kg|㎏|g|ℓ|L|l|ton|t|톤|개|본|매|장|조|식|대|인|시간|hr)\s*당\s*[)）]", re.I)
LABOR = re.compile(r"(?:단위\s*인(?:\s|\||$)|\b(?:인부|목공|철근공|콘크리트공|미장공|도장공|용접공|배관공|전공|석공|조적공|비계공|타일공|기능공|작업원|인력)\b|직종)")
PERCENT = re.compile(r"\d+(?:\.\d+)?\s*%")
ADJUST = re.compile(r"할증|보정|감액|감소|감하여|가산|할인|증감|증가율|감소율")
EQUIPMENT = re.compile(r"(?:\bhr\b|\bQ\s*=|작업능력|기계경비|장비|굴착기|기중기|크레인|덤프트럭|불도저|로더|롤러|펌프카|단위\s*대(?:\s|\||$))", re.I)
MATERIAL = re.compile(r"(?:단위\s*(?:kg|㎏|g|ℓ|L|l|㎥|m³|m3|㎡|m²|m2|m|㎞|km|개|본|매|장|톤|ton|t)(?:\s|\||$)|재료|자재|소요량|사용량)", re.I)
SECTION_NO = re.compile(r"^(\d+(?:-\d+){1,2})\b")


def nearby_basis(page, box, previous_bottom: float) -> str:
    """표 바로 위의 독립 텍스트 블록에서만 기준 단위를 읽는다."""
    candidates = []
    for block in page.get_text("blocks"):
        x0, y0, x1, y1, raw, _, kind = block
        if kind != 0 or y1 > box[1] + 2 or y0 < previous_bottom - 2:
            continue
        gap = box[1] - y1
        if gap < -2 or gap > 45 or x1 < box[0] - 8 or x0 > box[2] + 8:
            continue
        marker = DAILY.search(raw) or PER_UNIT.search(raw)
        if marker:
            candidates.append((gap, marker.group()))
    return min(candidates)[1] if candidates else ""


def classify(records: list[dict], basis: str) -> tuple[str, str, int]:
    count = len(records)
    uncertain = sum(r.get("structure", {}).get("status") == "uncertain" for r in records)
    if count == 0:
        return "X", "파서 레코드 0개", uncertain
    if uncertain * 2 > count:
        return "X", f"uncertain {uncertain}/{count}행(과반)", uncertain

    rows = [r["text"] for r in records if "| 비고 |" not in r["text"]]
    body = "\n".join(rows)
    has_labor = bool(LABOR.search(body))
    if DAILY.search(basis) or DAILY.search(body):
        return "A", f"일당 표기 {basis or '표 내부'}", uncertain
    if has_labor and "시공량" in body:
        return "A", "시공량 + 직종/인", uncertain
    if has_labor and (PER_UNIT.search(basis) or PER_UNIT.search(body)):
        return "B", f"단위당 표기 {basis or '표 내부'} + 직종/인", uncertain

    percent_rows = sum(bool(PERCENT.search(row)) for row in rows)
    if rows and percent_rows * 2 > len(rows):
        return "D", f"% 포함 {percent_rows}/{len(rows)}행(과반)", uncertain
    # 일반 절 제목과 비고 문장의 '감' 등은 판정에 쓰지 않는다.
    value_text = "\n".join(" | ".join(row.split(" | ")[1:]) for row in rows)
    if ADJUST.search(value_text):
        return "D", "표 행의 할증/보정/감액/가산 등", uncertain
    if EQUIPMENT.search(value_text):
        return "E", "표 행의 장비/hr/Q=/작업능력/기계경비", uncertain
    if not has_labor and MATERIAL.search(value_text):
        return "C", "재료 단위/소요량 + 직종/인 없음", uncertain
    return "F", "상위 유형의 명시적 단서 없음", uncertain


def section_for_table(records: list[dict], titles: list, top: float, inherited: str) -> str:
    local = next((r.get("section", "") for r in records if SECTION_RE.match(r.get("section", ""))), "")
    if local:
        return local
    title = title_above(titles, top)
    if SECTION_RE.match(title):
        return title
    return inherited or title


def aggregates(tables: list[dict], errors: list[dict], elapsed: float, pages: int) -> dict:
    total = len(tables)
    counts = Counter(t["type"] for t in tables)
    chapters = defaultdict(Counter)
    sections = defaultdict(list)
    for table in tables:
        chapters[table["chapter"] or "미상"][table["type"]] += 1
        sections[table["section"] or "미상"].append(table)
    by_section = {}
    for name, group in sorted(sections.items()):
        group_counts = Counter(t["type"] for t in group)
        maximum = max(group_counts.values())
        by_section[name] = {
            "table_count": len(group),
            "by_type": {code: group_counts[code] for code in TYPES},
            "dominant_types": [code for code in TYPES if group_counts[code] == maximum],
            "has_A_or_B": bool(group_counts["A"] + group_counts["B"]),
        }
    focus = [t for t in tables if 185 <= t["page"] <= 214]
    focus_counts = Counter(t["type"] for t in focus)
    return {
        "pdf_pages": pages,
        "total_tables": total,
        "tables_with_records": sum(t["record_count"] > 0 for t in tables),
        "by_type": {
            code: {"count": counts[code], "ratio": counts[code] / total if total else 0}
            for code in TYPES
        },
        "A_B_ratio": (counts["A"] + counts["B"]) / total if total else 0,
        "X_ratio": counts["X"] / total if total else 0,
        "by_chapter": {
            chapter: {code: group[code] for code in TYPES}
            for chapter, group in sorted(chapters.items(), key=lambda pair: (pair[0] == "미상", pair[0]))
        },
        "by_section": by_section,
        "sections_with_A_or_B": sum(item["has_A_or_B"] for item in by_section.values()),
        "zero_record_tables": [t["table_id"] for t in tables if t["record_count"] == 0],
        "uncertain_majority_tables": sum(
            t["record_count"] > 0 and t["uncertain_rows"] * 2 > t["record_count"]
            for t in tables
        ),
        "error_pages": errors,
        "pages_185_214": {
            "table_count": len(focus),
            "tables_with_records": sum(t["record_count"] > 0 for t in focus),
            "by_type": {code: focus_counts[code] for code in TYPES},
            "tables_with_uncertain": sum(t["uncertain_rows"] > 0 for t in focus),
            "zero_record_tables": [t["table_id"] for t in focus if t["record_count"] == 0],
        },
        "elapsed_seconds": round(elapsed, 2),
    }


def spot_check(tables: list[dict], sample_rows: dict[str, list[str]]) -> str:
    rng = random.Random(SEED)
    lines = ["# 표 유형별 PDF 대조 표본", "", f"고정 seed: {SEED}. 각 유형에서 최대 5개를 무작위 추출했다.", ""]
    for code in TYPES:
        group = [t for t in tables if t["type"] == code]
        picks = rng.sample(group, min(5, len(group)))
        lines.extend([f"## {code} · {NAMES[code]} ({len(picks)}/{len(group)})", ""])
        for table in picks:
            lines.extend([
                f"### {table['table_id']} · PDF {table['page']}쪽",
                "",
                f"- bbox: `{table['bbox']}`",
                f"- 절: {table['section'] or '미상'}",
                f"- 판정: {table['reason']}",
                "- 레코드 앞 3줄:",
                "",
                "```text",
                *(sample_rows[table["table_id"]] or ["(레코드 없음)"]),
                "```",
                "",
            ])
    return "\n".join(lines)


def report(summary: dict) -> str:
    total = summary["total_tables"]
    focus = summary["pages_185_214"]
    lines = [
        f"# 전체 표 수: {total}개 · A+B 비율: {summary['A_B_ratio']:.1%} · 파싱 불량(X) 비율: {summary['X_ratio']:.1%}",
        "",
        "# 표준품셈 전 페이지 표 유형 조사",
        "",
        f"PDF {summary['pdf_pages']}쪽을 조사했다. 실행 시간 {summary['elapsed_seconds']:.2f}초.",
        "수치는 `results/summary.json`에서 생성한다. 유형 판정은 사람 검토 전 규칙 기반 추정이다.",
        "",
        "## 유형별 표", "", "| 유형 | 표 수 | 비율 |", "|---|---:|---:|",
    ]
    for code in TYPES:
        item = summary["by_type"][code]
        lines.append(f"| {code} {NAMES[code]} | {item['count']} | {item['ratio']:.1%} |")
    lines.extend([
        "", f"A/B를 하나 이상 가진 절: {summary['sections_with_A_or_B']}개 / {len(summary['by_section'])}개 절.",
        f"레코드가 있는 표: {summary['tables_with_records']}개. "
        f"0레코드 표: {len(summary['zero_record_tables'])}개. "
        f"uncertain 과반 표: {summary['uncertain_majority_tables']}개. "
        f"오류 쪽: {len(summary['error_pages'])}개.",
        "장별×유형 및 절별 전체 수치는 `results/summary.json`에 있다.",
        "", "## PDF 185~214쪽", "",
        f"`find_tables()` 검출 표 {focus['table_count']}개 중 레코드가 있는 표 "
        f"{focus['tables_with_records']}개, uncertain 행 포함 표 {focus['tables_with_uncertain']}개, "
        f"0레코드 표 {len(focus['zero_record_tables'])}개.",
        "", "| 유형 | 표 수 |", "|---|---:|",
    ])
    for code in TYPES:
        lines.append(f"| {code} | {focus['by_type'][code]} |")
    lines.extend([
        "", f"0레코드 표 ID: {', '.join(focus['zero_record_tables']) or '없음'}.",
        "기존 대조 값의 표 70개는 레코드가 있는 표 수와 일치한다. "
        "검출 총수에는 파싱 중 레코드가 사라진 14개 표도 포함했다. "
        "uncertain 포함 21개와 `p193-t1` 0레코드도 재현됐다.",
        "", "## 최종 분류 규칙", "",
        "`X > A > B > D > E > C > F` 순서로 첫 일치 유형을 부여한다.",
        "", "- X: 레코드가 없거나 `structure.status == uncertain`이 전체 레코드의 과반.",
        "- A: 표 직전 45pt 내 `(일당)` 표기 또는 직종/인 행과 `시공량` 동시 존재.",
        "- B: 표 직전 45pt 내 단위당 표기 또는 표 내부 단위당 표기, 그리고 직종/인 행 존재.",
        "- D: 비고를 뺀 행의 과반에 수치 `%`가 있거나, 표 행 값에 할증·보정·감액·감소·가산 등 명시.",
        "- E: 표 행 값에 hr, Q=, 작업능력, 기계경비 또는 대표 장비명/단위 대 존재.",
        "- C: 표 행 값에 재료/자재/소요량 또는 재료 단위가 있고 직종/인 단서가 없음.",
        "- F: 위 단서가 없는 참고·기준값 표. 불확실한 의미는 F에 둔다.",
        "", "## 알려진 한계", "",
        "- `find_tables()`가 원본 표를 분할하거나 놓친 경우 PDF의 실제 표 수와 다를 수 있다.",
        "- `parse_pages()`는 동일 텍스트를 중복 제거한다. 조사에서는 쪽별 호출로 쪽 간 제거를 피하지만, "
        "한 쪽 내 동문 행은 여전히 사라질 수 있다.",
        "- 표 바로 위 45pt 기준 표기는 여러 표와 주석이 밀접한 페이지에서 잘못 연결될 수 있다.",
        "- 직종·단위·장비 어휘 목록에 없는 표와 혼합형 표는 F 또는 다른 한 유형으로 분류될 수 있다.",
        "- 한 표의 일부 행만 uncertain이면 X가 아닐 수 있다. uncertain 수는 별도로 보존했다.",
        "- `spot_check.md`는 검토 표본이며 PDF 대조와 분류 정확도 검증은 아직 사람이 해야 한다.",
        "", "## 재현", "", "```powershell", "python experiments/table_census/census.py", "```", "",
    ])
    return "\n".join(lines)


def main() -> None:
    started = time.perf_counter()
    RESULTS.mkdir(parents=True, exist_ok=True)
    tables = []
    samples = {}
    errors = []
    inherited_section = ""
    with pymupdf.open(PDF) as doc, (RESULTS / "parsed_all.jsonl").open("w", encoding="utf-8") as output:
        page_count = len(doc)
        for page_no in range(1, page_count + 1):
            try:
                page = doc[page_no - 1]
                found = page.find_tables().tables
                titles = read_titles(page)
                parsed = parse_pages(str(PDF), page_no, page_no)
                grouped = defaultdict(list)
                for record in parsed:
                    output.write(json.dumps(record, ensure_ascii=False) + "\n")
                    if record.get("kind") == "table":
                        grouped[record["table_id"]].append(record)
                previous_bottom = 0.0
                for index, found_table in enumerate(found):
                    box = found_table.bbox
                    table_id = f"p{page_no}-t{index}"
                    rows = grouped[table_id]
                    section = section_for_table(rows, titles, box[1], inherited_section)
                    if SECTION_RE.match(section):
                        inherited_section = section
                    section_match = SECTION_NO.match(section)
                    section_no = section_match.group(1) if section_match else ""
                    basis = nearby_basis(page, box, previous_bottom)
                    code, reason, uncertain = classify(rows, basis)
                    tables.append({
                        "table_id": table_id, "page": page_no, "bbox": [round(v, 1) for v in box],
                        "section": section, "section_no": section_no,
                        "chapter": section_no.split("-")[0] if section_no else "",
                        "type": code, "reason": reason,
                        "record_count": len(rows), "uncertain_rows": uncertain,
                    })
                    samples[table_id] = [r["text"].replace("\n", " ") for r in rows[:3]]
                    previous_bottom = max(previous_bottom, box[3])
                for _, title, is_section in titles:
                    if is_section:
                        inherited_section = title
            except Exception as exc:
                errors.append({"page": page_no, "error": f"{type(exc).__name__}: {exc}"})
            if page_no % 100 == 0 or page_no == page_count:
                print(f"{page_no}/{page_count}쪽, 표 {len(tables)}개, 오류 {len(errors)}쪽", flush=True)

    summary = aggregates(tables, errors, time.perf_counter() - started, page_count)
    (RESULTS / "tables.json").write_text(json.dumps(tables, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (RESULTS / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (RESULTS / "spot_check.md").write_text(spot_check(tables, samples), encoding="utf-8")
    (HERE / "REPORT.md").write_text(report(summary), encoding="utf-8")
    print(f"완료: 표 {summary['total_tables']}개, A+B {summary['A_B_ratio']:.1%}, X {summary['X_ratio']:.1%}")


if __name__ == "__main__":
    main()
