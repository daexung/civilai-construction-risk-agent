"""OpenDataLoader hybrid 실험: 백엔드 서버를 띄우고 auto·full 두 분기 모드를 차례로 돌린다.

백엔드 'docling-fast' = opendataloader-pdf-hybrid 서버 = Docling DocumentConverter.
서버는 --no-ocr --device cpu로 띄워 앞선 Docling 실험과 OCR·장치 조건을 맞춘다.
서버 기동 시간(모델 로딩)과 서버 로그를 결과 폴더에 남긴다.

실행(저장소 루트, 기존 .venv): python experiments/parser_bench/run_odl_hybrid.py
"""
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from common import RESULTS, ROOT

SERVER = ROOT / ".venv-odl/Scripts/opendataloader-pdf-hybrid.exe"
PORT = 5002
HERE = Path(__file__).resolve().parent
RUNS = [("odl_hybrid_auto", "auto"), ("odl_hybrid_full", "full")]
SOURCE = sys.argv[1] if len(sys.argv) > 1 else "pages"   # pages | full
SUFFIX = "__fullpdf" if SOURCE == "full" else ""


def healthy() -> bool:
    try:
        with urllib.request.urlopen(f"http://localhost:{PORT}/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def main() -> int:
    log_path = RESULTS / f"odl_hybrid_server{SUFFIX}.log"
    RESULTS.mkdir(parents=True, exist_ok=True)
    server_cmd = [str(SERVER), "--port", str(PORT), "--no-ocr", "--device", "cpu"]
    with open(log_path, "w", encoding="utf-8") as log:
        log.write(f"$ {' '.join(server_cmd)}\n\n")
        log.flush()
        t0 = time.perf_counter()
        server = subprocess.Popen(server_cmd, stdout=log, stderr=subprocess.STDOUT)
        try:
            while not healthy():
                if server.poll() is not None:
                    print(f"서버가 종료됨 (exit {server.returncode}). 로그: {log_path}")
                    return 1
                if time.perf_counter() - t0 > 900:
                    print("서버 기동 900초 초과")
                    return 1
                time.sleep(2)
            startup = time.perf_counter() - t0
            print(f"서버 기동 {startup:.1f}초")

            for base, mode in RUNS:
                name = base + SUFFIX
                subprocess.run([sys.executable, str(HERE / "extract_odl.py"), "--name", name, "--hybrid", mode,
                                "--source", SOURCE], check=False)
                meta_path = RESULTS / name / "tables.json"
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                meta["server"] = {"command": server_cmd, "startup_sec": round(startup, 2),
                                  "log": str(log_path.relative_to(ROOT))}
                meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        finally:
            server.terminate()
            try:
                server.wait(timeout=30)
            except subprocess.TimeoutExpired:
                server.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
