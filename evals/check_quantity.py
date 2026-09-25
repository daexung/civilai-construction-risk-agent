"""품량 계산기(agent/calc/quantity.py) 점검. API·LLM·단가 없이 data/processed의 레코드·청크만 읽는다.

실행: python evals/check_quantity.py
정답: evals/golden_quantity.json (6-1-2는 원문 이미지 전사, 사람 검토 미완료), 6-1-1은 evals/golden_estimate.json.
"""

import copy
import json
import os
import subprocess
import sys
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent" / "flow"))
sys.path.insert(0, str(ROOT / "agent" / "search"))
sys.path.insert(0, str(ROOT / "agent" / "calc"))
import quantity  # noqa: E402
from quantity import USER_INPUT, compute, decimal_text, load_golden, load_sources, table_model  # noqa: E402
from rag import estimate_labor  # noqa: E402
from unit_price import safe_console  # noqa: E402

GOLDEN_ESTIMATE = json.loads((ROOT / "evals/golden_estimate.json").read_text(encoding="utf-8"))
SMALL = {"유형": "기계비빔타설", "구조물": "소형구조물"}
KEY = "small_structure_scattered"


def by_name(result):
    return {line["name"]: line for line in result["lines"]}


def exact(line) -> Fraction:
    return Fraction(line["quantity"]["exact"])


def with_case(golden, section_no, conditions):
    """운영 정답 목록은 두고, 검사용 사본에만 조합을 더한다."""
    g = copy.deepcopy(golden)
    g["cases"].append({"id": "test-only", "section_no": section_no, "conditions": conditions,
                       "human_review": {"원문 대조": "미완료", "실무 검토": "미완료"}})
    return g


def run_cli(args, encoding="cp949"):
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONIOENCODING", "PYTHONUTF8")}
    env["PYTHONIOENCODING"] = encoding
    return subprocess.run([sys.executable, "agent/calc/quantity.py", *args], cwd=ROOT, env=env, capture_output=True)


