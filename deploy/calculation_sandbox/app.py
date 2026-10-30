"""Private stateless execution service; deploy only behind Cloud Run IAM + gVisor."""
from __future__ import annotations

import hashlib
import json
import os
import selectors
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from pipeline.python_sandbox import validate_python_candidate

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
MAX_SOURCE = 512_000
MAX_INPUT = 1_000_000
MAX_OUTPUT = 256_000


def _run_sandbox(command: list[str], *, cwd: Path, timeout_seconds: int):
    process = subprocess.Popen(command, cwd=cwd,
        env={"PATH": os.environ.get("PATH", ""), "PORT": os.environ.get("PORT", "8080")},
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    output = bytearray()
    deadline = time.monotonic() + timeout_seconds
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                process.kill()
                process.wait()
                return None, "timeout"
            for key, _ in selector.select(min(remaining, 0.1)):
                chunk = key.fileobj.read1(4096)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                output.extend(chunk)
                if len(output) > MAX_OUTPUT:
                    process.kill()
                    process.wait()
                    return None, "output too large"
            if process.poll() is not None and not selector.get_map():
                return (process.returncode, bytes(output).decode("utf-8", errors="replace")), None
    finally:
        selector.close()
        if process.poll() is None:
            process.kill()
            process.wait()


class ExecutionRequest(BaseModel):
    source: str
    code_sha256: str
    spec: dict
    inputs: dict
    timeout_seconds: int = 5


@app.post("/execute")
async def execute(payload: ExecutionRequest, request: Request):
    raw = await request.body()
    if len(raw) > MAX_INPUT + MAX_SOURCE:
        raise HTTPException(413, "request too large")
    source = payload.source
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    if digest != payload.code_sha256:
        raise HTTPException(400, "code hash mismatch")
    if not 1 <= payload.timeout_seconds <= 10:
        raise HTTPException(400, "timeout outside policy")
    violations = validate_python_candidate(source)
    if violations:
        raise HTTPException(400, detail=violations)
    with tempfile.TemporaryDirectory(prefix="calc-worker-") as directory:
        work = Path(directory)
        candidate = work / "candidate.py"
        harness = work / "harness.py"
        data = work / "case.json"
        candidate.write_text(source, encoding="utf-8")
        data.write_text(json.dumps({"spec": payload.spec, "inputs": payload.inputs}, ensure_ascii=False), encoding="utf-8")
        harness.write_text(
            "import importlib.util,json,sys\n"
            "s=importlib.util.spec_from_file_location('candidate',sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)\n"
            "d=json.load(open(sys.argv[2],encoding='utf-8'));r=m.calculate(d['spec'],d['inputs'],labor_only=True)\n"
            "print(json.dumps(r,ensure_ascii=False,default=str,separators=(',',':')))\n", encoding="utf-8")
        for path in (candidate, harness, data):
            path.chmod(0o444)
        work.chmod(0o755)
        command = ["/usr/local/gcp/bin/sandbox", "do",
            "--mount", f"type=bind,source={work},destination=/work,readonly",
            "--env", "PATH=/usr/local/bin:/usr/bin:/bin", "--",
            "/bin/sh", "-c",
            "ulimit -v 262144; ulimit -t 3; ulimit -f 512; exec python -I -S -B /work/harness.py /work/candidate.py /work/case.json"]
        completed, run_error = _run_sandbox(command, cwd=ROOT, timeout_seconds=payload.timeout_seconds + 3)
        if run_error == "timeout":
            raise HTTPException(408, "calculation timed out")
        if run_error == "output too large":
            raise HTTPException(413, "result too large")
        returncode, stdout = completed
        if returncode:
            raise HTTPException(422, "candidate execution failed")
        try:
            result = json.loads(stdout.splitlines()[-1])
        except (ValueError, IndexError):
            raise HTTPException(422, "candidate returned invalid JSON")
        if not isinstance(result, dict):
            raise HTTPException(422, "candidate result must be an object")
        return {"status": "ok", "result": result}
