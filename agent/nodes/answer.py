"""품셈 상담 구조화 답변과 원문 검증."""
import json
import os
import re
import time
from pathlib import Path
from agent.nodes.qa_context import build_context
from agent.nodes.compose import validate_numbers
from agent.tools.llm import client

PROMPT = Path(__file__).resolve().parents[1] / "tools/llm/prompts/qa.md"
SCHEMA = {"type": "object", "properties": {
    "not_found": {"type": "boolean"}, "conclusion": {"type": "string"},
    "explanation": {"type": "string"}, "comparisons": {"type": "array", "items": {
        "type": "object", "properties": {"section": {"type": "string"}, "summary": {"type": "string"}}, "required": ["section", "summary"]}},
    "citations": {"type": "array", "items": {"type": "object", "properties": {
        "chunk_id": {"type": "string"}, "quote": {"type": "string"}}, "required": ["chunk_id", "quote"]}}},
    "required": ["not_found", "conclusion", "explanation", "comparisons", "citations"]}
MONEY = re.compile(r"\d[\d,]*(?:\.\d+)?\s*원|[₩￦]|[천만억조]\s*원|KRW|원\s*[/／]", re.I)

def qa_model():
    return json.loads(client.CONFIG_PATH.read_text(encoding="utf-8")).get("qa_model", "gemini-3.5-flash-lite")

def normalize(text):
    return re.sub(r"\s+", "", text)

def validate(qa, contexts):
    if not isinstance(qa, dict) or type(qa.get("not_found")) is not bool:
        return "schema"
    if not all(isinstance(qa.get(k), str) for k in ("conclusion", "explanation")) or not all(isinstance(qa.get(k), list) for k in ("comparisons", "citations")):
        return "schema"
    if any(not isinstance(c, dict) or not all(isinstance(c.get(k), str) for k in ("section", "summary")) for c in qa["comparisons"]):
        return "schema"
    if any(not isinstance(c, dict) or not all(isinstance(c.get(k), str) for k in ("chunk_id", "quote")) for c in qa["citations"]):
        return "schema"
    text = "\n".join([qa["conclusion"], qa["explanation"]] + [c["section"] + " " + c["summary"] for c in qa["comparisons"]])
    if MONEY.search(text + "\n" + "\n".join(c["quote"] for c in qa["citations"])):
        return "money"
    if qa["not_found"]:
        return None
    chunks = {c["chunk_id"]: c["text"] for ctx in contexts for c in ctx["chunks"]}
    sections = {ctx["section_no"] for ctx in contexts}
    if set(re.findall(r"\d+-\d+-\d+", text)) - sections:
        return "section"
    source = "\n".join(ctx["section"] + "\n" + "\n".join(c["text"] for c in ctx["chunks"]) for ctx in contexts)
    # Remove whitespace only within a numeric token (e.g. spaced thousands).
    source = re.sub(r"(?<=\d)[ \t]+(?=\d)", "", source)
    checked = re.sub(r"(?<=\d)[ \t]+(?=\d)", "", text)
    if not validate_numbers(checked, {"source": source})[0]:
        return "numbers"
    if not qa["citations"]:
        return "citations_missing"
    for cite in qa["citations"]:
        if cite["chunk_id"] not in chunks:
            return "chunk_id"
        if not normalize(cite["quote"]) or normalize(cite["quote"]) not in normalize(chunks[cite["chunk_id"]]):
            return "quote"
    return None

def not_found(contexts):
    return {"not_found": True, "conclusion": "품셈에서 이 질문에 맞는 기준을 찾지 못했습니다.",
            "explanation": "가장 가까운 절: " + contexts[0]["section"] if contexts else "",
            "comparisons": [], "citations": []}

def template(contexts, hits):
    qa = {"not_found": False, "conclusion": "품셈에서 관련 기준을 찾았습니다.", "explanation": "",
          "comparisons": [], "citations": []}
    ranks = {h["chunk_id"]: h["rank"] for h in hits}
    for ctx in contexts:
        qa["comparisons"].append({"section": ctx["section"], "summary": "원문 기준을 확인해 주세요."})
        for c in sorted(ctx["chunks"], key=lambda c: ranks.get(c["chunk_id"], 999))[:2]:
            lines = [line for line in c["text"].splitlines() if not MONEY.search(line)]
            quote = next((line.strip()[:350] for line in lines if line.strip()), "")
            if quote:
                qa["citations"].append({"chunk_id": c["chunk_id"], "quote": quote})
    if any(ctx["truncated"] for ctx in contexts):
        qa["explanation"] = "문맥 길이 제한으로 일부 원문이 생략되었습니다. 원문을 확인해 주세요."
    return qa

def answer(state, *, generate_fn=None, model=None, contexts=None):
    contexts = build_context(state.get("hits", [])) if contexts is None else contexts
    info = {"model": model or qa_model(), "elapsed_ms": 0, "attempts": 0, "error": None}
    qa, source = not_found(contexts), "template"
    started = time.monotonic()
    if contexts:
        qa = template(contexts, state.get("hits", []))
        try:
            if generate_fn is None and os.environ.get("AGENT_LLM", "off") != "on":
                raise client.LLMUnavailable("AGENT_LLM=off")
            result = (generate_fn or client.generate)(json.dumps({"question": state["query"], "sections": [
                {"section": c["section"], "truncated": c["truncated"], "text": c["text"]} for c in contexts]}, ensure_ascii=False),
                PROMPT.read_text(encoding="utf-8"), response_schema=SCHEMA, timeout_ms=15000, model=info["model"])
            info.update(provider=getattr(result, "provider", None), attempts=getattr(result, "attempts", 1))
            generated = json.loads(result.text if hasattr(result, "text") else result)
            error = validate(generated, contexts)
            if error:
                info["error"] = error
            else:
                qa = not_found(contexts) if generated["not_found"] else generated
                source = "llm"
        except Exception as exc:
            info.update(error=str(exc) if isinstance(exc, client.LLMUnavailable) else type(exc).__name__, attempts=getattr(exc, "attempts", info["attempts"]))
    info["elapsed_ms"] = round((time.monotonic() - started) * 1000)
    text = "\n\n".join(t for t in [qa["conclusion"], qa["explanation"]] + [c["section"] + ": " + c["summary"] for c in qa["comparisons"]] + [f"[{c['chunk_id']}] {c['quote']}" for c in qa["citations"]] if t)
    return {"status": "ANSWERED", "reason": "", "qa": qa, "answer": text, "answer_source": source,
            "llm_info": info, "candidates": [{k: c[k] for k in ("division", "section_no", "section", "score", "has_spec")} for c in contexts]}
