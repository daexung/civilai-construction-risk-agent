"""P3 평가: 선 기반 누락 감시(pipeline/table_guard.py)와 대체 추출.

ODL(행 분리 켬)은 한 번만 실행하고, 감시 끔/켬을 비교한다. 대상 쪽은 개발·회귀 세트뿐이다.
  - blind20 20쪽, 검증 10쪽(396·500쪽 포함), 기존 23건 범위, 5표 정답 쪽
확인:
  1. 감시 판정 목록: 누락 의심·부분 누락 의심 영역과 그 영역의 글자(오탐 여부를 사람이 보도록)
  2. 감시 범위 밖 정답 표: 정답 표 bbox의 50% 이상을 덮는 선 표 후보가 없는 표
  3. 396·500쪽 대각선 표 사실(ground_truth_failures.json, 잠정·비맹검)
  4. blind20 사실, 5표 정답, 기존 23건 퇴행

실행: python experiments/parser_bench/p3_eval.py
원시 출력(results/p3_guard/)은 커밋하지 않는다.
"""
import json
import subprocess
import sys

import pymupdf

from blind_eval import OUT
from common import PDF, RESULTS, ROOT, load_goldens, save_json
from p1_reproduce import LAYERS, candidates, failed_ids
from p2_eval import check_23, golden_tables_json

sys.path.insert(0, str(ROOT / "pipeline"))
import check_parse  # noqa: E402
from odl_tables import read_tables, run_odl  # noqa: E402
from table_guard import area, guard, ruled_regions  # noqa: E402

RUN_DIR = RESULTS / "p3_guard"
FAILURES = RESULTS / "validation" / "ground_truth_failures.json"


def score_facts(gt_tables, tables) -> dict:
    out = {}
    for t in gt_tables:
        got = failed_ids(t, candidates(t, tables.get(t["page"], [])))
        out[t["id"]] = {layer: {"passed": len(t["facts"]) - len(got[layer]), "failed": got[layer]} for layer in LAYERS}
        out[t["id"]]["n_facts"] = len(t["facts"])
    return out


def in_scope(gt_tables, regions_by_page) -> list[dict]:
    rows = []
    for t in gt_tables:
        best = 0.0
        for r in regions_by_page.get(t["page"], []):
            b = t["bbox_pt"]
            inter = area([max(r[0], b[0]), max(r[1], b[1]), min(r[2], b[2]), min(r[3], b[3])])
            best = max(best, inter / area(b))
        rows.append({"id": t["id"], "in_scope": best >= 0.5, "overlap": round(best, 2), "features": t.get("features", [])})
    return rows


