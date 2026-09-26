"""P2 평가: ODL 경로의 칸 안 행 분리(odl_tables.read_tables(split_rows=True))를 확인한다.

ODL은 한 번만 실행하고, 같은 원시 JSON에서 행 분리 끔/켬 두 결과를 만들어 비교한다.
  1. blind20: 사실 번호별 결과. 대상은 공통 오류 중 원시 추출 문제 31건. 기준선(baseline.json) 대비 퇴행도 본다.
  2. 5표 정답: score.py를 그대로 돌린다(결과 폴더 p2_odl_nosplit / p2_odl_rowsplit).
  3. 기존 23건: evals/check_parse.py를 그대로 돌리되, 이 스크립트 안에서만 parse.read_tables를 ODL 경로로 바꿔 끼운다.
     parse.py 파일과 기본 실행 경로는 바꾸지 않는다.

실행: python experiments/parser_bench/p2_eval.py
원시 출력(results/p2_odl_*)은 커밋하지 않는다.
"""
import contextlib
import io
import json
import shutil
import subprocess
import sys

import pymupdf

from blind_eval import OUT
from common import PDF, RESULTS, ROOT, iou, load_goldens, save_json
from p1_reproduce import LAYERS, candidates, failed_ids

sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "evals"))
import check_parse  # noqa: E402
import parse  # noqa: E402
from odl_tables import read_tables, run_odl, to_grid  # noqa: E402

RUN_DIR = RESULTS / "p2_odl_rowsplit"
SKIP_TABLES = ("p334_t1", "p872_t1")  # 파서 차이로 갈린 표. 공통 오류 집계에서 뺀다(REPORT.md와 같은 기준)


def target_facts(base) -> list[tuple[str, int]]:
    """공통 오류 64건 중 원시 추출 문제 31건: 두 파서 모두 최종 레코드에서 틀리고 ODL 원시 층에서도 틀린 사실."""
    out = []
    for tid, t in base["tables"].items():
        if tid in SKIP_TABLES:
            continue
        shared = set(t["pymupdf.spanfill.failed"]) & set(t["odl_local.spanfill.failed"])
        out += [(tid, i) for i in sorted(shared & set(t["odl_local.raw.failed"]))]
    return out


def blind20(gt, tables) -> dict:
    return {t["id"]: failed_ids(t, candidates(t, tables[t["page"]])) for t in gt["tables"]}


def golden_tables_json(tables, name: str) -> None:
    """score.py 입력 형식으로 저장한다. 정답 표 대응은 extract_odl.py와 같은 규칙(중첩 제외, IoU 0.3 이상 중 최대)."""
    out = {}
    for tid, golden in load_goldens().items():
        page = golden["source"]["pdf_page"]
        target = golden["source"]["table_bbox_pt"]
        scored = sorted(((iou(t["bbox_pt"], target), t) for t in tables[page] if not t["nested"]),
                        key=lambda x: x[0], reverse=True)
        if scored and scored[0][0] >= 0.3:
            best_iou, best = scored[0]
            out[tid] = {**{k: best[k] for k in ("n_rows", "n_cols", "cells", "bbox_pt")},
                        "id": tid, "page": page, "match_iou": round(best_iou, 3)}
    save_json(RESULTS / name / "tables.json", {"parser": "OpenDataLoader PDF (pipeline/odl_tables.py)",
                                              "version": "2.5.11", "config": {"split_rows": name.endswith("rowsplit")},
                                              "tables": out})


def check_23(tables) -> tuple[int, str]:
    original = parse.read_tables

    def odl_read_tables(page):
        return [(tuple(t["bbox_pt"]), to_grid(t, fill_spans=True)) for t in tables[page.number + 1]]

    parse.read_tables = odl_read_tables if tables is not None else original
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            code = check_parse.main()
    finally:
        parse.read_tables = original
    return code, buf.getvalue()


