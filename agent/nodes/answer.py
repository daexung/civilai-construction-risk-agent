"""품셈 상담 구조화 답변과 원문 검증."""
import json
import os
import re
import time
from difflib import SequenceMatcher
from pathlib import Path
from agent.nodes.qa_context import build_context
from agent.nodes.compose import validate_numbers
from agent.tools.llm import client
from agent.tools.search.bm25 import tokens

PROMPT = Path(__file__).resolve().parents[1] / "tools/llm/prompts/qa.md"
SCHEMA = {"type": "object", "properties": {
    "not_found": {"type": "boolean"}, "conclusion": {"type": "string"},
    "explanation": {"type": "string"}, "comparisons": {"type": "array", "items": {
        "type": "object", "properties": {"section": {"type": "string"}, "summary": {"type": "string"}}, "required": ["section", "summary"]}},
    "citations": {"type": "array", "items": {"type": "object", "properties": {
        "chunk_id": {"type": "string"}, "quote": {"type": "string"}}, "required": ["chunk_id", "quote"]}}},
    "required": ["not_found", "conclusion", "explanation", "comparisons", "citations"]}
MONEY = re.compile(r"\d[\d,]*(?:\.\d+)?\s*원|[₩￦]|[천만억조]\s*원|KRW|원\s*[/／]", re.I)
TIMEOUT_MS = 12_000
INSTRUCTION_LEAK = re.compile(r"금지되어|지시|규칙상|제공된\s*문맥|원문에\s*직접\s*곱셈")

def qa_model():
    return json.loads(client.CONFIG_PATH.read_text(encoding="utf-8")).get("qa_model", "gemini-3.5-flash-lite")

def normalize(text):
    return re.sub(r"\s+|\||설명|단위|수량", "", text)

def match_quote(quote, source):
    """표의 저장용 머리글을 제외하고 비교하되 표시 문장은 원문에서 가져온다."""
    wanted = normalize(quote)
    if not wanted:
        return None
    lines = [line.strip() for line in source.splitlines() if normalize(line)]
    joined = "".join(normalize(line) for line in lines)
    start = joined.find(wanted)
    if start >= 0:
        offset, selected = 0, []
        for line in lines:
            end = offset + len(normalize(line))
            if end > start and offset < start + len(wanted):
                selected.append(line)
            offset = end
        return "normalized", "\n".join(selected)
    if not lines:
        return None
    ranked = [(SequenceMatcher(None, wanted, normalize(line), autojunk=False).ratio(), line)
              for line in lines]
    score, line = max(ranked, key=lambda item: item[0])
    return ("fuzzy", line) if score >= 0.85 else None

def validate(qa, contexts, query=""):
    if not isinstance(qa, dict) or type(qa.get("not_found")) is not bool:
        return "schema"
    if not all(isinstance(qa.get(k), str) for k in ("conclusion", "explanation")) or not all(isinstance(qa.get(k), list) for k in ("comparisons", "citations")):
        return "schema"
    if any(not isinstance(c, dict) or not all(isinstance(c.get(k), str) for k in ("section", "summary")) for c in qa["comparisons"]):
        return "schema"
    if any(not isinstance(c, dict) or not all(isinstance(c.get(k), str) for k in ("chunk_id", "quote")) for c in qa["citations"]):
        return "schema"
    text = "\n".join([qa["conclusion"], qa["explanation"]] + [c["section"] + " " + c["summary"] for c in qa["comparisons"]])
    if INSTRUCTION_LEAK.search(text):
        return "instruction_leak"
    if MONEY.search(text + "\n" + "\n".join(c["quote"] for c in qa["citations"])):
        return "money"
    if qa["not_found"]:
        return None
    chunks = {c["chunk_id"]: "\n".join(line for line in c["text"].splitlines()
              if "원문텍스트 · 표 구조 불확실]" not in line) for ctx in contexts for c in ctx["chunks"]}
    sections = {ctx["section_no"] for ctx in contexts}
    if set(re.findall(r"\d+-\d+-\d+", text)) - sections:
        return "section"
    source = "\n".join(ctx["section"] for ctx in contexts) + "\n" + "\n".join(chunks.values())
    source += "\n" + query
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
        match = match_quote(cite["quote"], chunks[cite["chunk_id"]])
        if match is None:
            return "quote"
        kind, original = match
        if MONEY.search(original):
            return "money"
        cite.update(quote=original, quote_match=kind)
    return None

def not_found(contexts, *, value_missing=False, hits=None, query=""):
    if value_missing and contexts:
        qa = template(contexts[:1], hits or [], query)
        qa.update(not_found=True, not_found_kind="section_found_value_missing",
                  conclusion=f"관련 기준은 {contexts[0]['section']}입니다. 질문하신 조건의 값은 원문에서 확인하지 못했습니다.")
        return qa
    return {"not_found": True, "not_found_kind": "section_not_found",
            "conclusion": "품셈에서 이 질문에 맞는 기준을 찾지 못했습니다.",
            "explanation": "가장 가까운 절: " + contexts[0]["section"] if contexts else "",
            "comparisons": [], "citations": []}

