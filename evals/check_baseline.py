"""main 9a2af9f 기준 결과와 현재 코드를 같은 시나리오로 비교한다(오프라인, 운영 DB·유료 API 없음).

사용자 입력 하나와 그 뒤 자동 답을 한 턴으로 묶어, 질문 횟수와 관계없이 턴의 최종 결과를 비교한다.

보존(preserve) 사례
- 실제 회귀: 최종 상태·선택 공종·입력·단위·출처·계산 금액·근거 인용이 다름, 완료 결과 누락,
  반복 질문, 실행 오류, main에서 고른 필수 공종 후보 누락, Excel 숫자 다름, 사용자 턴 누락
- 검토 필요한 변경: 질문 응답 횟수, 후보 표시 변경(필수 후보 유지), 중간 상태·질문 순서·문구, Excel 글자
main 오동작(main_bug) 사례는 scenarios.json의 fix_check 기준으로 해결 / 미해결 / 악화 / 판단 불가를 판정하고,
통과 여부에는 넣지 않는다. 기준 파일은 이 검사가 덮어쓰지 않는다(--refresh-main은 main 코드로만 다시 만든다).

사용:
  python evals/check_baseline.py                 # 현재 작업 트리를 기준과 비교
  python evals/check_baseline.py --refresh-main  # tmp/main-baseline(9a2af9f)로 기준 파일을 다시 만든다
"""

from __future__ import annotations

import argparse
import io
import json
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMIT = "9a2af9f"
BASELINE_ROOT = ROOT / "tmp/main-baseline"
FIXTURE = ROOT / "evals/fixtures/baseline_main_9a2af9f.json"
CHECKPOINT = ROOT / "evals/fixtures/legacy_checkpoints/main_9a2af9f_pending_ask.json"
SCENARIOS = ROOT / "evals/baseline/scenarios.json"
RUNNER = ROOT / "evals/baseline/run_scenarios.py"


def _prepare_main() -> None:
    """main 커밋 파일만 git archive로 꺼낸다(.git·작업 트리는 건드리지 않음)."""
    if (BASELINE_ROOT / "BASELINE_COMMIT").exists():
        return
    BASELINE_ROOT.mkdir(parents=True, exist_ok=True)
    archive = subprocess.run(["git", "archive", COMMIT, "backend", "data", "evals", "pipeline", "frontend/src"], cwd=ROOT, capture_output=True, check=True)
    # Windows 기본 tar는 한글 경로를 풀지 못하므로 표준 라이브러리로 푼다.
    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as bundle:
        bundle.extractall(BASELINE_ROOT, filter="data")
    # git에서 제외된 데이터 파일은 같은 파일을 복사한다(해시를 결과 meta에 기록).
    for name in ("data/processed/page_map.json", "data/processed/embeddings.all.gemini-embedding-2.parquet"):
        if (ROOT / name).exists():
            shutil.copy(ROOT / name, BASELINE_ROOT / name)
    (BASELINE_ROOT / "BASELINE_COMMIT").write_text(COMMIT, encoding="utf-8")


def _run(root: Path, out: Path, *extra: str) -> dict:
    """버전마다 별도 프로세스로 실행해 import 경로·캐시·환경설정이 섞이지 않게 한다."""
    command = [sys.executable, str(RUNNER), "--root", str(root), "--scenarios", str(SCENARIOS), "--out", str(out), *extra]
    subprocess.run(command, check=True, env={**_clean_env(), "PYTHONIOENCODING": "utf-8"})
    return json.loads(out.read_text(encoding="utf-8"))


def _clean_env() -> dict:
    import os
    blocked = ("INDEX_CONFIG", "CHAT_DATABASE_URL", "GEMINI_API_KEY", "VERTEX_API_KEY", "SUPABASE", "QUOTA_HASH_SECRET",
               "PYTHONPATH", "APP_ENV", "AGENT_")
    return {key: value for key, value in os.environ.items() if not key.startswith(blocked)}


TERMINAL = {"OK", "PARTIAL", "BLOCKED", "COMPUTED", "ANSWERED", "OUT_OF_SCOPE", "EVIDENCE_ONLY", "ERROR"}