def main() -> None:
    gt = json.loads((OUT / "ground_truth.json").read_text(encoding="utf-8"))
    base = json.loads((OUT / "baseline.json").read_text(encoding="utf-8"))
    blind_pages = json.loads((OUT / "selection.json").read_text(encoding="utf-8"))["pages"]
    golden = json.loads(check_parse.GOLDEN.read_text(encoding="utf-8"))
    case_pages = sorted({c["page"] for c in golden["cases"]})
    pages = sorted(set(blind_pages) | set(range(case_pages[0], case_pages[-1] + 1))
                   | {g["source"]["pdf_page"] for g in load_goldens().values()})

    run = run_odl(PDF, pages, RUN_DIR / "raw")
    with pymupdf.open(PDF) as doc:
        heights = {p: doc[p - 1].rect.height for p in pages}
    variants = {"nosplit": read_tables(run["json_path"], heights, split_rows=False),
                "rowsplit": read_tables(run["json_path"], heights, split_rows=True)}

    report = {"odl_pages": pages, "elapsed_sec": run["elapsed_sec"]}

    # 1. blind20
    targets = target_facts(base)
    res = {name: blind20(gt, tabs) for name, tabs in variants.items()}
    facts = {t["id"]: t["facts"] for t in gt["tables"]}
    report["blind20"] = {}
    for name, r in res.items():
        report["blind20"][name] = {layer: sum(len(facts[tid]) - len(v[layer]) for tid, v in r.items()) for layer in LAYERS}
    report["nosplit_equals_baseline"] = all(
        res["nosplit"][tid][layer] == base["tables"][tid][f"odl_local.{layer}.failed"] for tid in res["nosplit"] for layer in LAYERS)
    report["targets"] = [{"table": tid, "fact": i, "row": facts[tid][i][0],
                          "raw": i not in res["rowsplit"][tid]["raw"],
                          "spanfill": i not in res["rowsplit"][tid]["spanfill"],
                          "extract": i not in res["rowsplit"][tid]["extract"]} for tid, i in targets]
    # 퇴행: 기준선(ODL 경로)에서 맞던 사실이 행 분리 뒤 틀린 것, 현행 운영 경로(PyMuPDF extract)가 맞히는데 틀린 것
    report["regressions_vs_odl_baseline"] = [
        {"table": tid, "fact": i, "layer": layer, "row": facts[tid][i][0]}
        for tid in facts for layer in LAYERS
        for i in sorted(set(res["rowsplit"][tid][layer]) - set(base["tables"][tid][f"odl_local.{layer}.failed"]))]
    report["gains_outside_targets"] = [
        {"table": tid, "fact": i, "layer": layer} for tid in facts for layer in LAYERS
        for i in sorted(set(base["tables"][tid][f"odl_local.{layer}.failed"]) - set(res["rowsplit"][tid][layer]))
        if (tid, i) not in targets]
    report["vs_production_extract"] = {
        name: [{"table": tid, "fact": i} for tid in facts
               for i in sorted(set(res[name][tid]["spanfill"]) - set(base["tables"][tid]["pymupdf.extract.failed"]))]
        for name in res}
    report["split_tables_blind20"] = {f"p{p}#{i}": t["rows_split"] for p in blind_pages
                                     for i, t in enumerate(variants["rowsplit"][p]) if t["rows_split"]}

    # 2. 5표 정답 (score.py는 results/summary.json을 덮어쓰므로 보관 후 되돌린다)
    for name, tabs in variants.items():
        golden_tables_json(tabs, f"p2_odl_{name}")
    summary = RESULTS / "summary.json"
    backup = summary.read_bytes() if summary.exists() else None
    proc = subprocess.run([sys.executable, "score.py", "odl_local__fullpdf", "p2_odl_nosplit", "p2_odl_rowsplit"],
                          cwd=RESULTS.parent, capture_output=True, text=True, encoding="utf-8")
    scored = json.loads(summary.read_text(encoding="utf-8"))
    if backup is not None:
        summary.write_bytes(backup)
    else:
        summary.unlink()
    report["golden5"] = {k: {"B_spanfill": v["B"]["spanfill"], "B_extract": v["B"]["extract"]} for k, v in scored.items()}
    report["golden5_stderr"] = proc.stderr[-1500:]

    # 3. 기존 23건
    report["check_parse"] = {}
    for name, tabs in [("pymupdf(운영)", None), ("odl_nosplit", variants["nosplit"]), ("odl_rowsplit", variants["rowsplit"])]:
        code, out = check_23(tabs)
        report["check_parse"][name] = out.strip()

    save_json(RUN_DIR / "p2_report.json", report)
    print(f"ODL {run['elapsed_sec']}초, {len(pages)}쪽")
    print("blind20:", json.dumps(report["blind20"], ensure_ascii=False), "| 끔=기준선:", report["nosplit_equals_baseline"])
    ok = sum(t["raw"] for t in report["targets"])
    print(f"원시 추출 대상 {len(targets)}건 중 원시 층 복원 {ok}건, 최종 레코드(spanfill) 통과 {sum(t['spanfill'] for t in report['targets'])}건")
    for t in report["targets"]:
        print(f"   {t['table']:8} #{t['fact']:2} {'복원' if t['raw'] else '미복원':3} 레코드{'O' if t['spanfill'] else 'X'} {t['row']}")
    print("퇴행(ODL 기준선 대비):", report["regressions_vs_odl_baseline"])
    print("대상 밖 개선:", len(report["gains_outside_targets"]), report["gains_outside_targets"][:12])
    print("현행 운영 경로가 맞히는데 틀린 사실(spanfill):", {k: len(v) for k, v in report["vs_production_extract"].items()})
    print("행을 나눈 표:", report["split_tables_blind20"])
    for k, v in report["golden5"].items():
        print("5표", k, json.dumps(v["B_spanfill"], ensure_ascii=False)[:400])
    for k, v in report["check_parse"].items():
        print("23건", k, v.splitlines()[0] if v else v)


if __name__ == "__main__":
    main()
