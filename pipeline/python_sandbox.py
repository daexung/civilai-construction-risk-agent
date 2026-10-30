"""Fail-closed local Docker or authenticated remote sandbox runner for generated Python."""
from __future__ import annotations

import json
import ast
import subprocess
import tempfile
import os
from pathlib import Path


class SandboxUnavailable(RuntimeError):
    pass


def run_registered_python(source: str, spec: dict, inputs: dict, *, image: str,
                         timeout_seconds: int = 5) -> dict:
    """Use a private isolated execution service in deployments; otherwise local Docker."""
    endpoint = os.environ.get("CALC_PYTHON_SANDBOX_URL", "").strip()
    if not endpoint:
        return run_generated_python(source, spec, inputs, image=image, timeout_seconds=timeout_seconds)
    if not endpoint.startswith("https://"):
        return {"status": "failed", "errors": ["sandbox service URL must use HTTPS"]}
    try:
        import hashlib
        from google.auth.transport.requests import AuthorizedSession, Request
        from google.oauth2 import id_token
        audience = os.environ.get("CALC_PYTHON_SANDBOX_AUDIENCE", endpoint)
        credentials = id_token.fetch_id_token_credentials(audience, request=Request())
        session = AuthorizedSession(credentials)
        response = session.post(endpoint.rstrip("/") + "/execute", json={
            "source": source, "code_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
            "spec": spec, "inputs": inputs, "timeout_seconds": timeout_seconds,
        }, timeout=timeout_seconds + 5)
        if response.status_code != 200:
            return {"status": "failed", "errors": [f"sandbox service returned HTTP {response.status_code}"]}
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("status") != "ok" or not isinstance(payload.get("result"), dict):
            return {"status": "failed", "errors": ["sandbox service returned invalid result contract"]}
        return {**payload, "executor": "Cloud Run sandbox service"}
    except Exception as exc:
        return {"status": "failed", "errors": [f"remote isolated execution failed: {type(exc).__name__}"]}


