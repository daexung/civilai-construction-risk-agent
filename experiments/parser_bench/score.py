"""5표 정답으로 파서 결과를 두 층으로 채점한다.

층 A — 원시 표 구조: 파서가 준 셀·병합 범위를 그대로 읽는다. 레코드 조립 로직을 거치지 않는다.
층 B — 최종 레코드·노무량: 운영 파이프라인의 clean_table()·table_to_records()를 그대로 import해
       레코드를 만든 뒤 채점한다. 격자를 넘기는 방식(어댑터) 두 가지를 같이 본다.
         extract: 병합 텍스트를 왼쪽 위 칸에만 둠(PyMuPDF extract() 규약, 현행 운영 방식)
         spanfill: 병합 범위 전체에 같은 텍스트를 채움
       미확정 해석(auto_score=false)은 채점하지 않는다.

실행(저장소 루트, 기존 .venv): python experiments/parser_bench/score.py <결과폴더이름> [...]
예: python experiments/parser_bench/score.py pymupdf docling_accurate
"""
import json
import re
import sys
from decimal import Decimal, InvalidOperation

from common import RESULTS, ROOT, grid_from_cells, lines, load_goldens, save_json, strip_brackets, ws

sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "evals"))
from check_estimate import check_case  # noqa: E402
from parse import clean_table, table_to_records  # noqa: E402

OLD_GOLDEN = ROOT / "evals/golden_parse.json"
ESTIMATE_GOLDEN = ROOT / "evals/golden_estimate.json"


# ───────────────────────── 층 A: 원시 표 구조 ─────────────────────────

def covers(cell, r=None, c=None) -> bool:
    return (r is None or cell["r0"] <= r < cell["r1"]) and (c is None or cell["c0"] <= c < cell["c1"])


def golden_body_texts(golden) -> set[str]:
    out = set()
    for ev in golden["expected_values"]:
        out |= {ws(v) for v in ev["row_key"].values()}
        if golden["scoring"]["orientation"] == "rows":
            out |= {ws(v) for v in ev["fields"].values()}
            out |= {ws(v) for v in ev.get("shared_fields", {}).values()}
        else:
            out |= {ws(v) for v in ev["fields"].values()}
    out.discard("")
    return out


def data_start(table, golden) -> int | None:
    """본문이 시작하는 행. 정답의 행 키나 값이 처음 나오는 행으로 정한다(파서 무관)."""
    scoring = golden["scoring"]
    if scoring["orientation"] == "header_is_key":
        targets = {ws(v) for ev in golden["expected_values"] for v in ev["fields"].values()}
    else:
        targets = golden_body_texts(golden)
    for cell in sorted(table["cells"], key=lambda c: c["r0"]):
        if ws(cell["text"]) in targets or any(ws(line) in targets for line in lines(cell["text"])):
            return cell["r0"]
    return None


def header_texts(table, start, col) -> list[str]:
    return [ws(c["text"]) for c in table["cells"] if c["r0"] < start and covers(c, c=col)]


def column_matches(table, start, col, components) -> bool:
    texts = header_texts(table, start, col)
    return all(any(ws(comp) in t for t in texts) for comp in components)


def rows_with_keys(table, start, keys) -> list[int]:
    rows = []
    for r in range(start, table["n_rows"]):
        if all(any(covers(c, r=r) and ws(c["text"]) == ws(k) for c in table["cells"]) for k in keys):
            rows.append(r)
    return rows


def span_basis_of(golden, value) -> str:
    for cell in golden["source_table"]["cells"]:
        if (cell.get("rs", 1) > 1 or cell.get("cs", 1) > 1) and ws(cell.get("text")) == ws(value):
            return cell.get("span_basis", "unknown")
    return "unknown"


