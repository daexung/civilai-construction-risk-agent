"""P1 확인: pipeline/odl_tables.py 어댑터 + 현행 조립(clean_table·table_to_records)으로 blind20 기준선을 재현한다.

- 추출은 어댑터의 run_odl로 새로 한다(실험용 extract_odl.py 출력을 쓰지 않는다).
- 격자 변환도 어댑터의 to_grid를 쓴다.
- 채점은 고정된 blind_eval.py의 판정 함수를 그대로 가져다 쓴다(SCORING_RULES.md 3절). 표 대응 규칙(3-2)만 여기에 같은 값으로 옮겨 적었다.
- 재현 기준: baseline.json의 odl_local.{raw,spanfill,extract}.failed와 사실 번호 단위로 완전히 같아야 한다.

실행: python experiments/parser_bench/p1_reproduce.py
원시 출력은 results/p1_odl_adapter/ 아래에 두고 커밋하지 않는다.
"""
import json
import sys

import pymupdf

from blind_eval import (OUT, area, exclusive_ok, fact_ok, inter, other_row_tokens, raw_fact_ok)
from common import PDF, RESULTS, ROOT, save_json

sys.path.insert(0, str(ROOT / "pipeline"))
from odl_tables import read_tables, run_odl, to_grid  # noqa: E402
from parse import clean_table, table_to_records  # noqa: E402

RUN_DIR = RESULTS / "p1_odl_adapter"
LAYERS = ("raw", "spanfill", "extract")


def records(table, fill: bool) -> list[str]:
    try:
        return [r["text"] for r in table_to_records(clean_table(to_grid(table, fill_spans=fill)), "S", 0)]
    except Exception as exc:
        return [f"조립 오류: {type(exc).__name__}: {exc}"]


def candidates(gt_table, page_tables):
    # SCORING_RULES 3-2와 같은 규칙: 정답 넓이의 30% 이상 또는 파서 표 넓이의 50% 이상 겹침
    out = []
    for pt in page_tables:
        ov = inter(pt["bbox_pt"], gt_table["bbox_pt"])
        if ov and (ov / area(gt_table["bbox_pt"]) >= 0.3 or ov / area(pt["bbox_pt"]) >= 0.5):
            out.append(pt)
    return out


def failed_ids(gt_table, cands) -> dict[str, list[int]]:
    facts = gt_table["facts"]
    grids = [to_grid(pt, fill_spans=True) for pt in cands]
    recs = {"spanfill": [r for pt in cands for r in records(pt, True)],
            "extract": [r for pt in cands for r in records(pt, False)]}
    out = {layer: [] for layer in LAYERS}
    for i, fact in enumerate(facts):
        others = other_row_tokens(fact, facts)
        if not any(raw_fact_ok(fact, g, others) for g in grids):
            out["raw"].append(i)
        for layer in ("spanfill", "extract"):
            if not any(fact_ok(fact, r) and exclusive_ok(fact, r.split(" | "), others) for r in recs[layer]):
                out[layer].append(i)
    return out


def main() -> None:
    gt = json.loads((OUT / "ground_truth.json").read_text(encoding="utf-8"))
    base = json.loads((OUT / "baseline.json").read_text(encoding="utf-8"))
    pages = json.loads((OUT / "selection.json").read_text(encoding="utf-8"))["pages"]

    run = run_odl(PDF, pages, RUN_DIR / "raw")
    with pymupdf.open(PDF) as doc:
        heights = {p: doc[p - 1].rect.height for p in pages}
    tables = read_tables(run["json_path"], heights)

    report = {"elapsed_sec": run["elapsed_sec"], "command": run["command"], "tables": {}, "mismatch": []}
    totals = {layer: 0 for layer in LAYERS}
    for t in gt["tables"]:
        got = failed_ids(t, candidates(t, tables[t["page"]]))
        want = {layer: base["tables"][t["id"]][f"odl_local.{layer}.failed"] for layer in LAYERS}
        report["tables"][t["id"]] = got
        for layer in LAYERS:
            totals[layer] += t["n_facts"] if "n_facts" in t else len(t["facts"])
            totals[layer] -= len(got[layer])
            if got[layer] != want[layer]:
                report["mismatch"].append({"table": t["id"], "layer": layer, "got": got[layer], "baseline": want[layer]})
    report["passed"] = totals
    report["baseline_passed"] = {layer: base["totals"][f"odl_local.{layer}.passed"] for layer in LAYERS}

    # 참고: 실험용 추출기 결과와 표 단위로도 같은지(있을 때만)
    same, diff = 0, []
    for p in pages:
        old_path = RESULTS / "blind20_odl_local" / "raw" / f"p{p}_all_tables.json"
        if not old_path.exists():
            continue
        old = json.loads(old_path.read_text(encoding="utf-8"))
        new = [{k: v for k, v in t.items() if k not in ("page", "nested")} for t in tables[p]]
        if old == new:
            same += 1
        else:
            diff.append(p)
    report["vs_experiment_extractor"] = {"pages_identical": same, "pages_different": diff}
    save_json(RUN_DIR / "reproduction.json", report)

    print(f"ODL 실행 {run['elapsed_sec']}초 (20쪽)")
    for layer in LAYERS:
        print(f"  {layer:8} 재현 {totals[layer]}/286  기준선 {report['baseline_passed'][layer]}/286")
    print(f"  사실 번호 불일치 {len(report['mismatch'])}건", report["mismatch"][:5])
    print(f"  실험용 추출기와 표 결과 동일한 쪽 {same}/{len(pages)}, 다른 쪽 {diff}")


if __name__ == "__main__":
    main()
