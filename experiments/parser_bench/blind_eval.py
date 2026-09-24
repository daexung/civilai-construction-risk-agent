"""무작위 20쪽 맹검 평가: 쪽을 먼저 고정하고, 원문 이미지로 정답 표 목록을 만든 뒤 파서를 비교한다.

단계 (순서를 지킨다. 파서 결과는 정답 목록을 다 만든 뒤에만 연다):
  select  : 쪽 고정 → results/blind20/selection.json
  render  : 쪽 이미지 렌더링(세로 좌표 눈금 포함) → results/blind20/pages/pNNN.png   ※ 파서 미사용
  (사람/Claude가 이미지를 보고 results/blind20/ground_truth.json 작성)
  (extract_pymupdf.py / extract_odl.py --source full --pages ... 로 추출)
  crops   : 정답 표마다 원문 조각 이미지 → results/blind20/crops/

선정 규칙:
  1~982쪽에서 파일럿 장(185~214쪽)과 기존 실패 사례 쪽(180·396·500·885)을 뺀다.
  남은 쪽을 20구간으로 나눠 구간마다 random.Random(SEED)로 1쪽씩 뽑는다.
"""
import json
import re
import unicodedata
import random
import sys

import pymupdf

from common import PDF, RESULTS, ROOT, grid_from_cells, save_json, strip_brackets, ws

SEED = "blind20-2026-09-24"
N = 20
TOTAL_PAGES = 982
EXCLUDE = set(range(185, 215)) | {180, 396, 500, 885}
OUT = RESULTS / "blind20"


def select() -> list[int]:
    allowed = [p for p in range(1, TOTAL_PAGES + 1) if p not in EXCLUDE]
    size = len(allowed) / N
    rng = random.Random(SEED)
    pages = [rng.choice(allowed[int(i * size): int((i + 1) * size)]) for i in range(N)]
    save_json(OUT / "selection.json", {
        "rule": "1~982쪽에서 185~214쪽과 180·396·500·885쪽을 빼고 20구간으로 나눠 구간마다 1쪽",
        "seed": SEED,
        "excluded_known_failures": [180, 396, 500, 885],
        "pages": pages,
    })
    return pages


def render() -> None:
    pages = json.loads((OUT / "selection.json").read_text(encoding="utf-8"))["pages"]
    (OUT / "pages").mkdir(parents=True, exist_ok=True)
    with pymupdf.open(PDF) as doc:
        for p in pages:
            page = doc[p - 1]
            # 원문을 가리지 않도록 왼쪽 여백에만 50pt 간격 눈금을 그린 사본을 렌더링한다(원본 PDF는 수정하지 않음)
            tmp = pymupdf.open()
            tmp.insert_pdf(doc, from_page=p - 1, to_page=p - 1)
            tp = tmp[0]
            for y in range(0, int(page.rect.height), 50):
                tp.draw_line((0, y), (40, y), color=(1, 0, 0), width=0.6)
                tp.insert_text((2, y - 1), str(y), fontsize=7, color=(1, 0, 0))
            tp.get_pixmap(dpi=110).save(OUT / "pages" / f"p{p}.png")
            tmp.close()
    print(f"{len(pages)}쪽 렌더링 → {OUT / 'pages'}")


def crops() -> None:
    gt = json.loads((OUT / "ground_truth.json").read_text(encoding="utf-8"))
    (OUT / "crops").mkdir(parents=True, exist_ok=True)
    with pymupdf.open(PDF) as doc:
        for t in gt["tables"]:
            page = doc[t["page"] - 1]
            y0, y1 = t["bbox_pt"][1], t["bbox_pt"][3]
            clip = pymupdf.Rect(0, max(0, y0 - 8), page.rect.width, min(page.rect.height, y1 + 8))
            page.get_pixmap(clip=clip, dpi=150).save(OUT / "crops" / f"{t['id']}.png")
    print(f"표 {len(gt['tables'])}개 원문 조각 → {OUT / 'crops'}")