def score_relations(table, golden, start) -> list[dict]:
    scoring = golden["scoring"]
    results = []

    if scoring["orientation"] == "header_is_key":
        for ev in golden["expected_values"]:
            key = next(iter(ev["row_key"].values()))
            value = ev["fields"][scoring["value_field"]]
            found = any(
                ws(v["text"]) == ws(value) and any(
                    h["r0"] < v["r0"] and ws(h["text"]) == ws(key)
                    and max(h["c0"], v["c0"]) < min(h["c1"], v["c1"])
                    for h in table["cells"])
                for v in table["cells"])
            results.append({"row": key, "field": scoring["value_field"], "value": value,
                            "kind": "own", "found": found})
        return results

    for ev in golden["expected_values"]:
        keys = list(ev["row_key"].values())
        rows = rows_with_keys(table, start, keys)
        items = [(p, v, "own") for p, v in ev["fields"].items()]
        items += [(p, v, "shared") for p, v in ev.get("shared_fields", {}).items()]
        for path, value, kind in items:
            components = scoring["header_paths"][path]
            found = any(
                covers(c, r=r) and ws(c["text"]) == ws(value)
                and any(column_matches(table, start, col, components) for col in range(c["c0"], c["c1"]))
                for r in rows for c in table["cells"])
            item = {"row": " / ".join(keys), "field": path, "value": value, "kind": kind, "found": found}
            if kind == "shared":
                item["span_basis"] = span_basis_of(golden, value)
            if not rows:
                item["reason"] = "행 키를 가진 행이 없음(행 분리 실패 등)"
            results.append(item)
    return results


def score_row_split(table, golden, start) -> list[dict]:
    if golden["scoring"]["orientation"] != "rows":
        return []
    last_key = golden["scoring"]["row_key_fields"][-1]
    out = []
    for ev in golden["expected_values"]:
        key = ev["row_key"][last_key]
        whole = any(c["r0"] >= start and ws(c["text"]) == ws(key) for c in table["cells"])
        out.append({"key": key, "separate_cell": whole})
    return out


def golden_texts(golden) -> list[str]:
    texts = []
    for cell in golden["source_table"]["cells"]:
        if "text" in cell:
            texts.append(cell["text"])
        texts += cell.get("text_lines", [])
    for nested in golden["source_table"].get("nested_tables", []):
        texts += nested["columns"]
        for row in nested["rows"]:
            texts += row
    return [t for t in texts if ws(t)]


def found_as_token_run(golden_ws: str, cell_text: str) -> bool:
    """정답 문자열이 칸 안의 연속된 어절(공백·줄바꿈으로 나뉜 조각)을 이어 붙인 것과 정확히 같은가.

    부분 문자열 판정은 '3', '인' 같은 짧은 정답이 '13'·'인력'에서도 걸려 보존으로 잘못 세진다.
    어절 경계에 맞춰서만 인정한다. 파서마다 합쳐진 칸을 줄바꿈으로 잇기도 하고(PyMuPDF·ODL)
    공백으로 잇기도 해서(Docling) 줄이 아니라 어절 단위로 본다.
    """
    tokens = [t for t in re.split(r"\s+", strip_brackets(cell_text)) if t]
    for i in range(len(tokens)):
        acc = ""
        for j in range(i, len(tokens)):
            acc += tokens[j]
            if acc == golden_ws:
                return True
            if len(acc) >= len(golden_ws):
                break
    return False


NUMERIC_TEXT = re.compile(r"^[\d.,%]+$")


def segment(text: str, pieces: set[str]) -> list[str] | None:
    """text를 원문 문자열 2개 이상으로 순서대로 나눌 수 있으면 그 조각 목록 (예: '인3' → ['인', '3'])."""
    back = [None] * (len(text) + 1)
    back[0] = -1
    for i in range(len(text)):
        if back[i] is None:
            continue
        for piece in pieces:
            end = i + len(piece)
            if piece and end <= len(text) and back[end] is None and text.startswith(piece, i):
                back[end] = i
    if back[len(text)] is None:
        return None
    out, end = [], len(text)
    while end > 0:
        start = back[end]
        out.append(text[start:end])
        end = start
    out.reverse()
    return out if len(out) >= 2 else None


def splits_into(text: str, pieces: set[str]) -> bool:
    """text가 원문 문자열 2개 이상을 순서대로 이어 붙인 것인가 (예: '구분내용' = '구분' + '내용')."""
    return text not in pieces and segment(text, pieces) is not None


