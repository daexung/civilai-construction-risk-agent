"""검색 순위를 재사용해 부문별 절의 원문을 모은다."""
from functools import cache
import json
import re
from pathlib import Path
from backend.agent.nodes.select import decide, MARGIN
from backend.agent.rules.specs import specs_by_section
from backend.agent.tools.search.bm25 import tokens
from backend.paths import ROOT

CHUNKS = ROOT / "data/processed/chunks.all.jsonl"
LIMIT = 4000
TOTAL_LIMIT = 12000
FIRST_LIMIT = 8000

def _position_lines(words):
    """PDF 단어를 위에서 아래, 같은 줄에서는 왼쪽에서 오른쪽으로 모은다."""
    rows = []
    for word in sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0])):
        center = (word[1] + word[3]) / 2
        if not rows or abs(center - rows[-1][0]) > 3:
            rows.append((center, []))
        rows[-1][1].append(word)
    return "\n".join(" ".join(w[4] for w in sorted(row, key=lambda w: w[0])) for _, row in rows)

@cache
def pdf_table_text(pdf, page, bbox, section_no):
    import pymupdf

    with pymupdf.open(pdf) as document:
        source_page = document[page - 1]
        if bbox:
            return _position_lines(source_page.get_text("words", clip=pymupdf.Rect(bbox)))
        lines = _position_lines(source_page.get_text("words")).splitlines()
        start = next((i for i, line in enumerate(lines) if re.match(rf"^{re.escape(section_no)}\s", line)), None)
        if start is None:
            return ""
        end = next((i for i in range(start + 1, len(lines))
                    if re.match(r"^\d+-\d+(?:-\d+)?\s+[^\d]", lines[i])), len(lines))
        return "\n".join(lines[start:end])

def supplement_table(chunk):
    if chunk.get("kind") != "table":
        return chunk
    label_shift = any(str(issue).startswith("label_shift") for issue in chunk.get("issues", []))
    content = "\n".join(line for line in chunk["text"].splitlines()
                        if not line.startswith((chunk.get("section_no") or "\0", "기준 ")))
    if not label_shift and chunk.get("structure") != "uncertain" and re.search(r"\d", content):
        return chunk
    source = chunk.get("source", {})
    pdf = ROOT / source.get("pdf", "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf")
    try:
        raw = pdf_table_text(str(pdf), source["page"], tuple(source["bbox"]) if source.get("bbox") else None, chunk["section_no"])
    except (OSError, KeyError, ValueError) as exc:
        return {**chunk, "supplement_error": type(exc).__name__}
    if label_shift:
        # The parsed cells contain a confidently wrong label/value pairing; expose only PDF text.
        text = f"{chunk['section']}\n[{chunk['chunk_id']} 원문텍스트 · 이름 줄 밀림]\n{raw}"
    else:
        text = chunk["text"] + (f"\n[{chunk['chunk_id']} 원문텍스트 · 표 구조 불확실]\n{raw}" if raw else "")
    return {**chunk, "pdf_text": raw, "text": text}

@cache
def load_sections():
    sections = {}
    for line in CHUNKS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            chunk = json.loads(line)
            sections.setdefault((chunk.get("division", "공통"), chunk.get("section_no")), []).append(chunk)
    return sections

def build_context(hits, *, query="", sections=None, specs=None, limit=None):
    decision = decide(hits, specs_by_section() if specs is None else specs)
    candidates = decision["candidates"][:1 if decision["decision"] == "chosen" else 3]
    sections = load_sections() if sections is None else sections
    contexts = []
    remaining_total = TOTAL_LIMIT
    words = set(tokens(query))
    conditions = re.findall(r"\d+(?:\.\d+)?\s*[가-힣㎡㎥%]+", query)
    second = decision["candidates"][1] if len(decision["candidates"]) > 1 else None
    confident = bool(candidates) and (decision["decision"] == "chosen" or second is None or
                                     candidates[0]["score"] >= MARGIN * second["score"])
    for candidate_index, candidate in enumerate(candidates):
        budget = min(FIRST_LIMIT if candidate_index == 0 else remaining_total // (len(candidates) - candidate_index), remaining_total)
        if limit is not None:  # Explicit budgets retain the earlier bounded-context contract.
            budget = min(budget, limit)
        key = (candidate["division"], candidate["section_no"])
        ordered = sorted([supplement_table(c) for c in sections.get(key, [])], key=lambda c: (c["source"]["page"], min(c["record_ids"]) if c.get("record_ids") else int(re.search(r"(\d+)$", c["chunk_id"]).group(1))))
        ids = [h["chunk_id"] for h in hits if (h.get("division", "공통"), h.get("section_no")) == key]
        total = sum(len(c["text"]) + len(c["chunk_id"]) + 4 for c in ordered)
        truncated = total > budget
        def relevance(c):
            subtitle = (c.get("subsection") or {}).get("title", "")
            compact = re.sub(r"\s+", "", subtitle + "\n" + "\n".join(c["text"].splitlines()[:3]))
            condition_matches = sum(re.sub(r"\s+", "", term) in compact for term in conditions)
            overlap = sum(len(word) for word in words & set(tokens(subtitle + "\n" + c["text"])))
            note = any(t in c["text"] for t in ("[주]", "비고", "①", "※"))
            return (-condition_matches, -overlap, -int(note), -int(c["chunk_id"] in ids), ordered.index(c))
        priority = sorted(ordered, key=relevance) if truncated else ordered
        selected, remaining = {}, budget
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
        text = "\n".join(f"[{c['chunk_id']}]\n{c['text']}" for c in chunks)
        remaining_total -= len(text)
        contexts.append({**candidate, "chunks": chunks, "truncated": truncated,
                         "selection_decision": decision["decision"], "section_confident": confident if candidate_index == 0 else False,
                         "text": text})
    return contexts