def main() -> None:
    gt = json.loads((OUT / "ground_truth.json").read_text(encoding="utf-8"))
    failures = json.loads(FAILURES.read_text(encoding="utf-8"))
    blind_pages = json.loads((OUT / "selection.json").read_text(encoding="utf-8"))["pages"]
    val_pages = json.loads((RESULTS / "validation" / "selection.json").read_text(encoding="utf-8"))["pages"]
    golden = json.loads(check_parse.GOLDEN.read_text(encoding="utf-8"))
    case_pages = sorted({c["page"] for c in golden["cases"]})
    pages = sorted(set(blind_pages) | set(val_pages) | set(range(case_pages[0], case_pages[-1] + 1))
                   | {g["source"]["pdf_page"] for g in load_goldens().values()})

    run = run_odl(PDF, pages, RUN_DIR / "raw")
    with pymupdf.open(PDF) as doc:
        heights = {p: doc[p - 1].rect.height for p in pages}
        regions = {p: ruled_regions(doc[p - 1]) for p in pages}
        region_text = {}
        for p, rs in regions.items():
            for r in rs:
                region_text[(p, tuple(r))] = " ".join(doc[p - 1].get_text("text", clip=pymupdf.Rect(r)).split())[:80]
    plain = read_tables(run["json_path"], heights, split_rows=True)
    guarded, log = guard(PDF, plain)

    report = {"pages": pages, "odl_elapsed_sec": run["elapsed_sec"]}
    # 1. 감시 판정
    for e in log:
        e["text"] = region_text[(e["page"], tuple(e["region"]))]
    report["guard_log"] = log
    report["guard_counts"] = {s: sum(1 for e in log if e["status"] == s) for s in ("covered", "partial", "missing")}
    # 2. 감시 범위
    report["scope_blind20"] = in_scope(gt["tables"], regions)
    report["scope_failures"] = in_scope(failures["tables"], regions)
    goldens = [{"id": tid, "page": g["source"]["pdf_page"], "bbox_pt": g["source"]["table_bbox_pt"]}
               for tid, g in load_goldens().items()]
    report["scope_golden5"] = in_scope(goldens, regions)
    # 3·4. 사실
    report["failures"] = {"no_guard": score_facts(failures["tables"], plain), "guard": score_facts(failures["tables"], guarded)}
    # PyMuPDF 실험 추출기(검증 10쪽) 참고값
    pm = {p: json.loads((RESULTS / "validation_pymupdf" / "raw" / f"p{p}_all_tables.json").read_text(encoding="utf-8"))
          for p in (396, 500)}
    report["failures"]["pymupdf_reference"] = score_facts(failures["tables"], pm)
    b20 = {name: score_facts(gt["tables"], tabs) for name, tabs in (("no_guard", plain), ("guard", guarded))}
    report["blind20_totals"] = {name: {layer: sum(v[layer]["passed"] for v in r.values()) for layer in LAYERS}
                                for name, r in b20.items()}
    report["blind20_changed"] = [{"table": tid, "layer": layer, "no_guard": b20["no_guard"][tid][layer]["failed"],
                                  "guard": b20["guard"][tid][layer]["failed"]}
                                 for tid in b20["guard"] for layer in LAYERS
                                 if b20["guard"][tid][layer]["failed"] != b20["no_guard"][tid][layer]["failed"]]
    # 5표 정답 (score.py는 results/summary.json을 덮어쓰므로 보관 후 되돌린다)
    golden_tables_json(guarded, "p3_odl_guard")
    summary = RESULTS / "summary.json"
    backup = summary.read_bytes() if summary.exists() else None
    subprocess.run([sys.executable, "score.py", "p2_odl_rowsplit", "p3_odl_guard"], cwd=RESULTS.parent,
                   capture_output=True, text=True, encoding="utf-8")
    scored = json.loads(summary.read_text(encoding="utf-8"))
    if backup is not None:
        summary.write_bytes(backup)
    report["golden5"] = {k: v["B"]["spanfill"] for k, v in scored.items()}
    report["check_parse"] = {"odl_rowsplit_guard": check_23(guarded)[1].strip().splitlines()[0],
                             "pymupdf(운영)": check_23(None)[1].strip().splitlines()[0]}
    save_json(RUN_DIR / "p3_report.json", report)

    print(f"ODL {run['elapsed_sec']}초, {len(pages)}쪽 · 감시 판정 {report['guard_counts']}")
    for e in log:
        if e["status"] != "covered":
            print(f"   p{e['page']} {e['status']:8} 덮임 {e['coverage']:.2f} {e['region']} 대체 {e.get('fallback_tables')} | {e['text'][:60]}")
    for key in ("scope_blind20", "scope_failures", "scope_golden5"):
        out = [r for r in report[key] if not r["in_scope"]]
        print(f"{key}: 범위 안 {sum(r['in_scope'] for r in report[key])}/{len(report[key])}, 범위 밖 {[(r['id'], r['overlap']) for r in out]}")
    for name, r in report["failures"].items():
        print(f"396·500 {name}:", {tid: f"{v['spanfill']['passed']}/{v['n_facts']} (raw {v['raw']['passed']}, extract {v['extract']['passed']})"
                                   for tid, v in r.items()})
    print("blind20 감시 끔/켬:", report["blind20_totals"], "변화", report["blind20_changed"])
    for k, v in report["golden5"].items():
        print("5표", k, v["expected_own"], v["expected_shared"], "노무량", v["estimate"], "형식실패", v["old_golden_failures_by_type"])
    print("23건", report["check_parse"])


if __name__ == "__main__":
    main()