def score_text(table, golden) -> dict:
    gold = golden_texts(golden)
    gold_ws = {ws(t) for t in gold}
    pred_whole = {ws(c["text"]) for c in table["cells"]}

    # 띄어쓰기 없이 붙은 어절(예: Docling '인3')은 원문 칸으로 정확히 분해될 때만 조각을 인정한다.
    # 숫자만으로 된 어절은 분해하지 않는다('13'을 '1'+'3'으로 인정하지 않기 위함)
    fused_pieces = set()
    for c in table["cells"]:
        for tok in re.split(r"\s+", strip_brackets(c["text"])):
            if tok and not NUMERIC_TEXT.match(tok):
                fused_pieces |= set(segment(tok, gold_ws) or [])
    # 같은 행의 칸을 왼쪽부터 이은 문자열. 한 문장이 여러 칸으로 쪼개진 경우를 복원해 본다
    row_joined = {}
    for c in sorted(table["cells"], key=lambda c: (c["r0"], c["c0"])):
        row_joined.setdefault(c["r0"], []).append(c["text"])

    preserved = {"whole": 0, "inside_merged_cell": 0, "split_across_cells": 0, "missing": []}
    for text in gold:
        t = ws(text)
        if t in pred_whole:
            preserved["whole"] += 1
        elif any(found_as_token_run(t, c["text"]) for c in table["cells"]) or t in fused_pieces:
            # 다른 원문 칸과 한 칸에 합쳐졌거나, 합쳐진 칸 안에서 줄바꿈으로 나뉜 경우. 글자는 보존됨
            preserved["inside_merged_cell"] += 1
        elif any(found_as_token_run(t, " ".join(texts)) for texts in row_joined.values()):
            preserved["split_across_cells"] += 1
        else:
            preserved["missing"].append(text)

    novel, merged = [], 0
    for cell in table["cells"]:
        if not ws(cell["text"]) or ws(cell["text"]) in gold_ws:
            continue
        parts = [ws(strip_brackets(line)) for line in lines(cell["text"])]
        parts = [p for p in parts if p]
        if parts and all(p in gold_ws for p in parts):
            merged += 1
            continue
        for p in parts:
            if p in gold_ws:
                continue
            # 숫자는 원문 칸과 정확히 같거나, 원문 문장 안의 숫자(예: '20% 가산')일 때만 인정한다.
            # 0.013 ↔ 0.13 같은 오독을 놓치지 않기 위함
            if NUMERIC_TEXT.match(p):
                if not any(len(g) >= 10 and re.search(rf"(?<![\d.]){re.escape(p)}(?![\d])", g) for g in gold_ws):
                    novel.append(p)
                continue
            # 원문 칸 여러 개가 한 줄로 붙은 것(예: '인3인3' = 인+3+인+3, '구분내용' = 구분+내용)은 합쳐짐
            if splits_into(p, gold_ws):
                continue
            # 좁은 칸에서 잘린 원문 조각
            text_gold = [g for g in gold_ws if not NUMERIC_TEXT.match(g)]
            if any(len(g) >= 2 and p in g for g in text_gold) or any(len(g) >= 3 and g in p for g in text_gold):
                continue
            # 남는 것: 원문에 없는 글자 조합(칸끼리 글자가 뒤섞임) 또는 표 밖 글자 유입
            novel.append(p)
    return {"golden_texts": len(gold), **preserved,
            "cells_merging_several_golden_cells": merged, "novel_text": novel}


def score_groupings(table, golden, start) -> list[dict]:
    out = []
    for grp in golden.get("expected_groupings", []):
        cols = [c for c in range(table["n_cols"]) if column_matches(table, start, c, [grp["column_header"]])]
        scope = next(iter(grp["scope"].values()))
        scope_rows = [r for r in range(start, table["n_rows"])
                      if any(covers(c, r=r) and ws(c["text"]) == ws(scope) for c in table["cells"])]
        member_rows = []
        if scope_rows:
            for member in grp["members"]:
                for r in range(scope_rows[0], table["n_rows"]):
                    if any(covers(c, r=r) and (ws(c["text"]) == ws(member)
                                                or ws(member) in {ws(line) for line in lines(c["text"])})
                           for c in table["cells"]):
                        member_rows.append(r)
                        break
        member_set = set(member_rows)
        value_cells = [
            c for c in table["cells"]
            if any(c["c0"] <= col < c["c1"] for col in cols)
            and any(covers(c, r=r) for r in member_set)
            and (ws(strip_brackets(c["text"])) == ws(grp["value"])
                 or ws(grp["value"]) in {ws(strip_brackets(line)) for line in lines(c["text"])})
        ]
        present = bool(value_cells)
        once = len(value_cells) == 1
        # 멤버가 서로 다른 행으로 나뉘었는지는 row_split에서 따로 본다. 여기서는 값 하나가 멤버 전부와
        # 같은 행 범위에 놓였는지만 본다(행 분리 실패로 이중 감점하지 않기 위함).
        covers_all = (once and len(member_rows) == len(grp["members"])
                      and all(covers(value_cells[0], r=r) for r in member_set))
        out.append({
            "group": grp["group"], "column_found": bool(cols), "member_rows": member_rows,
            "value_present": present, "value_once": once, "covers_all_members": covers_all,
            "bracket_glyphs_in_text": any(ch in c["text"] for c in value_cells for ch in "⌈⌉⌊⌋"),
            "pass": present and once and covers_all,
        })
    return out