def _split_excel(sheets: dict) -> tuple[dict, dict]:
    numbers = {name: [[c for c in row if isinstance(c, (int, float))] for row in rows] for name, rows in sheets.items()}
    texts = {name: [[c for c in row if not isinstance(c, (int, float))] for row in rows] for name, rows in sheets.items()}
    return numbers, texts


def _groups(step: dict) -> dict:
    """응답 하나를 성격별 값으로 나눈다. 공종 후보(work_choices)는 선택과 분리해 따로 판단한다."""
    response = step.get("response") or {}
    questions = response.get("questions") or []
    result = response.get("result") or {}
    unit_lines = result.get("unit_lines") or []
    return {
        "selection": {"status": response.get("status"), "route": response.get("route"),
                      "spec_id": (response.get("work") or {}).get("spec_id"),
                      "confirmed": (response.get("work") or {}).get("confirmed"),
                      "evidence": response.get("evidence"), "qa_sections": (response.get("qa") or {}).get("sections"),
                      "items": response.get("items")},
        "work_choices": next((q["choices"] for q in questions if q["name"] == "work"), None),
        "inputs": {"inputs": response.get("inputs"), "conditions": response.get("conditions"),
                   "unit_basis": result.get("unit_basis"), "units": [(l["name"], l["unit"]) for l in unit_lines]},
        "calc": {"unit_lines": [(l["name"], l["applied"], l["exact"]) for l in unit_lines], "lines": result.get("lines"),
                 "daily_volume": result.get("daily_volume"), "work_days": result.get("work_days"),
                 "not_calculated": result.get("not_calculated"), "priced": response.get("priced"),
                 "statement": response.get("statement"), "bill": response.get("bill")},
        "citations": {"result": result.get("citations"), "qa": (response.get("qa") or {}).get("citations")},
        "questions": [(q["name"], q["choices"] if q["name"] != "work" else None, q["default"], q.get("optional"))
                      for q in questions],
        "text": {"message": response.get("message"), "answer": response.get("answer"),
                 "asks": [(q["ask"], q.get("reason")) for q in questions], "qa": (response.get("qa") or {}).get("conclusion")},
    }


def _turns(steps: list) -> list[dict]:
    """사용자 입력(메시지·자유 입력·재전송·조건 변경·내보내기) 하나와 그 뒤의 자동 답을 한 턴으로 묶는다.

    자동 답 횟수는 버전마다 달라질 수 있으므로 중간 응답을 순번으로 대응시키지 않는다.
    """
    turns: list[dict] = []
    for step in steps:
        op = step.get("op") or {}
        if "answers" in op and turns:
            turns[-1]["auto"].append(step)
        else:
            turns.append({"op": next(iter(op), "error"), "first": step, "auto": []})
    return turns


def _final(turn: dict) -> dict:
    return turn["auto"][-1] if turn["auto"] else turn["first"]


def _status(step: dict) -> str | None:
    return (step.get("response") or {}).get("status")


def _problems(turn: dict) -> set[str]:
    """실행 오류, 답을 보냈는데 같은 질문이 그대로 반복되는 경우."""
    found = set()
    sequence = [turn["first"], *turn["auto"]]
    for step in sequence:
        if "error" in step or "http_status" in (step.get("response") or {}) or "http_status" in (step.get("excel") or {}):
            found.add("실행 오류")
    for previous, current in zip(sequence, sequence[1:]):
        before, after = previous.get("response") or {}, current.get("response") or {}
        if before.get("status") == after.get("status") == "MISSING_INFO" and \
                [q["name"] for q in before.get("questions", [])] == [q["name"] for q in after.get("questions", [])]:
            found.add("반복 질문")
            break
    return found


def _required_choices(turn: dict) -> set[str]:
    """main에서 실제로 고른 공종 선택지. 현재 버전에서도 후보에 있어야 한다."""
    sequence = [turn["first"], *turn["auto"]]
    required = set()
    for step, following in zip(sequence, sequence[1:]):
        choices = _groups(step)["work_choices"]
        picked = ((following.get("op") or {}).get("answers") or {}).get("work")
        if choices and picked in choices:
            required.add(picked)
    return required


