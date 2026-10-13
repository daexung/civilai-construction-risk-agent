"""4g 정답 준비용 원문 열람 도구. 검색·선택 경로를 실행하지 않고 원문 DB의 절·조각만 읽는다(읽기 전용)."""
import sys, json, re
from pathlib import Path
sys.dont_write_bytecode = True
W = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(W / 'src')); sys.path.insert(0, str(W / 'pilots/step04d'))
import retrieve as rv, select_verified as sv, specs  # noqa

class _C:
    def call(*a, **k): raise AssertionError('검색·선택 호출 금지')

def open_store():
    rt = rv.Retriever(embed_queries=False, vectors=False)
    vs = sv.VerifiedSelector(rt, _C())
    return rt, vs

def used_sections():
    used = set()
    for s in specs.load_specs():
        for k in ('answer_sections', 'acceptable_sections', 'forbidden_sections', 'evidence_in', 'expect_primary'):
            used |= set(s.get(k) or [])
        for t in s.get('tasks') or []:
            used |= set(t.get('answer_sections') or [])
    for fn in ('pilots/step04e/dev_cases_4e.json', 'pilots/step04f/dev_cases_4f.json'):
        d = json.loads((W / fn).read_text(encoding='utf-8'))
        for v in d.values():
            if isinstance(v, list):
                for c in v:
                    if isinstance(c, dict):
                        for k in ('answer_sections_any', 'forbidden_sections', 'alternatives_sections'):
                            for x in c.get(k, []):
                                used.add('pumsem-2026-errata1:' + x)
    return used


def show(vs, secid, maxc=900):
    sid = secid if secid.startswith('pumsem') else 'pumsem-2026-errata1:' + secid
    sec = vs.sel.sec[sid]
    print(f"##### {secid} | {sec['division']} {sec['number']} {sec['title']} | p{sec['first_page']}")
    chs = sorted((c for c, ch in vs.store.chunk.items() if ch['section_id'] == sid), key=lambda c: vs.store.chunk[c]['ordinal'])
    for c in chs:
        ch = vs.store.chunk[c]
        print(f"--- {c.split(':', 1)[-1]} [{ch['kind']}] status={ch['status']} issues={ch['issues']}")
        t = ch['text']
        print(t[:maxc].replace('\n', '\n    '))