EMPTY_TABLE = {"n_rows": 0, "n_cols": 0, "cells": []}


def score_layer_a(table, golden) -> dict:
    # 표를 못 찾았거나 본문을 못 찾아도 문항을 분모에서 빼지 않는다. 빈 표로 채점해 전부 실패로 센다.
    table = table or EMPTY_TABLE
    start = data_start(table, golden)
    note = None
    if start is None:
        start = 0
        note = "표를 찾지 못함" if not table["cells"] else "본문 행을 찾지 못함"
    return {
        "note": note,
        "data_start_row": start,
        "relations": score_relations(table, golden, start),
        "row_split": score_row_split(table, golden, start),
        "groupings": score_groupings(table, golden, start),
        "text": score_text(table, golden),
    }


# ───────────────────────── 층 B: 최종 레코드·노무량 ─────────────────────────

def parts_of(record) -> list[str]:
    return [p.strip() for p in record["text"].split("|")]


def part_is(part, value, components=()) -> bool:
    """레코드 조각이 '열이름 값' 또는 '값' 형태로 value를 담는지. 숫자 경계를 지킨다(3 ≠ 13)."""
    p, v = ws(part), ws(value)
    if not p.endswith(v):
        return False
    prefix = p[: len(p) - len(v)]
    if not components:
        return prefix == "" or not re.search(r"[\d.]$", prefix)
    return bool(prefix) and not re.search(r"[\d.]$", prefix) and all(ws(c) in prefix for c in components)


def records_for(records, keys) -> list[dict]:
    return [r for r in records if all(any(part_is(p, k) for p in parts_of(r)[1:]) for k in keys)]


def part_is_relaxed(part, value, components=()) -> bool:
    """part_is와 같되 괄호 글리프를 지우고 본다. 표기 차이(형식)를 값 오류와 가르기 위한 느슨한 판정."""
    return part_is(strip_brackets(part), strip_brackets(value), components)


def records_for_relaxed(records, keys) -> list[dict]:
    return [r for r in records if all(any(part_is_relaxed(p, k) for p in parts_of(r)[1:]) for k in keys)]


def classify_failure(records, keys, value, components) -> tuple[str, str]:
    """엄격 판정에서 실패한 기대값의 원인을 가른다.

    형식: 행·열·값은 맞고 표기만 다름(괄호 글리프, 자간, 열 이름 앞뒤 표기)
    값 오류: 해당 행의 해당 열에 다른 값이 있음
    구조: 행을 못 찾거나 여러 개이거나, 해당 열이 없거나, 값이 없음
    """
    matched = records_for_relaxed(records, keys)
    if len(matched) != 1:
        return "구조", f"행 키에 맞는 레코드 {len(matched)}건"
    parts = parts_of(matched[0])[1:]
    if any(part_is_relaxed(p, value, components) for p in parts):
        return "형식", "괄호·공백을 무시하면 일치"
    column = [p for p in parts if components and all(ws(c) in ws(strip_brackets(p)) for c in components)]
    if column:
        return "값 오류", f"같은 열에 다른 값: {column[:2]}"
    return "구조", "해당 열이 레코드에 없음"