def compare_preserve(expected: list, actual: list) -> tuple[list[str], list[str]]:
    """보존 사례: (실제 회귀, 검토 필요한 변경)."""
    regressions, reviews = [], []
    old_turns, new_turns = _turns(expected), _turns(actual)
    if len(old_turns) != len(new_turns):
        regressions.append(f"사용자 턴 수가 다름(main {len(old_turns)}, 현재 {len(new_turns)})")
    for number, (old, new) in enumerate(zip(old_turns, new_turns), 1):
        label = f"턴{number}({old['op']})"
        added = _problems(new) - _problems(old)
        regressions += [f"{label} {problem}" for problem in sorted(added)]
        if old["op"] == "export":
            old_numbers, old_texts = _split_excel(old["first"].get("excel") or {})
            new_numbers, new_texts = _split_excel(new["first"].get("excel") or {})
            if old_numbers != new_numbers:
                regressions.append(f"{label} Excel 숫자 다름")
            if old_texts != new_texts:
                reviews.append(f"{label} Excel 글자 다름")
            continue
        old_final, new_final = _final(old), _final(new)
        if _status(old_final) in TERMINAL and _status(new_final) not in TERMINAL:
            regressions.append(f"{label} 완료 결과 누락(main {_status(old_final)}, 현재 {_status(new_final)})")
        old_groups, new_groups = _groups(old_final), _groups(new_final)
        for group, name in (("selection", "최종 상태·선택 공종"), ("inputs", "최종 입력·단위·출처"),
                            ("calc", "최종 계산 금액"), ("citations", "최종 근거 인용")):
            if old_groups[group] != new_groups[group]:
                regressions.append(f"{label} {name} 다름")
        if len(old["auto"]) != len(new["auto"]):
            reviews.append(f"{label} 질문 응답 횟수 main {len(old['auto'])}회, 현재 {len(new['auto'])}회")
        required = _required_choices(old)
        offered = {choice for step in [new["first"], *new["auto"]] for choice in (_groups(step)["work_choices"] or [])}
        lost = sorted(required - offered)
        if lost:
            regressions.append(f"{label} 필수 공종 후보 누락: {lost}")
        old_first, new_first = _groups(old["first"]), _groups(new["first"])
        if old_first["work_choices"] != new_first["work_choices"]:
            removed = sorted(set(old_first["work_choices"] or []) - set(new_first["work_choices"] or []))
            added_choices = sorted(set(new_first["work_choices"] or []) - set(old_first["work_choices"] or []))
            reviews.append(f"{label} 후보 표시 변경(필수 후보 {sorted(required) or '없음'} 유지) 빠짐={removed} 추가={added_choices}")
        for group, name in (("selection", "중간 상태"), ("questions", "질문 이름·순서"), ("text", "문구")):
            if old_first[group] != new_first[group]:
                reviews.append(f"{label} {name} 다름")
    return regressions, reviews


def _codes(texts, codes) -> list[str]:
    joined = " ".join(str(text) for text in texts or [])
    return [code for code in codes if re.search(rf"(?<![\d-]){re.escape(code)}(?![\d-])", joined)]


