"""검색 순위를 재사용해 부문별 절의 원문을 모은다."""
from functools import cache
import json
import re
from pathlib import Path
from agent.nodes.select import decide
from agent.rules.specs import specs_by_section

CHUNKS = Path(__file__).resolve().parents[2] / "data/processed/chunks.all.jsonl"
LIMIT = 4000

@cache
def load_sections():
    sections = {}
    for line in CHUNKS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            chunk = json.loads(line)
            sections.setdefault((chunk.get("division", "공통"), chunk.get("section_no")), []).append(chunk)
    return sections

def build_context(hits, *, sections=None, specs=None, limit=LIMIT):
    decision = decide(hits, specs_by_section() if specs is None else specs)
    candidates = decision["candidates"][:1 if decision["decision"] == "chosen" else 3]
    sections = load_sections() if sections is None else sections
    contexts = []
    for candidate in candidates:
        key = (candidate["division"], candidate["section_no"])
        ordered = sorted(sections.get(key, []), key=lambda c: (c["source"]["page"], min(c["record_ids"]) if c.get("record_ids") else int(re.search(r"(\d+)$", c["chunk_id"]).group(1))))
        ids = [h["chunk_id"] for h in hits if (h.get("division", "공통"), h.get("section_no")) == key]
        total = sum(len(c["text"]) + len(c["chunk_id"]) + 4 for c in ordered)
        truncated = total > limit
        priority = sorted(ordered, key=lambda c: (0 if c["chunk_id"] in ids else 1 if any(t in c["text"] for t in ("[주]", "비고", "①", "※")) else 2, ordered.index(c))) if truncated else ordered
        selected, remaining = {}, limit
        for index, c in enumerate(priority):
            # Reserve room for retrieved chunks and notes following a long table.
            important = [n for n in priority[index + 1:] if n["chunk_id"] in ids or any(t in n["text"] for t in ("[주]", "비고", "①", "※"))]
            reserve = sum(min(200, len(n["text"])) + len(n["chunk_id"]) + 4 for n in important)
            room = remaining - len(c["chunk_id"]) - 4 - min(reserve, remaining // 2)
            if room <= 0:
                break
            text = c["text"][:room]
            selected[c["chunk_id"]] = {**c, "text": text}
            remaining -= len(text) + len(c["chunk_id"]) + 4
        chunks = [selected[c["chunk_id"]] for c in ordered if c["chunk_id"] in selected]
        contexts.append({**candidate, "chunks": chunks, "truncated": truncated,
                         "text": "\n".join(f"[{c['chunk_id']}]\n{c['text']}" for c in chunks)})
    return contexts
