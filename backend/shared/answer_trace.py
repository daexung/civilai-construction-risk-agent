"""Request-local, bounded answer execution trace collection."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from fractions import Fraction
from hashlib import sha256
import json
import logging
import time
from uuid import uuid4

_trace = ContextVar("civilai_answer_trace", default=None)
_parent = ContextVar("civilai_answer_trace_parent", default=None)
MAX_STEPS = 120
MAX_JSON_BYTES = 8_192
MAX_STRING = 2_000
log = logging.getLogger(__name__)


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _bounded(value):
    """JSON-normalize, cap strings/depth/bytes, and expose omissions explicitly."""
    def clean(item, depth=0):
        if depth > 8:
            return {"_omitted": "max_depth"}
        if item is None or isinstance(item, (bool, int, float)):
            return item
        if isinstance(item, (Decimal, Fraction)):
            return str(item)
        if isinstance(item, str):
            return item[:MAX_STRING] + ("…" if len(item) > MAX_STRING else "")
        if isinstance(item, dict):
            return {str(k)[:100]: clean(v, depth + 1) for k, v in list(item.items())[:100]}
        if isinstance(item, (list, tuple)):
            return [clean(v, depth + 1) for v in item[:100]]
        return str(type(item).__name__)
    result = clean(value)
    encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":"), default=str)
    if len(encoded.encode("utf-8")) <= MAX_JSON_BYTES:
        return result, False
    # Keep valid JSON and disclose that the summary is partial.
    compact = encoded.encode("utf-8")[:MAX_JSON_BYTES - 100].decode("utf-8", errors="ignore")
    while compact:
        try:
            value = json.loads(compact)
            return {"_truncated": True, "_prefix": value}, True
        except json.JSONDecodeError:
            compact = compact[:-1]
    return {"_truncated": True}, True


@contextmanager
def capture(*, request_id=None, thread_id=None, conversation_id=None, user_id=None, environment=None, agent_mode=None):
    state = {"id": str(uuid4()), "request_id": str(request_id) if request_id else None,
             "thread_id": str(thread_id) if thread_id else None,
             "conversation_id": str(conversation_id) if conversation_id else None,
             "user_id": str(user_id) if user_id else None,
             "environment": environment or "local", "agent_mode": agent_mode or "graph",
             "started_at": datetime.now(timezone.utc), "started_clock": time.perf_counter(),
             "sequence": 0, "steps": [], "capture_status": "complete",
             "started_persisted": False, "execution_started": False, "suppressed": False}
    token = _trace.set(state)
    parent_token = _parent.set(None)
    try:
        yield state
    finally:
        _parent.reset(parent_token)
        _trace.reset(token)


def current():
    return _trace.get()


def _summary(value):
    result, truncated = _bounded(value or {})
    return result, truncated


@contextmanager
def step(name, kind, input_summary=None):
    state = _trace.get()
    if state is None or state["suppressed"]:
        yield None
        return
    if len(state["steps"]) >= MAX_STEPS:
        state["capture_status"] = "partial"
        yield None
        return
    state["sequence"] += 1
    entry = {"id": str(uuid4()), "parent_step_id": _parent.get(), "step_kind": kind,
             "name": str(name)[:100], "sequence": state["sequence"],
             "started_at": datetime.now(timezone.utc), "started_clock": time.perf_counter(),
             "status": "incomplete", "input_summary": None, "output_summary": None,
             "error_code": None, "error_type": None, "metadata": {}}
    if input_summary is not None:
        entry["input_summary"], cut = _summary(input_summary)
        if cut:
            state["capture_status"] = "partial"
    state["steps"].append(entry)
    parent_token = _parent.set(entry["id"])
    try:
        yield entry
        if entry["status"] == "incomplete":
            entry["status"] = "completed"
    except BaseException as exc:
        entry["status"] = "failed"
        entry["error_type"] = type(exc).__name__[:100]
        entry["error_code"] = "step_failed"
        raise
    finally:
        entry["finished_at"] = datetime.now(timezone.utc)
        entry["duration_ms"] = round((time.perf_counter() - entry.pop("started_clock")) * 1000, 2)
        _parent.reset(parent_token)


def set_output(entry, value):
    state = _trace.get()
    if state is None or entry is None:
        return
    entry["output_summary"], cut = _summary(value)
    if cut:
        state["capture_status"] = "partial"


def set_metadata(entry, value):
    state = _trace.get()
    if state is None or entry is None:
        return
    entry["metadata"], cut = _summary(value)
    if cut:
        state["capture_status"] = "partial"


def record_model(call):
    state = _trace.get()
    if state is None or state["suppressed"]:
        return
    if len(state["steps"]) >= MAX_STEPS:
        state["capture_status"] = "partial"
        return
    state["sequence"] += 1
    finished = datetime.now(timezone.utc)
    duration = max(0, int(call.get("elapsed_ms") or 0))
    entry = {"id": str(uuid4()), "parent_step_id": _parent.get(), "step_kind": "model",
             "name": str(call.get("model") or "model")[:100], "sequence": state["sequence"],
             "started_at": finished - timedelta(milliseconds=duration), "finished_at": finished,
             "duration_ms": duration, "status": "failed" if call.get("status") == "failed" else "completed",
             "error_code": "model_call_failed" if call.get("status") == "failed" else None,
             "error_type": str(call["error_type"])[:100] if call.get("error_type") else None}
    entry["input_summary"], cut_in = _summary({"schema_sha256": call.get("schema_sha256")})
    entry["output_summary"], cut_out = _summary({"status": call.get("status"), "attempts": call.get("attempts")})
    entry["metadata"], cut_meta = _summary({k: call[k] for k in
                         ("model", "provider", "system_sha256", "schema_sha256", "attempts", "usage")
                         if call.get(k) is not None})
    if cut_in or cut_out or cut_meta:
        state["capture_status"] = "partial"
    state["steps"].append(entry)


def suppress():
    state = _trace.get()
    if state is not None:
        state["suppressed"] = True


def mark_partial():
    state = _trace.get()
    if state is not None:
        state["capture_status"] = "partial"


def set_thread_id(value):
    state = _trace.get()
    if state is not None and value:
        state["thread_id"] = str(value)


def persist_start():
    state = _trace.get()
    if state is None or state["started_persisted"] or state["suppressed"]:
        return
    if not state["execution_started"]:
        state["started_at"] = datetime.now(timezone.utc)
        state["started_clock"] = time.perf_counter()
        state["execution_started"] = True
    from backend.api import answer_runs
    state["started_persisted"] = answer_runs.persist_start(state)


def finalize(response=None, *, failed=False):
    state = _trace.get()
    if state is None or state["suppressed"] or not state["execution_started"]:
        return
    from backend.api import answer_runs
    answer_runs.persist_finish(state, response, failed=failed)