def judge_main_bug(check: dict, expected: list, actual: list) -> tuple[str, str]:
    """main 오동작 사례: 해결 / 미해결 / 악화 / 판단 불가."""
    old_turns, new_turns = _turns(expected), _turns(actual)
    problems = set().union(*(_problems(turn) for turn in new_turns)) - set().union(*(_problems(turn) for turn in old_turns))
    if problems:
        return "악화", f"새 문제: {sorted(problems)}"
    first = new_turns[0]["first"].get("response") or {}
    final = _final(new_turns[-1]).get("response") or {}
    kind = check["type"]
    if kind == "consult":
        if not check.get("expect_sections"):
            return "판단 불가", check.get("why", "기대 근거 미정")
        routed = first.get("route") == "qa" and first.get("status") == "ANSWERED" and not first.get("questions")
        sections = (first.get("qa") or {}).get("sections") or []
        if routed and _codes(sections, check["expect_sections"]):
            return "해결", f"상담 경로, 기대 근거 {check['expect_sections']} 포함"
        if routed:
            return "미해결", f"상담 경로지만 기대 근거 {check['expect_sections']} 없음: {sections}"
        return "미해결", f"상담 경로 아님({first.get('route')}/{first.get('status')})"
    if kind == "out_of_scope":
        return ("해결", "범위 밖 안내") if first.get("status") == "OUT_OF_SCOPE" else \
               ("미해결", f"{first.get('route')}/{first.get('status')}")
    if kind == "work_choice":
        choices = _groups(new_turns[0]["first"])["work_choices"] or []
        has, bad = _codes(choices, check["expect_any"]), _codes(choices, check.get("forbid", []))
        extra = check.get("work_only") and [q["name"] for q in first.get("questions", []) if q["name"] != "work"]
        if first.get("status") == "MISSING_INFO" and has and not bad and not extra:
            return "해결", f"공종 확인 질문, 기대 후보 {has} 포함"
        return "미해결", f"상태={first.get('status')} 기대 후보={has or '없음'} 무관 후보={bad or '없음'} 함께 묻는 조건={extra or '없음'}"
    if kind == "recalc":
        choices = _groups(new_turns[0]["first"])["work_choices"] or []
        if choices:
            return "악화", f"직전 견적 없이 관련 없는 후보 제시: {[c[:20] for c in choices]}"
        if first.get("route") == "estimate" and first.get("status") in ("MISSING_INFO", "EVIDENCE_ONLY"):
            return "해결", "견적으로 받고 공종 확인 안내"
        return "미해결", f"{first.get('route')}/{first.get('status')}"
    if kind == "no_zero_estimate":
        amount = ((final.get("statement") or {}).get("totals") or {}).get("contract_amount")
        if final.get("status") == "PARTIAL" and not amount:
            return "미해결", "여전히 0원 부분 견적"
        return "해결", f"최종 상태 {final.get('status')}, 도급액 {amount}"
    return "판단 불가", f"알 수 없는 판정 기준: {kind}"


