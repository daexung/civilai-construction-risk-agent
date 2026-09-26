"""--json 출력 왕복 검사: 콘솔 인코딩이 cp949여도 json.loads 결과에서 한글·특수문자가 '?'로 바뀌지 않는지.

실행: python evals/check_json_output.py
자식 프로세스의 출력 인코딩을 cp949로 고정해(PYTHONIOENCODING=cp949) agent/calc/unit_price.py와
agent/flow/agent.py(--offline, API 호출 없음)를 --json으로 실행한다. 받은 바이트를 cp949로 풀어 json.loads한 값이
같은 계산을 프로세스 안에서 한 결과와 똑같아야 한다. 일반(사람용) 출력도 cp949에서 멈추지 않는지 본다.
단가는 계산 검증용 가상값이다(실제 노임단가 아님).
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent" / "flow"))
sys.path.insert(0, str(ROOT / "agent" / "search"))
sys.path.insert(0, str(ROOT / "agent" / "calc"))
from agent import answer  # noqa: E402
from unit_price import calculate, calculate_case, load_rates, parse_volume, safe_console, to_json  # noqa: E402

# cp949에 없는 글자(①·∼·㎥ 일부 조합, 줄표)를 일부러 넣어 원문 특수문자 보존을 확인한다
SPECIAL_SOURCE = "테스트용 가상값(실제 노임단가 아님) ① 150∼200㎥ — ‘인용’"
QUERY = "철근구조물 150㎥를 레미콘 인력운반 타설하면 노무비는 얼마야?"


def run(args: list[str]) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONIOENCODING", "PYTHONUTF8")}
    env["PYTHONIOENCODING"] = "cp949"
    return subprocess.run([sys.executable, *args], cwd=ROOT, env=env, capture_output=True)


def expected(obj) -> object:
    """프로세스 안 결과를 같은 JSON 규칙으로 직렬화했다가 되읽은 값(비교 기준)."""
    return json.loads(to_json(obj))


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from strings(v)


def main() -> int:
    safe_console()
    results = []

    def check(name, ok, detail=""):
        results.append(bool(ok))
        print(f"{'PASS' if ok else 'FAIL'} {name}" + (f": {detail}" if detail and not ok else ""))

    with tempfile.TemporaryDirectory() as tmp:
        rates_path = Path(tmp) / "rates.json"
        rates_path.write_text(json.dumps({"rates": [
            {"trade": "콘크리트공", "unit_price": "1000", "basis_date": "2000-01-01", "source": SPECIAL_SOURCE},
            {"trade": "보통인부", "unit_price": "2000", "basis_date": "2000-01-01", "source": SPECIAL_SOURCE}]},
            ensure_ascii=False), encoding="utf-8")
        rates = load_rates(rates_path)

        cases = [
            ("unit_price --volume 150 --json", ["agent/calc/unit_price.py", "--volume", "150", "--rates", str(rates_path), "--json"],
             lambda: calculate_case(parse_volume("150"), rates)),
            ("unit_price --golden --json (단가 없음)", ["agent/calc/unit_price.py", "--golden", "--json"],
             lambda: calculate({})),
            ("agent --json 정상", ["agent/flow/agent.py", QUERY, "--offline", "--rates", str(rates_path), "--json"],
             lambda: answer(QUERY, rates, offline=True)),
            ("agent --json 조건 부족", ["agent/flow/agent.py", "레미콘 타설 노무비 알려줘", "--offline", "--json"],
             lambda: answer("레미콘 타설 노무비 알려줘", {}, offline=True)),
            ("agent --json 범위 밖", ["agent/flow/agent.py", "PC기둥 설치 노무비", "--offline", "--json"],
             lambda: answer("PC기둥 설치 노무비", {}, offline=True)),
        ]
        for name, args, build in cases:
            proc = run(args)
            if proc.returncode != 0:
                check(name, False, proc.stderr.decode("cp949", "replace")[-300:])
                continue
            check(f"{name}: 출력이 ASCII 바이트뿐", all(b < 128 for b in proc.stdout))
            try:
                got = json.loads(proc.stdout.decode("cp949"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                check(f"{name}: cp949로 읽어 json.loads", False, str(exc))
                continue
            want = expected(build())
            check(f"{name}: 왕복 값이 프로세스 안 결과와 같음", got == want)
            lost = [s for s in strings(got) if "?" in s and s not in set(strings(want))]
            check(f"{name}: '?'로 바뀐 글자 없음", not lost, str(lost[:3]))

        got = json.loads(run(["agent/calc/unit_price.py", "--volume", "150", "--rates", str(rates_path), "--json"])
                         .stdout.decode("cp949"))
        sources = {i["price_source"] for i in got["items"]}
        check("원문 특수문자 보존: 단가 출처 ①·∼·㎥·—·‘’", sources == {SPECIAL_SOURCE})
        check("한글·㎥ 보존: 사용한 원문 행", all("철근구조물" in i["labor_row"] and "㎥" in i["labor_row"] for i in got["items"]))
        check("원문 인용 보존: 공구손료 ④ 조건", any(u["text"].startswith("④ 공구손료") for u in got["unapplied_conditions"]))

        human = run(["agent/calc/unit_price.py", "--volume", "150", "--rates", str(rates_path)])
        text = human.stdout.decode("cp949", "replace")
        check("일반 출력: cp949에서 멈추지 않음(기존 동작)", human.returncode == 0 and "일위대가(노무비)" in text
              and "22.5 인·일" in text)
        human = run(["agent/flow/agent.py", QUERY, "--offline", "--rates", str(rates_path)])
        text = human.stdout.decode("cp949", "replace")
        check("일반 출력: 에이전트 답변도 cp949에서 멈추지 않음", human.returncode == 0 and "[결과]" in text
              and "PDF 185쪽" in text)

    print(f"\n통과 {sum(results)} / 전체 {len(results)} (API 호출 없음, 가상 단가)")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