def score_expected(records, golden) -> list[dict]:
    scoring = golden["scoring"]
    skip = set(scoring.get("record_skip_values", []))
    out = []
    for ev in golden["expected_values"]:
        if scoring["orientation"] == "header_is_key":
            key = next(iter(ev["row_key"].values()))
            value = ev["fields"][scoring["value_field"]]
            found = any(part_is(p, value, [key]) for r in records for p in parts_of(r)[1:])
            item = {"row": key, "field": scoring["value_field"], "value": value, "kind": "own", "found": found}
            if not found:
                if any(part_is_relaxed(p, value, [key]) for r in records for p in parts_of(r)[1:]):
                    item["failure_type"], item["failure_detail"] = "형식", "괄호·공백을 무시하면 일치"
                elif any(ws(key) in ws(p) for r in records for p in parts_of(r)[1:]):
                    item["failure_type"], item["failure_detail"] = "값 오류", "머리글은 있으나 값이 다름"
                else:
                    item["failure_type"], item["failure_detail"] = "구조", "머리글·값 없음"
            out.append(item)
            continue
        keys = list(ev["row_key"].values())
        matched = records_for(records, keys)
        items = [(p, v, "own") for p, v in ev["fields"].items()]
        items += [(p, v, "shared") for p, v in ev.get("shared_fields", {}).items()]
        for path, value, kind in items:
            if value in skip:
                continue
            components = scoring["header_paths"][path]
            found = len(matched) == 1 and any(part_is(p, value, components) for p in parts_of(matched[0])[1:])
            item = {"row": " / ".join(keys), "field": path, "value": value, "kind": kind,
                    "found": found, "matching_records": len(matched)}
            if kind == "shared":
                item["span_basis"] = span_basis_of(golden, value)
            if not found:
                item["failure_type"], item["failure_detail"] = classify_failure(records, keys, value, components)
            out.append(item)
    return out


def score_interpretations(records, golden) -> list[dict]:
    out = []
    for interp in golden["interpretations"]:
        if not interp.get("auto_score"):
            continue
        check = interp["check"]
        if check["type"] != "count_once_per_group":
            continue
        for grp in golden["expected_groupings"]:
            if grp["group"] not in check["groups"]:
                continue
            scope = next(iter(grp["scope"].values()))
            in_scope = [r for r in records if any(part_is(p, scope) for p in parts_of(r)[1:])]
            carrying = [r for r in in_scope
                        if any(part_is(p, grp["value"], [grp["column_header"]]) for p in parts_of(r)[1:])]
            out.append({"interpretation": interp["id"], "group": grp["group"],
                        "records_with_value": len(carrying), "pass": len(carrying) == 1})
    return out


def score_arithmetic(records, golden) -> list[dict]:
    out = []
    scoring = golden["scoring"]
    for rule in scoring.get("arithmetic_checks", []):
        for ev in golden["expected_values"]:
            keys = list(ev["row_key"].values())
            matched = records_for(records, keys)
            if len(matched) != 1:
                out.append({"row": " / ".join(keys), "pass": False, "reason": f"레코드 {len(matched)}건"})
                continue
            values = {}
            for field in rule["sum_of"] + [rule["equals"]]:
                comps = scoring["header_paths"][field]
                for p in parts_of(matched[0])[1:]:
                    m = re.fullmatch(r"(.*?)([\d.]+)", ws(p))
                    if m and part_is(p, m.group(2), comps):
                        values[field] = m.group(2)
            try:
                ok = (len(values) == len(rule["sum_of"]) + 1 and
                      sum(Decimal(values[f]) for f in rule["sum_of"]) == Decimal(values[rule["equals"]]))
            except InvalidOperation:
                ok = False
            out.append({"row": " / ".join(keys), "values": values, "pass": ok})
    return out


def score_old_golden(records_by_table, goldens) -> list[dict]:
    """기존 golden_parse.json 중 5표에 해당하는 표 케이스만, 기존 채점 규칙(부분 문자열) 그대로 적용."""
    old = json.loads(OLD_GOLDEN.read_text(encoding="utf-8"))
    groups = {}
    for tid, golden in goldens.items():
        section_no = re.match(r"^(\d+-\d+-\d+)", golden["source"]["section"]).group(1)
        groups.setdefault((golden["source"]["pdf_page"], section_no), []).append(tid)
    out = []
    for case in old["cases"]:
        key = (case["page"], case["must_contain"][0])
        if case["id"].startswith("줄글") or key not in groups:
            continue
        texts = [r["text"] for tid in groups[key] for r in records_by_table.get(tid, [])]
        hits = [t for t in texts if all(w in t for w in case["must_contain"])]
        ok = len(hits) == case.get("expect_count", 1)
        banned = [w for w in case.get("must_not_contain", []) if any(w in t for t in hits)]
        item = {"id": case["id"], "pass": ok and not banned, "hits": len(hits), "banned": banned}
        if not item["pass"]:
            # 괄호 글리프를 지우고 공백을 무시해도 실패하는지 본다. 통과하면 표기(형식) 문제
            relaxed = [strip_brackets(t) for t in texts]
            r_hits = [t for t in relaxed if all(ws(w) in ws(t) for w in case["must_contain"])]
            r_banned = [w for w in case.get("must_not_contain", [])
                        if strip_brackets(w) and any(ws(w) in ws(t) for t in r_hits)]
            if len(r_hits) == case.get("expect_count", 1) and not r_banned:
                item["failure_type"] = "형식"
                item["failure_detail"] = "괄호 글리프를 지우고 공백을 무시하면 통과" if banned else "공백을 무시하면 통과"
            else:
                item["failure_type"] = "값·구조"
                item["failure_detail"] = f"느슨한 판정에서도 {len(r_hits)}건 (필요 {case.get('expect_count', 1)}건)"
        out.append(item)
    return out