def validate_python_candidate(source: str) -> list[str]:
    """Reject non-function modules, ambient imports, and obvious constant stubs."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"python syntax error: {exc.msg} at line {exc.lineno}"]
    errors = []
    functions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and node.name == "calculate"]
    if len(functions) != 1:
        return ["candidate must define exactly one top-level calculate function"]
    safe_imports = {"fractions", "decimal", "math"}
    def allowed_import(node: ast.AST) -> bool:
        if isinstance(node, ast.Import):
            return all(alias.name.split(".", 1)[0] in safe_imports for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            return node.level == 0 and node.module in safe_imports
        return False
    if any(not (isinstance(node, ast.FunctionDef) and node.name == "calculate")
           and not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)) and not allowed_import(node) for node in tree.body):
        errors.append("module top level may contain a docstring, safe numeric imports, and calculate function")
    function = functions[0]
    if isinstance(function, ast.AsyncFunctionDef):
        errors.append("calculate must be synchronous")
    if len(function.args.args) < 2 or [arg.arg for arg in function.args.args[:2]] != ["spec", "inputs"]:
        errors.append("calculate must accept spec and inputs as its first arguments")
    if function.decorator_list or function.args.vararg or function.args.kwarg or function.args.kwonlyargs:
        errors.append("calculate decorators, variadic and keyword-only parameters are not allowed")
    if any(not isinstance(default, (ast.Constant, ast.Dict, ast.List, ast.Tuple, ast.Set))
           for default in function.args.defaults + function.args.kw_defaults if default is not None):
        errors.append("calculate defaults must be literals")
    calls = [node for node in ast.walk(function) if isinstance(node, ast.Call)]
    if any((isinstance(node.func, ast.Name) and node.func.id in {
               "open", "eval", "exec", "compile", "__import__", "getattr", "setattr",
               "globals", "locals", "vars", "breakpoint", "input"})
           or (isinstance(node.func, ast.Attribute) and node.func.attr in {"system", "popen", "connect"})
           for node in calls):
        errors.append("candidate uses a forbidden ambient or dynamic call")
    names = {node.id for node in ast.walk(function) if isinstance(node, ast.Name)}
    subscripts = [node for node in ast.walk(function) if isinstance(node, ast.Subscript)]
    input_dependent = "inputs" in names and any(isinstance(node.value, ast.Name) and node.value.id == "inputs"
                                                  for node in subscripts)
    if not input_dependent:
        errors.append("candidate must derive results from supplied site inputs, not constants")
    return errors


def docker_run_command(image: str, candidate: Path, harness: Path, case_file: Path,
                       scratch: Path, docker: str = "docker") -> list[str]:
    if "@sha256:" not in image:
        raise ValueError("sandbox image must be pinned by immutable sha256 digest")
    paths = [Path(p).resolve() for p in (candidate, harness, case_file, scratch)]
    if not all(path.exists() for path in paths):
        raise ValueError("candidate, harness, case file, and scratch directory must exist")
    candidate_path, harness_path, case_path, scratch_path = paths
    return [docker, "run", "--rm", "--network=none", "--read-only", "--cap-drop=ALL",
            "--security-opt=no-new-privileges", "--pids-limit=32", "--memory=256m",
            "--memory-swap=256m", "--cpus=1", "--user=65534:65534",
            "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=16m",
            "--mount", f"type=bind,src={candidate_path},dst=/work/candidate.py,readonly",
            "--mount", f"type=bind,src={harness_path},dst=/work/harness.py,readonly",
            "--mount", f"type=bind,src={case_path},dst=/work/case.json,readonly",
            image, "python", "/work/harness.py", "/work/candidate.py", "/work/case.json"]


def run_generated_python(source: str, spec: dict, inputs: dict, *, image: str, timeout_seconds: int = 5,
                         docker: str = "docker") -> dict:
    """Run a candidate only in a locally available, digest-pinned no-network container."""
    if not 1 <= timeout_seconds <= 30:
        raise ValueError("timeout_seconds must be in 1..30")
    try:
        inspect = subprocess.run([docker, "image", "inspect", image], check=False,
                                 capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SandboxUnavailable(f"Docker image inspection unavailable: {exc}") from exc
    if inspect.returncode:
        raise SandboxUnavailable("pinned sandbox image is not already available locally; pulls are disabled")
    scratch_root = Path(__file__).resolve().parents[1] / "tmp" / "calc-sandbox"
    scratch_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="run-", dir=scratch_root) as directory:
        root = Path(directory)
        candidate = root / "candidate.py"
        harness = root / "harness.py"
        case_file = root / "case.json"
        # Candidate is imported as a module; API requires a pure function and JSON result.
        harness.write_text(
            "import importlib.util,json,sys\n"
            "spec=importlib.util.spec_from_file_location('candidate',sys.argv[1])\n"
            "m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)\n"
            "data=json.load(open(sys.argv[2],encoding='utf-8'))\n"
            "result=m.calculate(data['spec'],data['inputs'],labor_only=True)\n"
            "print(json.dumps(result,ensure_ascii=False,default=str))\n", encoding="utf-8")
        candidate.write_text(source, encoding="utf-8")
        # Only operational data crosses the sandbox boundary; expected outputs remain
        # in the trusted parent process and are never mounted or serialized here.
        case_file.write_text(json.dumps({"spec": spec, "inputs": inputs}, ensure_ascii=False), encoding="utf-8")
        command = docker_run_command(image, candidate, harness, case_file, root, docker=docker)
        try:
            result = subprocess.run(command, check=False, capture_output=True, text=True,
                                    timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            return {"status": "failed", "errors": [f"sandbox timed out after {timeout_seconds}s"]}
        if result.returncode:
            return {"status": "failed", "errors": [result.stderr[-4000:] or f"sandbox exit {result.returncode}"]}
        try:
            return {"status": "ok", "result": json.loads(result.stdout.splitlines()[-1])}
        except (ValueError, IndexError):
            return {"status": "failed", "errors": ["sandbox returned invalid JSON"]}