def content_lines(chunk):
    """절 표제와 빈 표 머리글을 제외하고 실제 내용 행만 남긴다."""
    title = normalize(chunk.get("section", ""))
    for raw in chunk["text"].splitlines():
        line = raw.strip()
        if not line or MONEY.search(line) or "원문텍스트 · 표 구조 불확실]" in line:
            continue
        if normalize(line) == title or re.match(r"^\d+-\d+-\d+(?:\s|$)", line):
            continue
        if re.fullmatch(r"(?:기준\s*)?\([^)]*\)", line):
            continue
        compact = re.sub(r"[\s|]", "", line)
        content = re.sub(r"설명|단위|수량|규격|구분|품명|공종|기준", "", compact)
        if content in ("", "인", "대", "㎡", "㎥"):
            continue
        yield line

def template(contexts, hits, query=""):
    qa = {"not_found": False, "conclusion": "품셈에서 관련 기준을 찾았습니다.", "explanation": "",
          "comparisons": [], "citations": []}
    ranks = {h["chunk_id"]: h["rank"] for h in hits}
    words = set(tokens(query))
    seen = set()
    for ctx in contexts:
        retrieved = [c for c in ctx["chunks"] if c["chunk_id"] in ranks]
        rows = []
        retrieved_ids = {c["chunk_id"] for c in retrieved}
        for c in ctx["chunks"]:
            for order, line in enumerate(content_lines(c)):
                overlap = sum(len(word) for word in words & set(tokens(line)))
                table = c.get("kind") == "table" or "|" in line
                rows.append((int(bool(retrieved_ids) and c["chunk_id"] not in retrieved_ids),
                             -overlap, -int(table), ranks.get(c["chunk_id"], 999), order, c["chunk_id"], line))
        selected = []
        for *_, chunk_id, line in sorted(rows):
            if normalize(line) in seen:
                continue
            seen.add(normalize(line))
            selected.append({"chunk_id": chunk_id, "quote": line})
            if len(selected) == 2:
                break
        qa["comparisons"].append({"section": ctx["section"],
            "summary": "\n".join(c["quote"] for c in selected),
            "citation_ids": list(dict.fromkeys(c["chunk_id"] for c in selected))})
        qa["citations"].extend(selected)
    if any(ctx["truncated"] for ctx in contexts):
        qa["explanation"] = "문맥 길이 제한으로 일부 원문이 생략되었습니다. 원문을 확인해 주세요."
    return qa

def answer(state, *, generate_fn=None, model=None, contexts=None):
    contexts = build_context(state.get("hits", []), query=state["query"]) if contexts is None else contexts
    info = {"model": model or qa_model(), "elapsed_ms": 0, "attempts": 0, "error": None}
    qa, source = not_found(contexts), "template"
    started = time.monotonic()
    if contexts:
        qa = template(contexts, state.get("hits", []), state["query"])
        try:
            if generate_fn is None and os.environ.get("AGENT_LLM", "off") != "on":
                raise client.LLMUnavailable("AGENT_LLM=off")
            call_started = time.monotonic()
            result = (generate_fn or client.generate)(json.dumps({"question": state["query"], "sections": [
                {"section": c["section"], "truncated": c["truncated"], "text": c["text"]} for c in contexts]}, ensure_ascii=False),
                PROMPT.read_text(encoding="utf-8"), response_schema=SCHEMA, timeout_ms=TIMEOUT_MS, model=info["model"])
            info.update(provider=getattr(result, "provider", None), attempts=getattr(result, "attempts", 1))
            if (time.monotonic() - call_started) * 1000 >= TIMEOUT_MS:
                raise client.LLMUnavailable("timeout", attempts=info["attempts"], provider=info.get("provider"))
            generated = json.loads(result.text if hasattr(result, "text") else result)
            error = validate(generated, contexts, state["query"])
            if error:
                info["error"] = error
            else:
                qa = not_found(contexts, value_missing=contexts[0].get("section_confident", False) or
                               contexts[0].get("selection_decision") == "chosen",
                               hits=state.get("hits", []), query=state["query"]) if generated["not_found"] else generated
                source = "llm"
        except Exception as exc:
            info.update(error=str(exc) if isinstance(exc, client.LLMUnavailable) else type(exc).__name__, attempts=getattr(exc, "attempts", info["attempts"]))
    info["elapsed_ms"] = round((time.monotonic() - started) * 1000)
    parts = [qa["conclusion"], qa["explanation"]]
    if source == "template" or qa.get("not_found_kind") == "section_found_value_missing":
        for comparison in qa["comparisons"]:
            parts.append(comparison["section"])
            parts.extend(f"[{c['chunk_id']}] {c['quote']}" for c in qa["citations"]
                         if c["chunk_id"] in comparison.get("citation_ids", []))
    else:
        parts.extend(c["section"] + ": " + c["summary"] for c in qa["comparisons"])
        parts.extend(f"[{c['chunk_id']}] {c['quote']}" for c in qa["citations"])
    text = "\n\n".join(t for t in parts if t)
    return {"status": "ANSWERED", "reason": "", "qa": qa, "answer": text, "answer_source": source,
            "llm_info": info, "candidates": [{k: c[k] for k in ("division", "section_no", "section", "score", "has_spec")} for c in contexts]}