def score_estimate(records, golden) -> dict:
    """기존 노무량 사례를 기존 check_case()로 그대로 채점한다.

    '(일당)' 기준 표기는 표 밖 텍스트라 표 단독 추출에는 없다. 정답 파일(T1 source.basis_marker)의
    값을 설명 레코드 하나로 주입하고, 주입했다는 사실을 결과에 남긴다.
    """
    case = json.loads(ESTIMATE_GOLDEN.read_text(encoding="utf-8"))
    injected = {"text": f"{golden['source']['section']} | 설명 | {golden['source']['basis_marker']}",
                "section": golden["source"]["section"], "page": golden["source"]["pdf_page"]}
    try:
        result = check_case(records + [injected], case)
        return {"pass": True, "person_days": {k: str(v) for k, v in result.items()},
                "basis_injected_from_golden": injected["text"]}
    except (ValueError, KeyError, InvalidOperation) as exc:
        relaxed = relaxed_estimate(records, case)
        if relaxed["computed"] and relaxed["matches_expected"]:
            failure_type = "형식"
        elif relaxed["computed"]:
            failure_type = "값 오류"
        else:
            failure_type = "구조"
        return {"pass": False, "reason": str(exc), "failure_type": failure_type, "relaxed": relaxed,
                "basis_injected_from_golden": injected["text"]}


def relaxed_estimate(records, case) -> dict:
    """괄호·공백을 무시하고 같은 노무량을 계산해 본다. 기존 검사기가 형식 때문에 실패했는지 가르기 위함."""
    src, inp = case["source"], case["input"]
    scoped = [r for r in records if r["page"] == src["pdf_page"] and r["section"] == src["section"]]
    volume = Decimal(inp["volume_m3"])
    out, computed, ok = {}, True, True
    for trade, expected in case["expected_person_days"].items():
        matched = records_for_relaxed(scoped, [inp["method"], trade])
        if len(matched) != 1:
            out[trade] = f"레코드 {len(matched)}건"
            computed = False
            continue
        values = {}
        for name, comps in (("crew", ["수량"]), ("output", ["시공량", inp["structure"]])):
            for p in parts_of(matched[0])[1:]:
                m = re.fullmatch(r"(.*?)([\d.]+)", ws(strip_brackets(p)))
                if m and part_is_relaxed(p, m.group(2), comps):
                    values[name] = Decimal(m.group(2))
        if len(values) != 2:
            out[trade] = f"값을 못 찾음 {values}"
            computed = False
            continue
        days = volume / values["output"] * values["crew"]
        out[trade] = str(days)
        ok = ok and days == Decimal(expected)
    return {"computed": computed, "matches_expected": computed and ok, "person_days": out}


def build_records(table, golden, adapter) -> tuple[list[dict], str | None]:
    if adapter == "extract":
        grid = table.get("extract") or grid_from_cells(table, fill_spans=False)
    else:
        grid = grid_from_cells(table, fill_spans=True)
    try:
        records = table_to_records(clean_table(grid), golden["source"]["section"], golden["source"]["pdf_page"])
        return records, None
    except Exception as exc:  # 조립 로직이 이 격자를 처리하지 못한 것 자체가 결과다
        return [], f"{type(exc).__name__}: {exc}"


def score_layer_b(tables, goldens, adapter) -> dict:
    per_table, records_by_table = {}, {}
    for tid, golden in goldens.items():
        table = tables.get(tid)
        if table:
            records, error = build_records(table, golden, adapter)
        else:
            records, error = [], "표를 찾지 못함"
        records_by_table[tid] = records
        per_table[tid] = {
            "records": [r["text"] for r in records],
            "assembly_error": error,
            "expected": score_expected(records, golden),
            "interpretations": score_interpretations(records, golden),
            "arithmetic": score_arithmetic(records, golden),
        }
    return {
        "per_table": per_table,
        "old_golden": score_old_golden(records_by_table, goldens),
        "estimate": score_estimate(records_by_table.get("T1", []), goldens["T1"]),
    }


