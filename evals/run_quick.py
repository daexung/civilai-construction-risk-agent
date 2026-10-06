"""가벼운 검사만 순서대로 실행하고 합계 표를 출력한다.

API·임베딩·PDF 파싱처럼 느린 검사는 뺀다. AGENT_OFFLINE=1, AGENT_LLM=off로 고정한다(호출 없음).
실행: python evals/run_quick.py
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

QUICK_CHECKS = [
    "check_router", "check_qa", "check_label_shift", "check_compose", "check_fill", "check_graph", "check_api", "check_bundle", "check_price",
    "check_equipment", "check_supply", "check_spec_cases", "check_citation", "check_overhead_rates",
    "check_cost_statement", "check_embedding_config", "check_chunk_ids",
    "check_per_unit", "check_adjustments",
    "check_scope_inputs", "check_page_divisions",
]

SUMMARY_PATTERN = re.compile(r"통과 (\d+) / 전체 (\d+)")


def run_one(name: str) -> tuple[int, str, str]:
    env = dict(os.environ)
    env["AGENT_OFFLINE"] = "1"
    env["AGENT_LLM"] = "off"
    env["PYTHONIOENCODING"] = "utf-8"
    env["INDEX_CONFIG"] = str(ROOT / "evals/index_configs/6chapter_studio.json")
    if name in ("check_scope", "check_scope_inputs", "check_page_divisions"):
        env.pop("INDEX_CONFIG", None)
    result = subprocess.run(
        [sys.executable, str(ROOT / "evals" / f"{name}.py")],
        cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    output = result.stdout + result.stderr
    match = SUMMARY_PATTERN.search(output)
    summary = match.group(0) if match else ("요약 줄 없음" if result.returncode == 0 else "오류")
    return result.returncode, summary, output


def run_checks(names: list[str]) -> bool:
    rows = []
    for name in names:
        code, summary, output = run_one(name)
        status = "PASS" if code == 0 else "FAIL"
        rows.append((name, status, summary))
        print(f"{status} {name}: {summary}")
        if code != 0:
            print(output[-3000:])
    print()
    header = f"{'스크립트':30}{'결과':8}{'요약'}"
    print(header)
    print("-" * len(header))
    for name, status, summary in rows:
        print(f"{name:30}{status:8}{summary}")
    return all(status == "PASS" for _, status, _ in rows)


def main() -> int:
    ok = run_checks(QUICK_CHECKS)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