# ---------------- 채점 ----------------
# 정답 fact = [행 식별 글자들, [[열 힌트, 값], ...]]
# 한 레코드(운영 조립 로직 결과) 안에 행 식별 글자와 모든 (열 힌트, 값)이 함께 있으면 통과.
# 표기 차이(아래첨자·㎥·물결표·괄호 글리프·공백)는 여기서 흡수하고, 두 파서의 표기 차이는 셀 단위로 따로 센다.

RUNS = {"pymupdf": "blind20_pymupdf", "odl_local": "blind20_odl_local"}
NUMERIC_TOKEN = re.compile(r"^[\d.,~\-]+$")


def norm(text) -> str:
    text = unicodedata.normalize("NFKC", strip_brackets(text or ""))
    return re.sub(r"[∼～〜]", "~", text)


def nws(text) -> str:
    return ws(norm(text))


def row_token_in(token: str, record_text: str) -> bool:
    if NUMERIC_TOKEN.match(token):
        return re.search(rf"(?<![\w.,~]){re.escape(norm(token))}(?![\w.,~])", norm(record_text)) is not None
    return nws(token) in nws(record_text)


def value_in_field(hint: str, value: str, field: str) -> bool:
    if nws(hint) not in nws(field):
        return False
    tokens = norm(field).split()
    v = nws(value)
    if NUMERIC_TOKEN.match(v) or re.match(r"^\([\d.]+\)$", v):
        # 숫자는 칸의 마지막 낱말과 정확히 같아야 한다 ('0.2'가 '0.20'에 붙는 오판 방지)
        return bool(tokens) and tokens[-1] == v
    if len(v) <= 4:
        # 짧은 글자(단위 '인' 등)는 낱말 단위로 비교. 열 힌트가 있으면 '1대용W(...)'처럼 앞부분 일치도 인정
        return any(tok == v or (hint and tok.startswith(v)) for tok in tokens)
    return v in nws(field) and nws(field) != nws(hint)


def virtual_rows(grid) -> list[list[str]]:
    """원시 격자의 한 행에 줄바꿈으로 쌓인 값을 줄 번호로 나눈다.

    줄 수가 같은 칸은 i번째 줄끼리 짝짓고, 줄 수가 다른 칸은 통째로 모든 줄에 붙인다.
    (줄바꿈된 긴 라벨이면 맞는 결과, 여러 행 라벨이 쌓인 칸이면 exclusive_ok에서 걸린다.)
    첫 열이 비면 위 행 라벨을 이어받는다(운영 clean_table과 같은 규칙).
    """
    out = []
    for row in grid:
        stacks = [(c or "").split("\n") for c in row]
        depth = max(len(s) for s in stacks)
        for i in range(depth):
            vrow = [s[i] if len(s) == depth else " ".join(s) for s in stacks]
            if out and not ws(vrow[0]):
                vrow[0] = out[-1][0]
            out.append(vrow)
    return out


def aligned_values(grid) -> list[list[str]]:
    """virtual_rows와 같은 순서로, 값으로 인정할 칸만 남긴다.

    줄 수가 행 깊이와 같거나 한 줄짜리인 칸만 값으로 인정한다. 줄 수가 다른 여러 줄 칸은
    어느 값이 어느 행인지 모르므로 빈 칸으로 둔다(835쪽: 직종 5줄·값 4줄이 한 칸에 쌓인 경우).
    """
    out = []
    for row in grid:
        stacks = [(c or "").split("\n") for c in row]
        depth = max(len(s) for s in stacks)
        for i in range(depth):
            out.append([s[i] if len(s) == depth else (s[0] if len(s) == 1 else "") for s in stacks])
    return out