# ───────────────────────── 집계 ─────────────────────────

def ratio(items, key="found") -> list[int]:
    return [sum(1 for i in items if i[key]), len(items)]


def summarize(a_layer, b_layers) -> dict:
    rel = [r for t in a_layer.values() for r in t.get("relations", [])]
    summary = {
        "A": {
            "relations_own": ratio([r for r in rel if r["kind"] == "own"]),
            "relations_shared": ratio([r for r in rel if r["kind"] == "shared"]),
            "relations_shared_by_basis": {
                b: ratio([r for r in rel if r["kind"] == "shared" and r.get("span_basis") == b])
                for b in ("ruled", "unruled", "mixed")},
            "bracket_groups": ratio([g for t in a_layer.values() for g in t.get("groupings", [])], "pass"),
            "row_split": ratio([s for t in a_layer.values() for s in t.get("row_split", [])], "separate_cell"),
            "text_whole": [sum(t["text"]["whole"] for t in a_layer.values() if "text" in t),
                           sum(t["text"]["golden_texts"] for t in a_layer.values() if "text" in t)],
            "text_inside_merged": sum(t["text"]["inside_merged_cell"] for t in a_layer.values() if "text" in t),
            "text_split_across_cells": sum(t["text"]["split_across_cells"] for t in a_layer.values() if "text" in t),
            "text_missing": sum(len(t["text"]["missing"]) for t in a_layer.values() if "text" in t),
            "novel_text": [n for t in a_layer.values() if "text" in t for n in t["text"]["novel_text"]],
        },
        "B": {},
    }
    for adapter, b in b_layers.items():
        exp = [e for t in b["per_table"].values() for e in t.get("expected", [])]
        failed = [e for e in exp if not e["found"]]
        old_failed = [c for c in b["old_golden"] if not c["pass"]]
        summary["B"][adapter] = {
            "old_golden_subset": ratio(b["old_golden"], "pass"),
            "old_golden_failures_by_type": {t: sum(1 for c in old_failed if c.get("failure_type") == t)
                                            for t in ("형식", "값·구조")},
            "expected_own": ratio([e for e in exp if e["kind"] == "own"]),
            "expected_shared": ratio([e for e in exp if e["kind"] == "shared"]),
            "expected_failures_by_type": {t: sum(1 for e in failed if e.get("failure_type") == t)
                                          for t in ("형식", "값 오류", "구조")},
            "estimate_failure_type": b["estimate"].get("failure_type"),
            "interpretation_checks": ratio([i for t in b["per_table"].values() for i in t.get("interpretations", [])], "pass"),
            "arithmetic": ratio([x for t in b["per_table"].values() for x in t.get("arithmetic", [])], "pass"),
            "estimate": b["estimate"]["pass"],
            "estimate_detail": b["estimate"].get("person_days") or b["estimate"].get("reason"),
            "assembly_errors": {tid: t["assembly_error"] for tid, t in b["per_table"].items() if t.get("assembly_error")},
        }
    return summary


def main() -> int:
    runs = sys.argv[1:] or ["pymupdf"]
    goldens = load_goldens()
    all_scores = {}
    for run in runs:
        data = json.loads((RESULTS / run / "tables.json").read_text(encoding="utf-8"))
        tables = data["tables"]
        a_layer = {tid: score_layer_a(tables.get(tid), g) for tid, g in goldens.items()}
        b_layers = {adapter: score_layer_b(tables, goldens, adapter) for adapter in ("extract", "spanfill")}
        scores = {"run": run, "parser": data["parser"], "version": data.get("version"),
                  "config": data.get("config"), "elapsed_sec": data.get("elapsed_sec"),
                  "summary": summarize(a_layer, b_layers), "A": a_layer, "B": b_layers}
        save_json(RESULTS / run / "scores.json", scores)
        all_scores[run] = scores["summary"]
        print(f"\n===== {run} ({data['parser']} {data.get('version', '')}) =====")
        print(json.dumps(scores["summary"], ensure_ascii=False, indent=1))
    save_json(RESULTS / "summary.json", all_scores)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
