"""6-1-1 일위대가(노무비) 도구 점검. API·DB 없이 data/processed의 청크·레코드만 읽는다.

실행: python evals/check_unit_price.py
아래 단가는 계산 검증용 가상값이다. 실제 노임단가가 아니며 어디에도 기본값으로 쓰지 않는다.
"""

import json
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent" / "flow"))
sys.path.insert(0, str(ROOT / "agent" / "search"))
sys.path.insert(0, str(ROOT / "agent" / "calc"))
from unit_price import UNCALCULATED, RateError, calculate, load_rates, parse_rates, safe_console  # noqa: E402

TEST_SOURCE = "테스트용 가상값(실제 노임단가 아님)"


def entry(trade, price, date="2000-01-01", source=TEST_SOURCE):
    return {"trade": trade, "unit_price": price, "unit": "원/인·일", "basis_date": date, "source": source}


def by_trade(result):
    return {i["trade"]: i for i in result["items"]}


def main() -> int:
    safe_console()
    checks = []

    def check(name, ok, detail=""):
        checks.append(ok)
        print(f"{'PASS' if ok else 'FAIL'} {name}" + (f": {detail}" if detail else ""))

    # 1. 단가 없음 → 전 직종 미산정, 합계 없음. 노무량·출처 연결은 그대로
    r = calculate({})
    items = by_trade(r)
    check("단가 없음: 전 직종 미산정", all(i["status"] == UNCALCULATED and i["amount"] is None for i in r["items"])
          and r["labor_total"] is None and r["labor_total_status"] == UNCALCULATED)
    check("노무량 15인·일 유지(기존 결과)", all(i["person_days"] == Decimal(15) for i in r["items"])
          and set(items) == {"콘크리트공", "보통인부"})
    check("1㎥당 노무량 0.15인 (3인 ÷ 20㎥)", all(i["person_days_per_m3"] == Decimal("0.15") for i in r["items"]))
    check("원문 표 p185-t0이 검색 근거에 포함, 쪽 185 일치, 기준 (일당), 구조 ok",
          all(c["table_chunk"] == "p185-t0" and c["in_search_evidence"] and c["page_matches_case"]
              and c["basis"] == "(일당)" and c["structure"] == "ok" for c in r["source_checks"]),
          str(r["search"]["top3"]))
    check("노무량 출처에 절·쪽·표 bbox", all("6-1-1 | PDF 185쪽 | 표 p185-t0 bbox" in i["labor_source"]
                                         for i in r["items"]))
    check("공구손료 2% 조건은 원문 인용으로 미적용 표시",
          any("공구손료" in u["text"] and "2%" in u["text"] and u["status"] == "미적용" for u in r["unapplied_conditions"]))

    # 2. 빈 양식 파일 → 미산정
    r = calculate(load_rates(ROOT / "evals/labor_rates.template.json"))
    check("빈 양식: 전 직종 미산정(단가 없음)", all(i["status"] == UNCALCULATED and i["reason"] == "단가 없음"
                                             for i in r["items"]))

    # 3. 두 직종 모두 가상 단가 → 금액·합계
    r = calculate(parse_rates({"rates": [entry("콘크리트공", "1000"), entry("보통인부", "2000")]}))
    items = by_trade(r)
    check("금액 = 노무량 × 단가", items["콘크리트공"]["amount"] == Decimal(15000)
          and items["보통인부"]["amount"] == Decimal(30000))
    check("합계와 1㎥당 합계", r["labor_total"] == Decimal(45000) and r["labor_total_per_m3"] == Decimal(450)
          and r["labor_total_status"] == "완료")
    check("기준일·출처 전달", all(i["basis_date"] == "2000-01-01" and i["price_source"] == TEST_SOURCE
                              for i in r["items"]))

    # 4. 한 직종만 → 부분 합계, 나머지 미산정
    r = calculate(parse_rates({"rates": [entry("콘크리트공", "1000")]}))
    check("부분 합계: 미산정 직종 제외 표시", r["labor_total_status"] == "부분" and r["labor_total"] == Decimal(15000)
          and r["excluded_uncalculated"] == ["보통인부"])

    # 5. 기준일·출처 없는 단가는 쓰지 않는다
    r = calculate(parse_rates({"rates": [entry("콘크리트공", "1000", date=""), entry("보통인부", "2000", source="")]}))
    items = by_trade(r)
    check("기준일 없음 → 미산정", items["콘크리트공"]["status"] == UNCALCULATED and "기준일" in items["콘크리트공"]["reason"])
    check("출처 없음 → 미산정", items["보통인부"]["status"] == UNCALCULATED and "출처" in items["보통인부"]["reason"])

    # 6. Decimal 정확성: JSON 숫자도 float을 거치지 않는다 (float이면 0.1 × 15 = 1.5000000000000002)
    data = json.loads('{"rates": [{"trade": "콘크리트공", "unit_price": 0.1, "basis_date": "2000-01-01", "source": "t"},'
                      ' {"trade": "보통인부", "unit_price": "12,345.67", "basis_date": "2000-01-01", "source": "t"}]}',
                      parse_float=Decimal, parse_int=Decimal)
    items = by_trade(calculate(parse_rates(data)))
    check("Decimal: 0.1 × 15 = 1.5 정확", items["콘크리트공"]["amount"] == Decimal("1.5"))
    check("Decimal: 12,345.67 × 15 = 185,185.05 정확", items["보통인부"]["amount"] == Decimal("185185.05"))

    # 7. 잘못된 단가 입력은 계산하지 않고 거부
    bad = {"음수": [entry("콘크리트공", "-1")], "0": [entry("콘크리트공", "0")], "문자": [entry("콘크리트공", "만원")],
           "중복": [entry("콘크리트공", "1"), entry("콘크리트공", "2")],
           "단위": [{**entry("콘크리트공", "1"), "unit": "원/시간"}], "무한": [entry("콘크리트공", "Infinity")]}
    for name, rates in bad.items():
        try:
            parse_rates({"rates": rates})
            check(f"잘못된 입력 거부: {name}", False)
        except RateError:
            check(f"잘못된 입력 거부: {name}", True)

    # 8. 품량은 calc/quantity.py에서 받고, 계산 모듈 사이에 순환 참조가 없다
    import copy
    import subprocess

    import quantity
    from unit_price import apply_prices, quantity_conditions

    r = calculate({})
    check("품량 출처: calc/quantity.py 결과(골든 사례 ID, per_day)", r["quantity"]["calculator"] == "agent/calc/quantity.py"
          and r["quantity"]["case_id"] == "6-1-1-manual-reinforced-100m3" and r["quantity"]["rule"] == "per_day"
          and all(i["quantity_exact"] == "15" for i in r["items"]))
    for order in (["inputs", "quantity", "unit_price"], ["unit_price", "quantity"], ["quantity_node"]):
        code = ("import sys; sys.path[:0]=[r'%s', r'%s', r'%s']; " % tuple(str(ROOT / "agent" / s) for s in ("flow", "search", "calc"))
                + "; ".join(f"import {m}" for m in order))
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True)
        check(f"순환 참조 없음: {' → '.join(order)} 순서로 import", proc.returncode == 0, proc.stderr.decode("utf-8", "replace")[-200:])
    # 9. 순환소수도 거부·반올림 없이 정확히 계산 (실제 원문 6-1-1 장비사용 타설 행: 시공량 55, 콘크리트공 3·보통인부 1)
    #    운영 지원 목록·사례 정의는 바꾸지 않고, 검사에서만 사본 정답 목록과 사례 정의를 넘긴다
    from fractions import Fraction

    from unit_price import SUPPORTED_CASE, report, to_json

    test_case = {**SUPPORTED_CASE, "method": "장비사용 타설"}
    test_golden = copy.deepcopy(quantity.load_golden())
    test_golden["cases"].append({"id": "test-only-equipment", "section_no": "6-1-1",
                                 "conditions": quantity_conditions(test_case),
                                 "human_review": {"원문 대조": "미완료", "실무 검토": "미완료"}})
    rates12 = parse_rates({"rates": [entry("콘크리트공", "1000"), entry("보통인부", "2000")]})

    def priced(volume, rates):
        labor = quantity.compute("6-1-1", quantity_conditions(test_case), volume, golden=test_golden)
        return apply_prices(labor, rates, case=test_case)

    r = priced("55", rates12)
    it = by_trade(r)
    ex = it["콘크리트공"]["exact"]
    check("55㎥ ÷ 55㎥/일 × 3인 = 정확히 3인·일 (1㎥당 3/55가 순환소수여도 거부하지 않음)",
          ex["person_days"]["exact"] == "3" and it["콘크리트공"]["person_days"] == Decimal(3)
          and ex["person_days_per_m3"]["exact"] == "3/55" and ex["person_days_per_m3"]["display"] == "0.0(54)")
    check("55㎥: 금액 정확값 3000·2000, 합계 5000, 1㎥당 합계 1000/11 (= 90.(90))",
          ex["amount"]["exact"] == "3000" and it["보통인부"]["exact"]["amount"]["exact"] == "2000"
          and r["labor_total"] == Decimal(5000) and r["exact"]["labor_total"]["exact"] == "5000"
          and r["exact"]["labor_total_per_m3"]["exact"] == "1000/11" and r["exact"]["labor_total_per_m3"]["display"] == "90.(90)")
    check("55㎥: 순환소수 값의 기존 Decimal 필드는 None, 정확값은 exact에", it["콘크리트공"]["person_days_per_m3"] is None
          and r["labor_total_per_m3"] is None and it["콘크리트공"]["amount_per_m3"] is None)

    r = priced("100", rates12)
    it = by_trade(r)
    c, b = it["콘크리트공"]["exact"], it["보통인부"]["exact"]
    check("100㎥ ÷ 55㎥/일 × 3인 = 60/11인·일, 보통인부 20/11인·일",
          c["person_days"]["exact"] == "60/11" and c["person_days"]["display"] == "5.(45)"
          and b["person_days"]["exact"] == "20/11")
    check("60/11 × 1,000 = 60000/11원, 20/11 × 2,000 = 40000/11원, 합계 100000/11원 (정확값)",
          Fraction(c["amount"]["exact"]) == Fraction(60, 11) * 1000 and c["amount"]["exact"] == "60000/11"
          and b["amount"]["exact"] == "40000/11" and r["exact"]["labor_total"]["exact"] == "100000/11"
          and r["exact"]["labor_total"]["display"] == "9090.(90)" and r["labor_total"] is None)
    check("표시·적용 금액은 정하지 않음(값 없음, 정책 미정)", r["amount_policy"]["display_and_applied_amount"] == "미정"
          and all(i["applied_amount"] == {"value": None, "policy": "미정"} for i in r["items"]))
    text = report(r)
    check("사람용 출력: 반올림 없이 '분수 (= 순환소수)'로 표시하고 미산정으로 오표시하지 않음",
          "60000/11 (= 5454.(54)) 원" in text and "100000/11 (= 9090.(90)) 원" in text and "합계: 미산정" not in text)
    back = json.loads(to_json(r, ascii_only=True))
    check("JSON: 순환소수 정확값이 문자열로 왕복", back["exact"]["labor_total"]["exact"] == "100000/11"
          and back["items"][0]["exact"]["amount"]["numerator"] == "60000" and back["labor_total"] is None)

    r = priced("100", {})
    it = by_trade(r)
    check("단가 없음: 금액은 미산정이어도 정확한 품량 60/11·20/11은 반환",
          r["labor_total_status"] == UNCALCULATED and r["exact"]["labor_total"] is None
          and it["콘크리트공"]["exact"]["person_days"]["exact"] == "60/11"
          and it["보통인부"]["exact"]["person_days"]["exact"] == "20/11" and it["콘크리트공"]["amount"] is None)

    labor = quantity.compute("6-1-1", quantity_conditions(test_case), "100", golden=test_golden)
    try:
        apply_prices(labor, rates12)
        check("운영 경로(기본 사례)는 장비사용 품량을 받지 않음", False)
    except RuntimeError as exc:
        check("운영 경로(기본 사례)는 장비사용 품량을 받지 않음", "지원 사례가 아닌" in str(exc))
    check("운영 정답 목록·사례 정의는 그대로(장비사용 미등록, 인력운반·철근구조물만)",
          SUPPORTED_CASE["method"] == "인력운반 타설" and not any(
              c["conditions"].get("공법") == "장비사용 타설" for c in quantity.load_golden()["cases"]))

    # 10. 기존 끝나는 소수 결과의 필드·값 호환 (6-1-1 골든 사례)
    r = calculate(rates12)
    it = by_trade(r)
    legacy_keys = {"trade", "person_days", "crew", "daily_output_m3", "person_days_per_m3", "unit_price", "price_unit",
                   "basis_date", "price_source", "labor_source", "labor_row", "amount", "amount_per_m3", "status"}
    check("기존 필드 유지·값 동일(15, 0.15, 15000·30000, 합계 45000, 1㎥당 450)",
          all(legacy_keys <= set(i) for i in r["items"]) and it["콘크리트공"]["person_days"] == Decimal(15)
          and it["콘크리트공"]["person_days_per_m3"] == Decimal("0.15") and it["콘크리트공"]["amount"] == Decimal(15000)
          and it["보통인부"]["amount"] == Decimal(30000) and r["labor_total"] == Decimal(45000)
          and r["labor_total_per_m3"] == Decimal(450) and r["exact"]["labor_total"]["exact"] == "45000")
    check("기존 JSON 표기 유지(Decimal 문자열 '15', '0.15', '15000', '45000')",
          (lambda j: j["items"][0]["person_days"] == "15" and j["items"][0]["person_days_per_m3"] == "0.15"
           and j["items"][0]["amount"] == "15000" and j["labor_total"] == "45000")(json.loads(to_json(r))))
    try:
        apply_prices({"status": "refused", "reason": "테스트"}, {})
        check("거부된 품량 결과에는 단가를 적용하지 않음", False)
    except RuntimeError as exc:
        check("거부된 품량 결과에는 단가를 적용하지 않음", "품량을 계산하지 못했습니다" in str(exc))

    print(f"\n통과 {sum(checks)} / 전체 {len(checks)} (가상 단가로 계산만 검증. 실제 금액 아님)")
    return 0 if all(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