def exclusive_ok(fact, fields: list[str], others: list[str]) -> bool:
    """이 행의 라벨이 든 칸에 다른 행의 라벨까지 함께 붙어 있으면 실패(885쪽 유형).

    값·비고 칸은 보지 않는다('( )는 내업임' 같은 문구 오탐 방지).
    서로 부분 문자열인 라벨(현지측량/현지측량준비 등)은 구분하지 않는다.
    """
    label_text = " ".join(f for f in fields if any(row_token_in(t, f) for t in fact[0]))
    own = [nws(t) for t in fact[0]]
    for other in others:
        o = nws(other)
        if any(o in t or t in o for t in own):
            continue
        if row_token_in(other, label_text):
            return False
    return True


def other_row_tokens(fact, facts) -> list[str]:
    return sorted({tok for f in facts if f is not fact for tok in f[0]})


def raw_fact_ok(fact, grid, others) -> bool:
    """파서 층 검사: 열 이름을 쓰지 않고, 같은 (가상) 행 안에 행 라벨과 모든 값이 함께 있고 다른 행 라벨은 없는지 본다."""
    rows, cells = fact
    for vrow, vals in zip(virtual_rows(grid), aligned_values(grid)):
        joined = " | ".join(vrow)
        if (all(row_token_in(t, joined) for t in rows) and all(value_anywhere(v, vals) for _, v in cells)
                and exclusive_ok(fact, vrow, others)):
            return True
    return False


def fact_ok(fact, record_text: str) -> bool:
    rows, cells = fact
    if not all(row_token_in(t, record_text) for t in rows):
        return False
    fields = record_text.split(" | ")
    return all(any(value_in_field(h, v, f) for f in fields) for h, v in cells)


def value_anywhere(value: str, texts: list[str]) -> bool:
    return any(row_token_in(value, t) if NUMERIC_TOKEN.match(nws(value)) else nws(value) in nws(t) for t in texts)


def area(b):
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def inter(a, b):
    return area([max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])])