def _self_test() -> list[str]:
    """비교 로직 자체 점검: 완료 결과 누락·반복 질문·실행 오류·필수 후보 누락은 회귀, 질문 횟수·후보 표시는 검토."""
    def step(op, status, questions=(), choices=None, total=None):
        qs = [{"name": "work", "ask": "", "choices": choices, "default": None}] if choices else []
        qs += [{"name": name, "ask": "", "choices": None, "default": None} for name in questions]
        statement = {"status": status, "totals": {"contract_amount": total}, "lines": []} if total else None
        return {"op": op, "response": {"status": status, "route": "estimate", "questions": qs, "statement": statement}}
    done = step({"answers": {"x": 1}}, "PARTIAL", total=100)
    asked = step({"message": "q"}, "MISSING_INFO", ["x"])
    failures = []
    regressions, _ = compare_preserve([asked, done], [asked])
    if not any("완료 결과 누락" in r for r in regressions):
        failures.append("완료 결과 누락을 잡지 못함")
    regressions, _ = compare_preserve([asked, done], [asked, step({"answers": {"x": 1}}, "MISSING_INFO", ["x"])])
    if not any("반복 질문" in r for r in regressions):
        failures.append("반복 질문을 잡지 못함")
    regressions, _ = compare_preserve([asked, done], [asked, {"op": {"answers": {"x": 1}}, "error": "boom"}])
    if not any("실행 오류" in r for r in regressions):
        failures.append("실행 오류를 잡지 못함")
    two = step({"answers": {"y": 1}}, "MISSING_INFO", ["y"])
    regressions, reviews = compare_preserve([asked, done], [asked, two, done])
    if regressions or not any("응답 횟수" in r for r in reviews):
        failures.append("질문 횟수 차이를 회귀로 처리함")
    pick = step({"message": "q"}, "MISSING_INFO", choices=["A", "B", "C"])
    chose = step({"answers": {"work": "A"}}, "PARTIAL", total=100)
    regressions, reviews = compare_preserve([pick, chose], [step({"message": "q"}, "MISSING_INFO", choices=["A"]), chose])
    if regressions or not any("후보 표시 변경" in r for r in reviews):
        failures.append("필수 후보를 유지한 후보 축소를 회귀로 처리함")
    regressions, _ = compare_preserve([pick, chose], [step({"message": "q"}, "MISSING_INFO", choices=["B"]), chose])
    if not any("필수 공종 후보 누락" in r for r in regressions):
        failures.append("필수 후보 누락을 잡지 못함")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh-main", action="store_true")
    args = parser.parse_args()
    out_dir = ROOT / "tmp/baseline-run"
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.refresh_main:
        _prepare_main()
        _run(BASELINE_ROOT, FIXTURE, "--capture-checkpoints", str(CHECKPOINT))
        print(f"기준 파일 갱신: {FIXTURE.relative_to(ROOT)}")
        return 0

    self_failures = _self_test()
    baseline = json.loads(FIXTURE.read_text(encoding="utf-8"))
    current = _run(ROOT, out_dir / "current.json", "--resume-checkpoints", str(CHECKPOINT))
    scenarios = {s["id"]: s for s in json.loads(SCENARIOS.read_text(encoding="utf-8"))["scenarios"]}
    print(f"기준: main {COMMIT} ({baseline['meta']['code_root']}) / 현재: {current['meta']['code_root']}")
    same_data = baseline["meta"]["data_sha256"] == current["meta"]["data_sha256"]
    print(f"검색 데이터·제비율·색인 설정 해시 동일: {same_data} / 기준일 {baseline['meta']['environment']['basis_date']}")

    preserve, bugs = {}, {}
    for sid, scenario in scenarios.items():
        expected = baseline["results"][sid]
        actual = current["results"].get(sid, [{"op": {}, "error": "결과 없음"}])
        if scenario["expect"] == "preserve":
            regressions, reviews = compare_preserve(expected, actual)
            preserve[sid] = ("실제 회귀" if regressions else "검토 필요한 변경" if reviews else "동일", regressions, reviews)
        else:
            bugs[sid] = judge_main_bug(scenario["fix_check"], expected, actual)

    order = ("동일", "검토 필요한 변경", "실제 회귀")
    counts = {label: sum(1 for value in preserve.values() if value[0] == label) for label in order}
    print(f"\n[보존 사례 {len(preserve)}개] " + " / ".join(f"{label} {counts[label]}" for label in order))
    for sid, (label, regressions, reviews) in preserve.items():
        if label != "동일":
            print(f"  {label}: {sid}")
            for line in regressions:
                print(f"      회귀  {line}")
            for line in reviews:
                print(f"      검토  {line}")
    bug_order = ("해결", "미해결", "악화", "판단 불가")
    bug_counts = {label: sum(1 for value in bugs.values() if value[0] == label) for label in bug_order}
    print(f"\n[main 오동작 {len(bugs)}개] " + " / ".join(f"{label} {bug_counts[label]}" for label in bug_order))
    for label in bug_order:
        for sid, (verdict, why) in bugs.items():
            if verdict == label:
                print(f"  {label:5} {sid}: {why}")

    old_cp, new_cp = baseline.get("checkpoints", {}), current.get("checkpoints", {})
    checkpoint_ok = "error" not in new_cp and new_cp.get("resumed_totals") == old_cp.get("resumed_totals")
    print(f"\n[기존 체크포인트 호환] {'main 체크포인트를 같은 금액으로 재개' if checkpoint_ok else new_cp}")
    print(f"[비교 로직 자체 점검] {'통과' if not self_failures else self_failures}")
    (out_dir / "report.json").write_text(json.dumps({"preserve": preserve, "main_bug": bugs}, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
    failed = counts["실제 회귀"] or self_failures or not same_data or not checkpoint_ok
    print(f"\n판정: {'실패' if failed else '통과'} (보존 사례 실제 회귀 {counts['실제 회귀']}건 기준. main 오동작 결과는 통과 여부에 넣지 않음)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