def main() -> int:
    safe_console()
    golden = load_golden()
    chunks, records = load_sources()
    results = []

    def check(name, ok, detail=""):
        results.append(bool(ok))
        print(f"{'PASS' if ok else 'FAIL'} {name}" + (f": {detail}" if detail and not ok else ""))

    # ---- 6-1-1 회귀 (기존 골든 사례, per_day) ----
    case = next(c for c in golden["cases"] if c["section_no"] == "6-1-1")
    r = compute("6-1-1", case["conditions"], case["work_quantity"])
    lines = by_name(r)
    check("6-1-1: 계산됨", r["status"] == "computed", r.get("reason"))
    check("6-1-1: golden_estimate의 기존 결과와 같음(각 15)",
          {k: exact(v) for k, v in lines.items()}
          == {k: Fraction(v) for k, v in GOLDEN_ESTIMATE["expected_person_days"].items()})
    old = {t: estimate_labor(chunks, records, "6-1-1", "인력운반 타설", t, "시공량(㎥) 철근구조물", "100")["person_days"]
           for t in lines}
    check("6-1-1: 기존 운영 경로(rag.estimate_labor)와 같음", all(Fraction(Decimal(old[t])) == exact(lines[t]) for t in lines))
    line = lines["콘크리트공"]
    check("6-1-1: 기준량 규칙 per_day, 기준 (일당), 인원 3·시공량 20",
          line["basis"] == {"rule": "per_day", "label": "(일당)", "crew": "3", "crew_unit": "인(작업조 인원)",
                            "daily_output": "20", "daily_output_unit": "㎥/일"})
    check("6-1-1: 계산식", line["formula"] == "100㎥ ÷ 20㎥/일 × 3인 = 15인·일")
    check("6-1-1: 원문 출처(절·쪽·표·bbox·행)", line["source"]["pdf_page"] == 185 and line["source"]["table_id"] == "p185-t0"
          and line["source"]["bbox"] and "인력운반 타설 | 콘크리트공" in line["source"]["row"])
    check("6-1-1: 원문 단위 '인'과 결과 단위 '인·일' 분리·해석 명시",
          line["source_unit"] == "인" and line["result_unit"] == "인·일" and "작업조 인원" in line["unit_interpretation"])
    check("6-1-1: 자동 검사 통과와 사람 검토 미완료가 별도", r["automated_check"] == "통과"
          and r["human_review"] == {"원문 대조": "미완료", "실무 검토": "미완료"}
          and line["validation"]["automated_check"] == "통과" and line["validation"]["human_review"]["실무 검토"] == "미완료")
    sep = " ".join(n["text"] for n in r["labor_scope"]["not_included_separate"])
    check("6-1-1: 양생·공구손료·경장비 등 별도 계상 항목을 포함하지 않음으로 표시(원문 인용)",
          "양생은 양생방법" in sep and "공구손료" in sep and "포함하지 않았다" in r["labor_scope"]["statement"])

    # ---- 6-1-2 원문 전사값과 파싱 표 대조 ----
    spec = quantity.SPECS["6-1-2"]
    table = next(c for c in chunks if c["kind"] == "table" and c["section_no"] == "6-1-2")
    parsed = {}
    for row in table_model(spec, table, records):
        for struct, values in row["columns"].items():
            parsed.setdefault(row["유형"], {}).setdefault(row["trade"], {})[struct] = values[0] if len(values) == 1 else values
    check("6-1-2: 파싱 표 12개 값이 원문 이미지 전사값과 같음", parsed == golden["tables"]["6-1-2"]["rates"])
    check("6-1-2: 표 구조 ok·기준 (㎥당)·PDF 185쪽", table["structure"] == "ok" and table["basis"] == "(㎥당)"
          and table["source"]["page"] == 185)
    check("6-1-2: 정답 사람 검토는 미완료로 유지", golden["tables"]["6-1-2"]["human_review"] == {"원문 대조": "미완료", "실무 검토": "미완료"}
          and all(c["human_review"]["원문 대조"] == "미완료" for c in golden["cases"] if c["section_no"] == "6-1-2"))

    # ---- 6-1-2 계산 사례 두 개 (per_unit) ----
    for case in [c for c in golden["cases"] if c["section_no"] == "6-1-2"]:
        r = compute("6-1-2", case["conditions"], case["work_quantity"])
        lines = by_name(r)
        check(f"{case['id']}: 기대값", r["status"] == "computed"
              and {k: exact(v) for k, v in lines.items()} == {k: Fraction(v) for k, v in case["expected"].items()},
              r.get("reason"))
        line = lines["콘크리트공"]
        rate = golden["tables"]["6-1-2"]["rates"][case["conditions"]["유형"]]["콘크리트공"][case["conditions"]["구조물"]]
        check(f"{case['id']}: 규칙 per_unit, 기준량 1㎥, 원문 수량", line["basis"]["rule"] == "per_unit"
              and line["basis"]["label"] == "(㎥당)" and line["basis"]["per"] == "1" and line["basis"]["per_unit"] == "㎥"
              and line["basis"]["rate"] == rate)
        check(f"{case['id']}: 계산식·출처·단위 해석", line["formula"] == f"{case['work_quantity']}㎥ ÷ 1㎥ × {rate}인 = "
              f"{case['expected']['콘크리트공']}인·일" and line["source"]["table_id"] == "p185-t1"
              and line["result_unit"] == "인·일" and "기준량(㎥)당 인력 품" in line["unit_interpretation"])
        check(f"{case['id']}: 사람 검토 미완료 유지", r["automated_check"] == "통과"
              and r["human_review"] == {"원문 대조": "미완료", "실무 검토": "미완료"})
        sep = " ".join(n["text"] for n in r["labor_scope"]["not_included_separate"])
        check(f"{case['id']}: 양생·장비 기계경비·운반비 별도 계상 표시(186쪽 [주])",
              "양생은" in sep and "기계경비는 별도 계상" in sep and "운반비를 별도 계상" in sep
              and all("PDF" in n["source"] for n in r["labor_scope"]["not_included_separate"]))
        q = line["quantity"]
        check(f"{case['id']}: 끝나는 소수는 정확값과 표시값이 같음", q["terminating"] and q["exact"] == q["display"])

    # ---- 거부: 추정하지 않음 ----
    refusals = [
        ("조건 누락(유형)", ("6-1-2", {"구조물": "철근구조물"}, "100"), "조건 '유형'이 없습니다"),
        ("원문 표에 없는 값", ("6-1-2", {"유형": "펌프타설", "구조물": "철근구조물"}, "100"), "원문 표에 없습니다"),
        ("6-1-1에 소형구조물", ("6-1-1", {"공법": "인력운반 타설", "구조물": "소형구조물"}, "100"), "원문 표에 없습니다"),
        ("표에 없는 조건 이름", ("6-1-2", {"유형": "기계비빔타설", "구조물": "철근구조물", "지역": "서울"}, "100"), "표에 없는 조건"),
        ("정답 사례 없는 조합(6-1-1 장비사용)", ("6-1-1", {"공법": "장비사용 타설", "구조물": "철근구조물"}, "100"), "정답 사례가 아직 없는"),
        ("정답 사례 없는 조합(6-1-2 기계비빔 무근)", ("6-1-2", {"유형": "기계비빔타설", "구조물": "무근구조물"}, "100"), "정답 사례가 아직 없는"),
        ("소형구조물: 확인값 없음", ("6-1-2", SMALL, "8"), "true가 필요"),
        ("물량 0", ("6-1-2", {"유형": "기계비빔타설", "구조물": "철근구조물"}, "0"), "0보다 커야"),
        ("물량 음수", ("6-1-2", {"유형": "기계비빔타설", "구조물": "철근구조물"}, "-3"), "양의 숫자"),
        ("물량 숫자 아님", ("6-1-2", {"유형": "기계비빔타설", "구조물": "철근구조물"}, "많이"), "양의 숫자"),
        ("지원하지 않는 절", ("6-4-1", {}, "10"), "지원하지 않는 절"),
    ]
    for name, (sec, cond, qty), expect in refusals:
        r = compute(sec, cond, qty)
        check(f"거부: {name}", r["status"] == "refused" and expect in r["reason"] and not r["lines"], r.get("reason"))
    r = compute("6-1-2", {"유형": "기계비빔타설", "구조물": "철근구조물"}, "100", unit="㎡")
    check("거부: 물량 단위 ㎡", r["status"] == "refused" and "단위" in r["reason"])
    r = compute("6-1-2", SMALL, "8")
    check("거부 사유에 원문 ② 조항 인용", "② 소형구조물은" in r["reason"] and "PDF 186쪽" in r["reason"])

    # ---- 원문·파싱 상태 이상은 거부 (주입한 사본으로 확인) ----
    def mutated(fn):
        cs, rs = copy.deepcopy(chunks), copy.deepcopy(records)
        fn(cs, rs)
        return cs, rs

    def set_chunk(cs, key, value):
        next(c for c in cs if c["chunk_id"] == "p185-t1")[key] = value

    def set_value(rs, index, old, new):
        rs[index]["text"] = rs[index]["text"].replace(old, new)

    cases = [
        ("표 구조 uncertain", lambda cs, rs: set_chunk(cs, "structure", "uncertain"), "구조가 불확실"),
        ("기준 표기 없음", lambda cs, rs: set_chunk(cs, "basis", None), "기준 표기"),
        ("같은 조건 행 중복", lambda cs, rs: next(c for c in cs if c["chunk_id"] == "p185-t1")["record_ids"].append(11), "원문 행이 2개"),
        ("값이 숫자 아님", lambda cs, rs: set_value(rs, 11, "수량 철근구조물 0.17", "수량 철근구조물 -"), "하나의 숫자가 아닙니다"),
        ("값이 0", lambda cs, rs: set_value(rs, 11, "수량 철근구조물 0.17", "수량 철근구조물 0"), "0보다 크지 않습니다"),
    ]
    for name, fn, expect in cases:
        r = compute("6-1-2", {"유형": "기계비빔타설", "구조물": "철근구조물"}, "100", sources=mutated(fn))
        check(f"거부(원문 상태): {name}", r["status"] == "refused" and expect in r["reason"], r.get("reason"))

    # ---- 문제 1 재현: 끝나지 않는 소수도 정확한 품량으로 보존 ----
    check("표시값: 순환소수 괄호 표기(반올림 없음)",
          [decimal_text(Fraction(x)) for x in ("1/3", "1/6", "22/7", "85/8", "15")]
          == ["0.(3)", "0.1(6)", "3.(142857)", "10.625", "15"])
    eq = {"공법": "장비사용 타설", "구조물": "철근구조물"}
    r = compute("6-1-1", eq, "100", golden=with_case(golden, "6-1-1", eq))
    lines = by_name(r)
    check("재현: 100㎥ ÷ 55㎥/일 × 3인 = 60/11인·일을 거부하지 않음(실제 원문 값 55)", r["status"] == "computed"
          and lines["콘크리트공"]["basis"]["daily_output"] == "55" and lines["콘크리트공"]["basis"]["crew"] == "3", r.get("reason"))
    q = lines.get("콘크리트공", {}).get("quantity", {})
    check("재현: 정확값 60/11(기약분수)과 표시값 5.(45)를 구분해 기록",
          q.get("exact") == "60/11" and q.get("numerator") == "60" and q.get("denominator") == "11"
          and q.get("terminating") is False and q.get("display") == "5.(45)")
    check("재현: 정확값을 되돌리면 원래 식과 같음(60/11 × 55 ÷ 3 = 100)", Fraction(q.get("exact", "0")) * 55 / 3 == 100)
    check("재현: 보통인부 100 ÷ 55 × 1 = 20/11 (표시 1.(81))",
          lines.get("보통인부", {}).get("quantity", {}).get("exact") == "20/11"
          and lines["보통인부"]["quantity"]["display"] == "1.(81)")
    check("재현: 계산식에 정확값과 표시값", lines.get("콘크리트공", {}).get("formula") == "100㎥ ÷ 55㎥/일 × 3인 = 60/11 (= 5.(45))인·일")
    check("재현: 반올림 규칙을 정하지 않았음을 결과에 명시", "금액 반올림 규칙은 정하지 않았다" in r.get("rounding", ""))
    r = compute("6-1-1", eq, "100")
    check("재현: 운영 정답 목록에는 없어 6-1-1 장비사용은 여전히 계산하지 않음", r["status"] == "refused"
          and "정답 사례가 아직 없는" in r["reason"])
    r = compute("6-1-1", {"공법": "인력운반 타설", "구조물": "철근구조물"}, "1", sources=mutated(
        lambda cs, rs: [set_value(rs, i, "철근구조물 20", "철근구조물 3") for i in (2, 3)]))
    check("재현: 이전에 거부하던 1㎥ ÷ 3㎥/일 × 3인도 정확히 1인·일", r["status"] == "computed"
          and all(exact(line) == 1 for line in r["lines"]), r.get("reason"))

    # ---- 문제 2 재현: 소형구조물 확인은 명시적 불리언만 ----
    g_small = with_case(golden, "6-1-2", SMALL)
    for name, value, expect in [("부정문 '소형구조물 아님'", "소형구조물 아님", "true 또는 false"),
                                ("긍정 문장도 문장이면 불가", "소형구조물 적용 조건에 해당함", "true 또는 false"),
                                ("숫자 1", 1, "true 또는 false"),
                                ("문자열 'true'", "true", "true 또는 false"),
                                ("false", False, "false라")]:
        r = compute("6-1-2", SMALL, "8", confirmations={KEY: value}, golden=g_small)
        check(f"재현: 소형구조물 확인값 {name} → 승인되지 않음", r["status"] == "refused" and expect in r["reason"], r.get("reason"))
    r = compute("6-1-2", SMALL, "8", confirmations={"small_structure": True}, golden=g_small)
    check("재현: 모르는 확인 항목 키 → 거부", r["status"] == "refused" and "알 수 없는 확인 항목" in r["reason"])
    r = compute("6-1-2", SMALL, "8", confirmations={KEY: True}, golden=g_small)
    user = [c for c in r.get("condition_records", []) if c["source"] == USER_INPUT]
    check("소형구조물: 확인값 true면 계산(8㎥ × 0.24 = 1.92), 조건 출처 '사용자 입력'", r["status"] == "computed"
          and exact(by_name(r)["콘크리트공"]) == Fraction("1.92") and user and user[0]["confirmation_key"] == KEY
          and user[0]["value"] is True and "② 소형구조물은" in user[0]["original_clause"]["text"], r.get("reason"))
    check("소형구조물: 확인한 ② 조항은 '반영하지 않은 조건'에서 빠짐",
          not any("② 소형구조물은" in n["text"] for n in r.get("labor_scope", {}).get("conditional_not_applied", [])))
    r = compute("6-1-2", SMALL, "8", confirmations={KEY: True})
    check("소형구조물: 운영 정답 목록에는 없어 아직 계산하지 않음", r["status"] == "refused" and "정답 사례가 아직 없는" in r["reason"])
    r = compute("6-1-2", {"유형": "기계비빔타설", "구조물": "철근구조물"}, "100", confirmations={KEY: True})
    check("확인 항목은 해당 조건이 아니면 결과에 사용자 조건으로 넣지 않음", r["status"] == "computed"
          and not [c for c in r["condition_records"] if c["source"] == USER_INPUT])
    base = ["--section", "6-1-2", "--cond", "유형=기계비빔타설", "--cond", "구조물=소형구조물", "--quantity", "8"]
    bad = run_cli(base + ["--confirm", f"{KEY}=소형구조물아님"])
    check("재현(명령줄): --confirm 값이 true/false가 아니면 오류(exit 2)", bad.returncode == 2)
    ok = run_cli(base + ["--confirm", f"{KEY}=true", "--json"])
    got = json.loads(ok.stdout.decode("cp949")) if ok.stdout else {}
    check("명령줄: --confirm 키=true는 불리언 true로 전달(운영 목록에 없어 정답 사례 거부)", ok.returncode == 3
          and got.get("confirmations") == {KEY: True} and "정답 사례가 아직 없는" in got.get("reason", ""))

    # ---- cp949 콘솔 --json 왕복 ----
    args = ["--section", "6-1-2", "--cond", "유형=기계비빔타설", "--cond", "구조물=철근구조물", "--quantity", "100", "--json"]
    proc = run_cli(args)
    got = json.loads(proc.stdout.decode("cp949")) if proc.returncode == 0 else None
    want = json.loads(json.dumps(compute("6-1-2", {"유형": "기계비빔타설", "구조물": "철근구조물"}, "100")))
    check("--json: cp949 콘솔에서도 ASCII 출력, json.loads 왕복 값 동일", proc.returncode == 0
          and all(b < 128 for b in proc.stdout) and got == want)

    print(f"\n통과 {sum(results)} / 전체 {len(results)} (API·LLM·단가 없음. 6-1-2 정답은 사람 검토 미완료)")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