def load_tables(run, page):
    path = RESULTS / run / "raw" / f"p{page}_all_tables.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def score() -> None:
    sys.path.insert(0, str(ROOT / "pipeline"))
    from parse import clean_table, table_to_records
    from validate_pages import compare_pair

    def records(table, fill):
        try:
            return [r["text"] for r in table_to_records(clean_table(grid_from_cells(table, fill_spans=fill)), "S", 0)]
        except Exception as exc:
            return [f"조립 오류: {type(exc).__name__}: {exc}"]

    gt = json.loads((OUT / "ground_truth.json").read_text(encoding="utf-8"))
    pages = json.loads((OUT / "selection.json").read_text(encoding="utf-8"))["pages"]
    tables = {name: {p: load_tables(run, p) for p in pages} for name, run in RUNS.items()}
    used = {name: {p: set() for p in pages} for name in RUNS}
    out = {"tables": [], "false_positive_tables": {}, "pair_comparison": []}

    for t in gt["tables"]:
        row = {"id": t["id"], "features": t["features"], "n_facts": len(t["facts"])}
        for name in RUNS:
            cands = []
            for i, pt in enumerate(tables[name][t["page"]]):
                ov = inter(pt["bbox_pt"], t["bbox_pt"])
                if ov and (ov / area(t["bbox_pt"]) >= 0.3 or ov / area(pt["bbox_pt"]) >= 0.5):
                    cands.append((i, pt, ov / area(t["bbox_pt"])))
            for i, _, _ in cands:
                used[name][t["page"]].add(i)
            coverage = min(1.0, sum(c for _, _, c in cands))
            found = "미탐지" if not cands else ("찾음" if coverage >= 0.5 else "일부만")
            cell_texts = [c["text"] or "" for _, pt, _ in cands for c in pt["cells"]]
            res = {"found": found, "n_tables": len(cands), "coverage": round(coverage, 2),
                   "shapes": [f"{pt['n_rows']}x{pt['n_cols']}" for _, pt, _ in cands]}
            # 파서 층: 원시 셀에서 행 라벨과 값의 짝이 유지됐는가 (조립 로직과 무관)
            grids = [grid_from_cells(pt, fill_spans=True) for _, pt, _ in cands]
            raw_fails = []
            for fact in t["facts"]:
                if any(raw_fact_ok(fact, g, other_row_tokens(fact, t["facts"])) for g in grids):
                    continue
                if not cands:
                    kind = "표 미탐지"
                elif not all(value_anywhere(v, cell_texts) for _, v in fact[1]):
                    kind = "수량 누락"
                elif not all(value_anywhere(tok, cell_texts) for tok in fact[0]):
                    kind = "행 라벨 누락"
                else:
                    kind = "행 짝 잃음"
                raw_fails.append({"fact": fact, "kind": kind})
            res["raw"] = {"passed": len(t["facts"]) - len(raw_fails), "fails": raw_fails}
            for fill in (True, False):
                recs = [r for _, pt, _ in cands for r in records(pt, fill)]
                passed, fails = 0, []
                for fact in t["facts"]:
                    if any(fact_ok(fact, r) and exclusive_ok(fact, r.split(" | "), other_row_tokens(fact, t["facts"])) for r in recs):
                        passed += 1
                        continue
                    if not cands:
                        kind = "표 미탐지"
                    elif not all(value_anywhere(v, cell_texts) for _, v in fact[1]):
                        kind = "수량 누락"
                    elif not all(value_anywhere(tok, cell_texts) for tok in fact[0]):
                        kind = "행 라벨 누락"
                    elif not recs:
                        kind = "레코드 없음(조립)"
                    else:
                        kind = "잘못 붙음"
                    # 같은 행 라벨을 가진 레코드가 있으면 실제로 무엇이 붙었는지 증거로 남긴다
                    near = [r for r in recs if fact[0] and all(row_token_in(tok, r) for tok in fact[0])][:2]
                    fails.append({"fact": fact, "kind": kind, "records_with_row_label": near})
                res["spanfill" if fill else "extract"] = {"passed": passed, "fails": fails}
            row[name] = res
        # 두 파서가 같은 표 하나씩을 찾았으면 셀·레코드가 같은지 비교
        a_list = [pt for pt in tables["pymupdf"][t["page"]] if inter(pt["bbox_pt"], t["bbox_pt"]) / area(t["bbox_pt"]) >= 0.3]
        b_list = [pt for pt in tables["odl_local"][t["page"]] if inter(pt["bbox_pt"], t["bbox_pt"]) / area(t["bbox_pt"]) >= 0.3]
        if len(a_list) == 1 and len(b_list) == 1:
            cmp = compare_pair(a_list[0], b_list[0])
            cmp["notation_cells"] = notation_diffs(a_list[0], b_list[0])
            row["pair"] = cmp
        out["tables"].append(row)

    for name in RUNS:
        fps = []
        for p in pages:
            for i, pt in enumerate(tables[name][p]):
                if i not in used[name][p]:
                    fps.append({"page": p, "index": i, "bbox_pt": pt["bbox_pt"], "shape": f"{pt['n_rows']}x{pt['n_cols']}",
                                "text": " / ".join(ws(c["text"]) for c in pt["cells"] if c["text"])[:120]})
        out["false_positive_tables"][name] = fps
    save_json(OUT / "score.json", out)
    print_summary(out)


def notation_diffs(a, b) -> list:
    """같은 위치 셀의 글자가 표기 정규화 후에는 같고 원문 그대로는 다른 경우를 분류해 센다."""
    bmap = {(c["r0"], c["c0"]): c["text"] or "" for c in b["cells"]}
    diffs = []
    for c in a["cells"]:
        ta, tb = c["text"] or "", bmap.get((c["r0"], c["c0"]))
        if tb is None or ta == tb or nws(ta) != nws(tb):
            continue
        if ws(ta) == ws(tb):
            kind = "공백·줄바꿈"
        elif ws(strip_brackets(ta)) == ws(strip_brackets(tb)):
            kind = "괄호 글리프"
        elif re.search(r"[₀-₉⁰-⁹]", ta + tb):
            kind = "아래·위첨자"
        else:
            kind = "기타 유니코드 표기"
        diffs.append({"kind": kind, "pymupdf": ta, "odl_local": tb})
    return diffs


