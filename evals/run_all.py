"""run_quick의 가벼운 검사 + 무거운 검사(파서·품량·RAG·견적·표 커버리지)를 모두 실행한다.

선택적으로 --build를 주면 마지막에 `npm run build`도 실행한다.
실행: python evals/run_all.py [--build]
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_quick import QUICK_CHECKS, run_checks  # noqa: E402

HEAVY_CHECKS = [
    "check_parse", "check_quantity", "check_rag", "check_estimate", "check_table_coverage",
]


def run_build() -> bool:
    result = subprocess.run(["npm", "run", "build"], cwd=ROOT / "frontend",
                            capture_output=True, text=True, encoding="utf-8", errors="replace", shell=True)
    ok = result.returncode == 0
    print(f"{'PASS' if ok else 'FAIL'} npm run build")
    if not ok:
        print((result.stdout + result.stderr)[-3000:])
    return ok


def main() -> int:
    ok = run_checks(QUICK_CHECKS + HEAVY_CHECKS)
    if "--build" in sys.argv:
        ok = run_build() and ok
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