def print_summary(out) -> None:
    for adapter in ("raw", "spanfill", "extract"):
        print(f"== 어댑터 {adapter} ==")
        for name in RUNS:
            facts = sum(t["n_facts"] for t in out["tables"])
            passed = sum(t[name][adapter]["passed"] for t in out["tables"])
            found = sum(t[name]["found"] == "찾음" for t in out["tables"])
            kinds = {}
            for t in out["tables"]:
                for f in t[name][adapter]["fails"]:
                    kinds[f["kind"]] = kinds.get(f["kind"], 0) + 1
            perfect = sum(t[name][adapter]["passed"] == t["n_facts"] for t in out["tables"])
            print(f"  {name}: 표 찾음 {found}/{len(out['tables'])}, 완전 통과 표 {perfect}, fact {passed}/{facts}, 실패 {kinds}")
    print("== 표별 (spanfill) ==")
    for t in out["tables"]:
        a, b = t["pymupdf"], t["odl_local"]
        pair = t.get("pair")
        same = "-" if not pair else ("완전동일" if pair["same_strict"] else ("표기만다름" if pair["same_loose"] else "다름"))
        print(f"  {t['id']:9} facts {t['n_facts']:2} | PM {a['found']}{a['shapes']} {a['raw']['passed']:2}/{a['spanfill']['passed']:2} | "
              f"ODL {b['found']}{b['shapes']} {b['raw']['passed']:2}/{b['spanfill']['passed']:2} | 셀비교 {same}")
    for name, fps in out["false_positive_tables"].items():
        print(f"  정답에 없는 표 ({name}): {[(f['page'], f['shape']) for f in fps]}")


def baseline() -> None:
    """score.json에서 사실별 통과·실패만 뽑아 비퇴행(G6) 기준으로 남긴다. 사실은 정답 파일의 순서 번호로 가리킨다."""
    gt = json.loads((OUT / "ground_truth.json").read_text(encoding="utf-8"))
    sc = json.loads((OUT / "score.json").read_text(encoding="utf-8"))
    facts = {t["id"]: [json.dumps(f, ensure_ascii=False) for f in t["facts"]] for t in gt["tables"]}
    out = {"note": "현행 경로(PyMuPDF + parse.py 조립)와 ODL + 같은 조립의 사실별 결과. 번호는 ground_truth.json facts 순서. 정답은 잠정.",
           "ground_truth_status": gt.get("status"), "tables": {}}
    for t in sc["tables"]:
        row = {}
        for name in RUNS:
            for layer in ("raw", "spanfill", "extract"):
                failed = {json.dumps(f["fact"], ensure_ascii=False) for f in t[name][layer]["fails"]}
                row[f"{name}.{layer}.failed"] = [i for i, f in enumerate(facts[t["id"]]) if f in failed]
        out["tables"][t["id"]] = {"n_facts": t["n_facts"], **row}
    for name in RUNS:
        for layer in ("raw", "spanfill", "extract"):
            n = sum(len(v[f"{name}.{layer}.failed"]) for v in out["tables"].values())
            out.setdefault("totals", {})[f"{name}.{layer}.passed"] = sum(v["n_facts"] for v in out["tables"].values()) - n
    save_json(OUT / "baseline.json", out)
    print(json.dumps(out["totals"], ensure_ascii=False))


if __name__ == "__main__":
    {"select": lambda: print(select()), "render": render, "crops": crops, "score": score,
     "baseline": baseline}[sys.argv[1]]()
