"""근거 선택(4b단계): 후보 검색 → 필요한 원문 선택 → 근거 부족 확인 → 제한된 추가 검색.

  python -B experiments/retrieval-v1/src/select_evidence.py "질문"

- 검색(retrieve.Retriever)의 work·rule·table 세 종류 후보를 모두 쓴다. 질문 종류로 후보를 미리 빼지 않는다.
  선택 정책이 질문의 목적(목록·특정 값·규칙)을 신호로 쓰고, 불분명하면 후보를 함께 반환하거나 확인 필요로 표시한다.
- 절 3개·조각 2개 같은 고정 개수가 완료 기준이 아니다. 조각마다 질문과의 관련도·단위 기준·앞 소제목을 대조해 고르고,
  구조 연결(기준·작은 표·주석·주석 표·참조)은 evidence.Reader가 원문 식별자로 읽는다.
- 근거가 부족하면 추가 검색은 질문 전체에서 최대 2회다(상위 묶음 하위 절 탐색 포함).
- 상태: supported(근거 있음) / needs_confirmation(근거 부족·확인 필요) / not_found(관련 근거를 찾지 못함).
  not_found는 가까운 후보를 진단 정보로만 남기고 정상 답변 근거로 내보내지 않는다.
- 질문 ID·정답 파일·특정 조각 ID를 코드에서 참조하지 않는다.
"""
import hashlib
import json
import math
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
from . import retrieve as rv  # noqa: E402
from . import evidence as ev  # noqa: E402
from . import embed_index as ei  # noqa: E402

CONFIG = {
    'score': {'cos_weight': 0.5, 'bm25_weight': 0.5},
    'idf_low': 2.0,                   # 이 값보다 낮은 낱말(거의 모든 조각에 있음)은 핵심어가 아니다
    'section_candidates': 14,         # 절 후보로 보는 상위 절 수(근거 읽기 개수 제한이 아니다)
    'chunk_rel_ratio': 0.85,          # 한 절 안에서 최고 조각 대비 이 비율 이상이면 함께 고른다(값 질문의 표)
    'rule_rel_ratio': 0.80,
    'primary_section_ratio': 0.92,    # 이 비율 이상이고 질문 핵심어를 더하지 못하면 '대안 후보'
    'complement_ratio': 0.60,         # 핵심어를 더해 주는 다른 절의 최소 비율(여러 공종)
    'basis_mismatch_penalty': 0.40,
    'note_table_penalty': 0.15,
    'label_weight': 0.35,
    'list': {'seed_ratio': 0.9, 'path_min': 0.5, 'f_floor_ratio': 0.4, 'max_sections': 20, 'top_stems': 3},
    'title_weight': 0.08,
    'coverage_stop': 0.75,            # 주 근거가 질문 핵심어의 이만큼을 설명하면 다른 공종을 보완 근거로 더하지 않는다
    'relevance': {'unsupported_cov_max': 0.6, 'weak_cov_min': 0.2},
    'extra_searches_max': 2,
    'group_target': {'top_children': 3},
    'evidence_budget_tokens': 4000,
    'evidence_depth': 1,
}
# 현장 통용어 → 표준품셈 표기. 질문의 낱말이 자료에 없을 때만 추가 검색에서 쓰는 일반 규칙이다(원문 표기는 바꾸지 않는다).
SYNONYMS = {'레미콘': '레디믹스트콘크리트', '포클레인': '굴착기', '백호': '굴착기', '불도자': '불도저', '덤프': '덤프트럭',
            '시멘트벽돌': '벽돌', '함마': '해머', '노가다': '인력', '인건비': '노무비'}
SYNONYM_NOTE = '현장 통용어와 표준품셈 표기 사이의 일반 규칙. 질문 낱말이 자료에 없을 때만 추가 검색 문구에 쓴다'
QWORDS = {'품', '품셈', '공종', '같이', '필요한', '필요', '해당', '대한', '관한', '위한', '얼마', '몇', '어떤', '어떻게', '어디', '무엇', '뭐', '뭐가', '뭐야', '알려', '알려줘', '알려주세요', '있어', '있나', '해줘', '대충', '정도',
          '번째', '처음', '퍼센트', '근거', '하루', '종류', '목록', '관련', '방법', '경우', '때', '좀', '더', '또', '그', '이', '저'}
ENDINGS = ('하면서', '하며', '하여', '하게', '하도록', '하기', '하다', '합니다', '하는데', '하려고', '하려', '으면', '려고', '려면서', '기도', '기는', '지만',
           '을', '를', '를', '은', '는', '이', '가', '에', '의', '도', '로', '으로', '와', '과', '랑', '이랑', '나', '이나', '만', '까지', '부터', '에서', '에는',
           '하고', '하면', '해서', '하는', '할', '한', '하나', '하려면', '하려는', '려면', '려는', '해야', '야', '해', '줘', '요', '면', '서', '고', '며', '데',
           '니', '까', '지', '자', '네', '인', '인가', '인지', '일', '들', '들이', '들은', '하', '시', '된', '되는', '될', '될때', '인데', '인데요', '때', '에도')
LIST_CUES = [r'종류', r'목록', r'리스트', r'뭐가\s*있', r'무엇이\s*있', r'어떤\s*(것|게|품|공종|공법|방법|작업)[^?]{0,8}(있|들)', r'(품|공종|기준)(에는|들은)\s*(뭐|무엇|어떤)',
             r'관련\s*(품|공종|품셈|기준)', r'어떤\s*것들']
VALUE_CUES = [r'일당', r'하루', r'1일', r'시공량', r'투입', r'인원', r'몇\s*(인|명|대|개|㎡|㎥|m|%)', r'수량', r'품(이|은)\s*(얼마|몇)', r'얼마',
              r'노무비', r'인건비', r'노임', r'인력품', r'[㎡㎥m㎏]\s*당', r'\d+\s*(㎡|㎥|m|mm|ton|톤|㎏|개소|개)\b']
RULE_CUES = [r'어떤\s*경우', r'어떻게\s*(적용|계상|잡|산정|구분)', r'적용(해|하나|돼|되|할)', r'계상', r'포함(돼|되|하|이)', r'제외', r'별도', r'할증', r'감하', r'가산',
             r'기준(은|이)', r'구분(해|하)', r'상태', r'무엇을\s*기준', r'공정', r'들어\s*있']
PER_DAY = re.compile(r'일당|하루|1일|일일')
PER_UNIT = re.compile(r'(\d+(?:\.\d+)?\s*)?(㎡|㎥|m|개소|개|톤|㎏|본|매|대)\s*(당|마다)')
def _jongseong(ch):
    c = ord(ch) - 0xAC00
    return c % 28 if 0 <= c < 11172 else 0


MULTI_CUE = re.compile(r'(하면서|하고|하며|및|그리고|이랑|랑\s|함께|같이|동시에|까지|[,，]|와\s|과\s)')
QPREFIX = ('종류', '목록', '리스트', '관련', '알려', '궁금', '어떤', '어떻', '얼마', '몇')
WORD = re.compile(r"[0-9a-z.]+(?:-[0-9a-z.]+)*|[가-힣]+")


def _pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * p))] if xs else None


class Selector:
    def __init__(self, rt):
        self.rt = rt
        self.idf = rt.bm25_all.idf
        self.n = len(rt.items)
        self.cfg = CONFIG
        # 절 메타·계층·조각 목록
        rows = rt.conn.execute("""select section_id, division, level, number, title, parent_section_id, first_page, start_order
                                  from rag_knowledge.sections where release_id=%s""", (rt.reader.rid,)).fetchall()
        self.sec = {r[0]: {'section_id': r[0], 'division': r[1], 'level': r[2], 'number': r[3], 'title': r[4], 'parent': r[5],
                           'first_page': r[6], 'order': r[7]} for r in rows}
        self.children = defaultdict(list)
        for s in self.sec.values():
            if s['parent']:
                self.children[s['parent']].append(s['section_id'])
        for k in self.children:
            self.children[k].sort(key=lambda x: self.sec[x]['order'])
        self.chunks_of = defaultdict(list)       # 절 -> [index] (ordinal 순)
        for i, x in enumerate(rt.items):
            self.chunks_of[x['section_id']].append(i)
        self.secarr = np.array([x['section_id'] or '' for x in rt.items])
        # 조각 특징: 기준(단위), 주석 표 여부, 표 앞 소제목 라벨
        self.basis, self.is_note_table, self.label = {}, {}, {}
        for sid, idxs in self.chunks_of.items():
            idxs.sort(key=lambda i: rt.items[i]['ordinal'])
            for pos, i in enumerate(idxs):
                x = rt.items[i]
                ctx = x['text'].split('\n')
                head = ctx[0] if ctx else ''
                self.is_note_table[i] = head.startswith('[주석 표]')
                m = re.findall(r'기준:\s*\(([^)]*)\)', x['text'])
                self.basis[i] = m[-1] if m else None
                lab = ''
                if x['kind'] == 'table' and pos > 0:
                    prev = rt.items[idxs[pos - 1]]
                    if prev['kind'] == 'rule':
                        body = prev['text'].split('\n', 2)[-1] if prev['text'].count('\n') >= 1 else prev['text']
                        last = [l for l in body.split('\n') if l.strip()]
                        if last and len(last[-1]) <= 40:
                            lab = last[-1]
                self.label[i] = lab

    # ---------- 질문 분석 ----------
    def stem(self, w):
        """낱말에서 조사·어미를 떼고 자료 어휘에 있는 가장 긴 앞부분을 돌려준다. 자료에 없으면 None."""
        if re.fullmatch(r'[0-9a-z.\-]+', w):
            return w if w in self.idf else None
        for L in range(len(w) - 1, 1, -1):          # 조사·어미를 뗀 꼴을 먼저(작업은 → 작업)
            if w[L:] in ENDINGS and w[:L] in self.idf:
                return w[:L]
        if w in self.idf and not (len(w) == 2 and w[-1] in '은는이가을를에의도로와과나'):
            return w
        for L in range(len(w) - 1, 1, -1):
            p = w[:L]
            if p in self.idf and (len(w) - L <= 2 and L >= 3):
                return p
        return None

    def analyze(self, query):
        nq = rv.normalize(query)                       # 검색·질문 임베딩에 쓰는 글(캐시 키와 같음)
        q = unicodedata.normalize('NFKC', nq).lower()  # 낱말 분석용
        stems, unsupported, ignored, groups = [], [], [], []
        for w in WORD.findall(q):
            if re.fullmatch(r'[0-9.]+', w) or w in QWORDS or w.startswith(QPREFIX):
                continue
            if any(w.endswith(e) and w[:-len(e)] in QWORDS for e in ENDINGS if len(e) < len(w)):
                continue
            s = self.stem(w)
            if s is None:
                if len(w) < 2:
                    continue
                func_like = (w.endswith(ENDINGS) or any(w.startswith(qw) for qw in QWORDS if len(qw) >= 2) or
                             (len(w) >= 2 and '가' <= w[-1] <= '힣' and _jongseong(w[-1]) in (4, 8)))   # ㄴ·ㄹ 받침 관형형
                (ignored if func_like and not re.fullmatch(r'[a-z0-9.\-]+', w) else unsupported).append(w)
            elif s in QWORDS:
                continue
            else:
                stems.append(s)
                # 합성어는 더 짧은 앞부분으로도 제목과 맞춘다(페인트칠 → 페인트)
                alts = [s] + [s[:k] for k in range(len(s) - 1, 2, -1) if s[:k] in self.idf and self.idf[s[:k]] >= self.cfg['idf_low']]
                groups.append(alts)
        stems = list(dict.fromkeys(stems))
        content = [s for s in stems if self.idf[s] >= self.cfg['idf_low']]
        txt = q
        cues = {'list': any(re.search(p, txt) for p in LIST_CUES), 'value': any(re.search(p, txt) for p in VALUE_CUES),
                'rule': any(re.search(p, txt) for p in RULE_CUES)}
        basis_cue = None
        if PER_UNIT.search(txt):
            basis_cue = ('per_unit', PER_UNIT.search(txt).group(2))
        elif PER_DAY.search(txt):
            basis_cue = ('per_day', None)
        has_num = bool(re.search(r'\d+-\d+(?:-\d+)?', txt))
        if cues['list'] and not cues['value']:
            intent = 'list'
        elif cues['value'] and cues['rule']:
            intent = 'mixed'
        elif cues['value']:
            intent = 'value'
        elif cues['rule']:
            intent = 'rule'
        elif has_num:
            intent = 'list'                     # 절 번호를 적은 질문은 그 번호의 절들을 찾는다
        else:
            intent = 'unclear'                  # 목적 신호가 없으면 표·설명을 함께 고르고 확인 필요로 둘 수 있다
        gset = [g for g in groups if self.idf[g[0]] >= self.cfg['idf_low']]
        return {'multi_cue': bool(MULTI_CUE.search(q)), 'normalized': nq, 'stems': content, 'stem_groups': gset, 'all_stems': stems, 'unsupported_terms': unsupported, 'ignored_terms': ignored,
                'cues': cues, 'intent': intent, 'basis_cue': basis_cue}

    # ---------- 전체 조각 점수 ----------
    def score_all(self, nq, division=None):
        rt = self.rt
        vec, embed_sec = rt.query_vector(nq)
        cos = rt.matrix @ (vec / np.linalg.norm(vec))
        bm = rt.bm25_all.search(nq, 8000)
        b = np.zeros(self.n, dtype=np.float32)
        for s, c in bm:
            b[rt.pos[c['chunk_id']]] = s
        med = float(np.median(cos))
        v = np.clip((cos - med) / max(float(cos.max()) - med, 1e-9), 0, None)
        bn = b / max(float(b.max()), 1e-9)
        f = self.cfg['score']['cos_weight'] * v + self.cfg['score']['bm25_weight'] * bn
        if division:
            f = np.where(rt.division_of == division, f, 0.0)
        return {'cos': cos, 'bm25': b, 'f': f.astype(np.float32), 'embed_sec': embed_sec}

    def coverage(self, groups, texts):
        """질문 핵심어 묶음(낱말과 그 앞부분 대안)이 글에 있는 비율(IDF 가중). 묶음 하나는 가장 긴 대안의 IDF로 센다."""
        if not groups:
            return None
        blob = ''.join(texts).replace(' ', '')
        tot = sum(self.idf[g[0]] for g in groups)
        got = 0.0
        for g in groups:
            if any(a in blob for a in g):
                got += self.idf[g[0]]
        return got / tot

    # ---------- 목록: 범위 공종 집합 ----------
    def title_explain(self, stems, title):
        """절 제목이 질문 핵심어로 설명되는 비율(글자 기준). 제목에 질문에 없는 낱말이 많을수록 낮다."""
        t = re.sub(r'[\s\d\-\.\(\)·･,/및]', '', title)
        if not t:
            return 0.0
        mask = [False] * len(t)
        for st in stems:
            for m in re.finditer(re.escape(st.replace(' ', '')), t):
                for k in range(m.start(), m.end()):
                    mask[k] = True
        return sum(mask) / len(t)

    def list_sections(self, an, sc):
        L = self.cfg['list']
        f = sc['f']
        best = {}
        for i, s in enumerate(self.secarr):
            if s and f[i] > best.get(s, -1):
                best[s] = float(f[i])
        order = sorted(best, key=lambda s: -best[s])
        top = best[order[0]] if order else 0.0
        groups = an['stem_groups']
        topk = sorted(groups, key=lambda g: -self.idf[g[0]])[:L['top_stems']]
        denom = sum(self.idf[g[0]] for g in topk) or 1.0
        nums = re.findall(r'\d+-\d+(?:-\d+)?', an['normalized'])
        members, why = {}, {}
        for s, v in best.items():
            sec = self.sec.get(s)
            if not sec or sec['level'] != 'section':
                continue
            par = self.sec.get(sec['parent'], {})
            path = (sec['title'] + par.get('title', '')).replace(' ', '')
            got = 0.0
            for g in groups:
                hit = next((a_ for a_ in g if a_ in path), None)
                if hit:
                    got += self.idf[hit]
            ps = min(1.0, got / denom)
            reason = None
            if sec['number'] in nums:
                reason = '질문에 적힌 절 번호와 같음'
            elif v >= L['seed_ratio'] * top:
                reason = '질문과 직접 맞는 절'
            elif ps >= L['path_min'] and v >= L['f_floor_ratio'] * top:
                reason = f"제목·상위 묶음 제목이 질문 핵심어와 맞음({ps:.0%})"
            if reason:
                members[s] = v
                why[s] = reason
        ranked = sorted(members, key=lambda s: -members[s])
        truncated = len(ranked) > L['max_sections']
        return {'sections': ranked[:L['max_sections']], 'why': why, 'scores': members, 'truncated': truncated, 'total_candidates': len(ranked),
                'top_score': top, 'ranking_top': order[:12]}

    # ---------- 특정 값·규칙: 절 안에서 필요한 조각 ----------
    def select_in_section(self, sid, an, sc, intent):
        f, cfg = sc['f'], self.cfg
        idxs = self.chunks_of.get(sid, [])
        scored = []
        for i in idxs:
            x = self.rt.items[i]
            s = float(f[i])
            reasons = []
            if x['kind'] == 'work':
                continue
            lab = self.label.get(i, '')
            if lab and an['stems']:
                lh = self.coverage(an['stem_groups'], [lab]) or 0.0
                if lh > 0:
                    s += cfg['label_weight'] * lh
                    reasons.append(f"앞 소제목 '{lab[:20]}'이 질문과 맞음")
            bc = an['basis_cue']
            if x['kind'] == 'table' and bc:
                b = self.basis.get(i)
                if b:
                    day = '일당' in b
                    if bc[0] == 'per_day' and not day and re.search(r'당', b):
                        s -= cfg['basis_mismatch_penalty']
                        reasons.append(f"질문은 일당 기준인데 표 기준은 ({b})")
                    elif bc[0] == 'per_unit' and day:
                        s -= cfg['basis_mismatch_penalty']
                        reasons.append(f"질문은 단위당 기준인데 표 기준은 ({b})")
                    else:
                        reasons.append(f'표 기준 ({b})이 질문 단위와 맞음')
            if x['kind'] == 'table' and self.is_note_table.get(i) and intent in ('value',):
                s -= cfg['note_table_penalty']
                reasons.append('주석 표(소속 위치 근거): 값 질문의 주 근거로는 낮게 봄')
            scored.append((s, i, reasons))
        scored.sort(key=lambda t: -t[0])
        return scored

    # ---------- 전체 ----------
    def run(self, query, budget=None, depth=None, _extra_ok=True):
        cfg = self.cfg
        budget = budget or cfg['evidence_budget_tokens']
        depth = cfg['evidence_depth'] if depth is None else depth
        an = self.analyze(query)
        division = rv.explicit_division(query)
        log = {'query': query, 'analysis': {k: an[k] for k in ('normalized', 'stems', 'unsupported_terms', 'ignored_terms', 'cues', 'intent', 'basis_cue')},
               'division_filter': division, 'extra_searches': [], 'steps': []}
        sc = self.score_all(an['normalized'], division)
        res = self._answer(an, sc, budget, depth, log)
        # 추가 검색(최대 2회): 부족 사유에 맞춰 범위를 정한다
        searches = 0
        while res['status'] != 'supported' and searches < cfg['extra_searches_max'] and _extra_ok:
            plan = self._plan_extra(an, res, log)
            if not plan:
                break
            searches += 1
            q2, why, kind = plan
            an2 = self.analyze(q2)
            for k in ('cues', 'intent', 'basis_cue', 'multi_cue'):     # 질문의 목적·단위·여러 공종 신호는 원래 질문에서 가져온다
                an2[k] = an[k]
            if kind == 'core_terms':                                    # 핵심어만 남긴 검색이라도 원래 질문의 자료에 없는 낱말은 그대로 미지원이다
                an2['unsupported_terms'] = an['unsupported_terms']
            sc2 = self.score_all(an2['normalized'], division)
            res2 = self._answer(an2, sc2, budget, depth, {'steps': []})
            better = self._better(res2, res)
            log['extra_searches'].append({'n': searches, 'kind': kind, 'reason': why, 'query': q2, 'filter': division,
                                          'status_before': res['status'], 'status_after': res2['status'],
                                          'adopted': better, 'added_sections': [s['section_id'] for s in res2.get('sections', [])
                                                                                if s['section_id'] not in {x['section_id'] for x in res.get('sections', [])}],
                                          'end_reason': '개선됨' if better else '개선되지 않음'})
            if better:
                res = res2
                an = an2
                res.setdefault('log_note', f'추가 검색 {searches}회({kind})로 보완')
            else:
                break
        # 상위 묶음 참조의 하위 절 탐색(질문 전체 추가 검색 2회에 포함). 후보만 제시하고 선택·확정하지 않는다
        res['group_target_search'] = []
        for g in res.get('pending_group_targets', []):
            if searches >= cfg['extra_searches_max'] or res['status'] == 'not_found':
                res.setdefault('skipped_group_targets', []).append({**g, 'reason': '추가 검색 2회 한도'})
                continue
            searches += 1
            fz = sc['f']
            cands = []
            for k in g['children']:
                idxs = self.chunks_of.get(k, [])
                if idxs:
                    cands.append((max(float(fz[i]) for i in idxs), k))
            cands.sort(reverse=True)
            top3 = [{'section_id': k, 'score': round(v, 4), 'title': self.sec[k]['title']} for v, k in cands[:cfg['group_target']['top_children']]]
            item = {'edge_id': g['edge_id'], 'from_section': g['from_section'], 'children': len(g['children']), 'candidates': top3,
                    'selected': None, 'status': 'candidates_not_confirmed' if top3 else 'unresolved',
                    'note': '후보만 제시한다. 한 절을 적용 확정으로 고르지 않는다. 질문이 가리키는 절을 못 고르면 미해결이다.'}
            res['group_target_search'].append(item)
            log['extra_searches'].append({'n': searches, 'kind': 'group_target', 'reason': '상위 묶음 참조의 하위 절 탐색', 'query': an['normalized'],
                                          'filter': g['from_section'], 'status_before': res['status'], 'status_after': res['status'],
                                          'adopted': False, 'returned': [t['section_id'] for t in top3], 'end_reason': '후보 제시(선택 없음)'})
        res['extra_searches'] = log['extra_searches']
        res['extra_searches_used'] = searches
        res['analysis'] = log['analysis']
        res['query'] = query
        res['embed_api_sec'] = sc['embed_sec']
        return res

    def _plan_extra(self, an, res, log):
        """부족 사유에 맞는 추가 검색 문구. 검색으로 고칠 수 있는 사유(낱말 불일치·약한 관련성)만 다시 검색한다.
        예산·모호한 참조·부분 확인은 검색으로 고쳐지지 않으므로 확인 필요로 남긴다. 같은 문구는 반복하지 않는다."""
        tried = {e['query'] for e in log['extra_searches']}
        if an['unsupported_terms']:
            q = an['normalized']
            changed = []
            for w in an['unsupported_terms']:
                for k, v in SYNONYMS.items():
                    if k in w:
                        q = q.replace(k, v)
                        changed.append(f'{k}→{v}')
            if changed and q not in tried:
                return q, f"질문 낱말이 자료에 없음({', '.join(an['unsupported_terms'])}): 일반 동의어 규칙 {', '.join(changed)}", 'synonym'
        rel = res.get('relevance', {})
        if rel.get('coverage') is not None and rel['coverage'] < self.cfg['relevance']['weak_cov_min'] + 0.1 and len(an['stems']) >= 2:
            core = ' '.join(an['stems'][:6])
            if core not in tried and core != an['normalized']:
                return core, '핵심어 관련도가 낮아 핵심어만으로 다시 검색(구어체·조사 제거)', 'core_terms'
        return None

    @staticmethod
    def _rank(res):
        return {'supported': 2, 'needs_confirmation': 1, 'not_found': 0}[res['status']]

    def _better(self, a, b):
        if self._rank(a) != self._rank(b):
            return self._rank(a) > self._rank(b)
        return (a.get('relevance', {}).get('coverage') or 0) > (b.get('relevance', {}).get('coverage') or 0) + 0.05

    def _answer(self, an, sc, budget, depth, log):
        cfg = self.cfg
        f = sc['f']
        intent = an['intent']
        res = {'intent': intent, 'sections': [], 'evidence_sets': [], 'list': None, 'diagnostic_candidates': []}
        # 후보 절(질문 종류와 무관하게 세 종류 조각 전체의 점수)
        best, bchunk = {}, {}
        for i, s in enumerate(self.secarr):
            if s and f[i] > best.get(s, -1):
                best[s] = float(f[i])
                bchunk[s] = i
        for s in list(best):               # 제목이 질문 핵심어로 잘 설명되는 절을 조금 앞세운다(형제 절 구별)
            sec = self.sec.get(s)
            if sec and sec['level'] == 'section':      # 상위 묶음은 제목이 질문과 같아도 개별 공종 근거를 대신하지 않는다
                best[s] += cfg['title_weight'] * self.title_explain([x for g in an['stem_groups'] for x in g], sec['title'])
        order = sorted(best, key=lambda s: -best[s])[:cfg['section_candidates']]
        top = best[order[0]] if order else 0.0
        rrf_top = []
        try:
            base = self.rt.search(an['normalized'], 'hybrid')
            rrf_top = [x['section_id'] for x in base['sections'][:3]]
        except Exception:
            pass
        for s_ in rrf_top:                  # 다른 검색 방식이 올린 상위 절도 후보로 둔다(1위를 정답으로 가정하지 않음)
            if s_ not in order and s_ in best:
                order.append(s_)
        res['diagnostic_candidates'] = [{'section_id': s, 'score': round(best[s], 4), 'best_chunk': self.rt.ids[bchunk[s]]} for s in order[:8]]
        if not order or top <= 0:
            res['status'] = 'not_found'
            res['relevance'] = {'reason': '후보 없음', 'coverage': 0.0}
            return res
        # --- 목록 ---
        if intent == 'list':
            lst = self.list_sections(an, sc)
            res['list'] = lst
            res['sections'] = [{'section_id': s, **{k: self.sec[s][k] for k in ('division', 'number', 'title', 'first_page')},
                                'why': lst['why'][s], 'score': round(lst['scores'][s], 4)} for s in lst['sections']]
            texts = [self.sec[s]['title'] for s in lst['sections']] + [self.sec.get(self.sec[s]['parent'], {}).get('title', '') for s in lst['sections']]
            cov = self.coverage(an['stem_groups'], texts)
            if any(w.startswith('질문에 적힌 절 번호') for w in lst['why'].values()):
                cov = 1.0 if cov is None or cov < 0.2 else cov
            res['relevance'] = self._relevance(an, cov, top_cos=float(sc['cos'].max()))
            res['status'] = res['relevance']['status']
            if lst['truncated']:
                res['status'] = 'needs_confirmation' if res['status'] == 'supported' else res['status']
                res['relevance'].setdefault('notes', []).append(f"공종 후보 {lst['total_candidates']}개 중 {len(lst['sections'])}개만 표시(추가 조회 필요)")
            return res
        # --- 특정 값·규칙·불분명 ---
        chosen = []                      # [(section_id, role, selected[(idx, reasons)])]
        covered = set()
        for s in order:
            if best[s] < cfg['complement_ratio'] * top:
                break
            sel = self.select_in_section(s, an, sc, intent)
            if not sel:
                continue
            kinds_wanted = self._wanted_kinds(intent)
            pool = [t for t in sel if self.rt.items[t[1]]['kind'] in kinds_wanted] or sel
            bestc = pool[0][0]
            ratio = cfg['chunk_rel_ratio'] if intent in ('value', 'mixed') else cfg['rule_rel_ratio']
            picked = [(i, r) for sco, i, r in pool if sco >= ratio * bestc and sco > 0][:6]
            if not picked:
                continue
            # 고른 설명 바로 아래의 주석 표는 그 설명이 소개하는 표다(문서 순서, 위치 근거). 함께 읽어 확인 문맥으로 둔다
            have = {i for i, _ in picked}
            ids_s = self.chunks_of[s]
            for i0, r0 in list(picked):
                if self.rt.items[i0]['kind'] == 'rule':
                    pos0 = ids_s.index(i0)
                    if pos0 + 1 < len(ids_s):
                        j = ids_s[pos0 + 1]
                        if self.is_note_table.get(j) and j not in have:
                            picked.append((j, ['설명 바로 아래 주석 표(위치 근거, 미확정)']))
                            have.add(j)
            # 고른 주석 표 바로 아래의 설명도 그 표의 설명이다(문서 순서, 위치 근거)
            for i0, r0 in list(picked):
                if self.is_note_table.get(i0):
                    pos0 = ids_s.index(i0)
                    if pos0 + 1 < len(ids_s):
                        j = ids_s[pos0 + 1]
                        if self.rt.items[j]['kind'] == 'rule' and j not in have and self.rt.items[j]['status'] != 'membership_unconfirmed':
                            picked.append((j, ['주석 표 바로 아래 설명(위치 근거, 미확정)']))
                            have.add(j)
            # 주석 표(위치 근거 후보)는 질문과 관련도가 높을 때만 더 고른다. 읽는 쪽에서 자동으로 붙이지 않는다
            for sco, i, r in sel:
                if i not in have and self.is_note_table.get(i) and sco >= 0.75 * picked[0][0] and sco > 0 and len(picked) < 8:
                    picked.append((i, r + ['주석 표 후보: 질문과 관련도가 높아 선택(소속은 위치 근거)']))
            text = ' '.join(self.rt.items[i]['text'] for i, _ in picked)
            path = (self.sec[s]['title'] + self.sec.get(self.sec[s]['parent'], {}).get('title', '')).replace(' ', '')
            cov_s = set(g[0] for g in an['stem_groups'] if any(a_ in path for a_ in g))     # 제목·상위 묶음 제목이 설명하는 핵심어
            tex = self.title_explain([x for g in an['stem_groups'] for x in g], self.sec[s]['title'])
            role = None
            if not chosen:
                role = 'primary'
                tex_primary = tex
            else:
                new = cov_s - covered
                p_cov = chosen[0][3]
                near_prev = abs(best[chosen[-1][0]] - best[s]) <= 0.05 * top and self.sec[s]['parent'] == self.sec[chosen[-1][0]]['parent']
                near_top = best[s] >= cfg['primary_section_ratio'] * top
                from_rrf = s in rrf_top and best[s] >= 0.75 * top
                n_comp = sum(1 for c in chosen if c[1] == 'complement')
                if an['multi_cue'] and new and best[s] >= cfg['complement_ratio'] * top and not near_prev and n_comp < 3:
                    role = 'complement'
                elif (near_top or from_rrf or near_prev) and cov_s >= p_cov and tex >= tex_primary - 0.15:
                    role = 'alternative'
            if role:
                chosen.append((s, role, picked, cov_s))
                covered |= cov_s
            if len(chosen) >= 5:
                break
        if not chosen:
            res['status'] = 'not_found'
            res['relevance'] = {'reason': '선택할 조각 없음', 'coverage': 0.0}
            return res
        # 근거 읽기: 구조 연결은 Reader가 원문 식별자로 읽는다. 절마다 예산을 따로 둔다(고정 개수 제한 아님)
        all_text = ''
        refsec = {}
        for s, role, picked, cov_s in chosen:
            ids = [self.rt.ids[i] for i, _ in picked]
            # 값 질문의 표는 앞 소제목 조각도 함께 읽는다(표 값을 구별하는 라벨)
            for i, _ in picked:
                lab_i = self._label_chunk(i)
                if lab_i and lab_i not in ids and self.rt.items[i]['kind'] == 'table':
                    ids.append(lab_i)
            r = self.rt.reader.read(ids, depth, max(budget, 1200 * len(ids)), include_cells=False,
                                    skip_related=('note_table_candidate', 'note_table_owner_candidate'))
            res['evidence_sets'].append({'section_id': s, 'role': role, 'selected': [
                {'chunk_id': self.rt.ids[i], 'kind': self.rt.items[i]['kind'], 'score': round(float(f[i]), 4), 'reasons': reasons}
                for i, reasons in picked], 'label_chunks': [c for c in ids[len(picked):]], 'result': r})
            res['sections'].append({'section_id': s, 'role': role, **{k: self.sec[s][k] for k in ('division', 'number', 'title', 'first_page')}})
            if role in ('primary', 'complement'):
                all_text += r['answer_context']['text']
                for cid, u in r['units'].items():
                    if u['section'] and any(w['kind'] == 'reference_target' for w in u['why_included']):
                        rs = u['section']['section_id']
                        if rs not in refsec:
                            refsec[rs] = {'section_id': rs, 'role': 'reference_target', 'division': u['section']['division'],
                                          'number': u['section']['number'], 'title': u['section']['title'], 'first_page': u['section']['first_page'],
                                          'from_section': s}
        res['reference_sections'] = list(refsec.values())
        primary_texts = [self.rt.items[i]['text'] + self.label.get(i, '') for s, role, picked, _ in chosen if role in ('primary', 'complement') for i, _ in picked]
        cov = self.coverage(an['stem_groups'], primary_texts + [self.sec[s]['title'] for s, role, _, _ in chosen if role in ('primary', 'complement')])
        res['relevance'] = self._relevance(an, cov, top_cos=float(sc['cos'].max()))
        res['status'] = res['relevance']['status']
        # 근거 충분성: 값 질문은 표가 있어야 하고, 미해결 참조·예산 제외가 남으면 확인 필요
        reasons = []
        prim = [e for e in res['evidence_sets'] if e['role'] in ('primary', 'complement')]
        if intent in ('value', 'mixed') and not any(any(c['kind'] == 'table' for c in e['selected']) for e in prim):
            reasons.append('값 질문인데 표 근거를 고르지 못함')
        for e in prim:
            r = e['result']
            unresolved = [u for u in r['unresolved_references'] if u['kind'] in ('ambiguous_target', 'missing_target', 'partial_target', 'budget',
                                                                                'group_target_not_expanded', 'subitem_chunk_not_found')]
            if unresolved:
                reasons.append(f"{e['section_id'].split(':', 1)[1]}: 미해결 참조 {sorted({u['kind'] for u in unresolved})}")
            if any(x['reason'] == 'budget' for x in r['excluded']):
                reasons.append(f"{e['section_id'].split(':', 1)[1]}: 예산 때문에 빠진 근거")
        if any(e['role'] == 'alternative' for e in res['evidence_sets']):
            reasons.append('같은 핵심어를 가진 다른 절이 비슷한 점수(대안 후보): 질문의 범위 확인 필요')
        if reasons and res['status'] == 'supported':
            res['status'] = 'needs_confirmation'
        res['insufficiency'] = reasons
        pend = []
        for e in prim:
            for u in e['result']['unresolved_references']:
                if u['kind'] == 'group_target_not_expanded':
                    pend.append({'edge_id': u['edge_id'], 'from_section': e['section_id'], 'children': [k['section_id'] for k in u['children']]})
        res['pending_group_targets'] = pend
        if res['status'] == 'not_found':
            # 관련 근거를 찾지 못함: 가까운 후보는 진단 정보로만 남기고 정상 답변 근거로 내보내지 않는다
            res['diagnostic_evidence'] = [{'section_id': e['section_id'], 'role': e['role'], 'selected': [c['chunk_id'] for c in e['selected']]}
                                          for e in res['evidence_sets']]
            res['evidence_sets'] = []
            res['diagnostic_sections'] = res['sections']
            res['sections'] = []
            res['reference_sections'] = []
        return res

    def _wanted_kinds(self, intent):
        return {'value': ('table',), 'rule': ('rule',), 'mixed': ('table', 'rule'), 'unclear': ('table', 'rule', 'work')}.get(intent, ('table', 'rule'))

    def _label_chunk(self, i):
        sid = self.rt.items[i]['section_id']
        idxs = self.chunks_of[sid]
        pos = idxs.index(i)
        if pos > 0 and self.rt.items[idxs[pos - 1]]['kind'] == 'rule' and self.label.get(i):
            return self.rt.ids[idxs[pos - 1]]
        return None

    def _relevance(self, an, cov, top_cos):
        R = self.cfg['relevance']
        notes = []
        unsup = an['unsupported_terms']
        c = cov if cov is not None else 0.0
        if unsup and c < R['unsupported_cov_max']:
            return {'status': 'not_found', 'coverage': round(c, 3), 'unsupported_terms': unsup, 'top_cosine': round(top_cos, 4),
                    'reason': f"질문의 낱말 {unsup}이(가) 자료에 없고 핵심어 {c:.0%}만 후보에 있음", 'notes': notes}
        if unsup:
            return {'status': 'needs_confirmation', 'coverage': round(c, 3), 'unsupported_terms': unsup, 'top_cosine': round(top_cos, 4),
                    'reason': f"질문의 낱말 {unsup}이(가) 자료에 없음(핵심어는 {c:.0%} 맞음)", 'notes': notes}
        if cov is not None and c < R['weak_cov_min']:
            return {'status': 'needs_confirmation', 'coverage': round(c, 3), 'unsupported_terms': [], 'top_cosine': round(top_cos, 4),
                    'reason': f'핵심어가 후보에 {c:.0%}만 있음(약한 관련성)', 'notes': notes}
        return {'status': 'supported', 'coverage': round(c, 3), 'unsupported_terms': [], 'top_cosine': round(top_cos, 4), 'reason': '핵심어가 후보에 있음', 'notes': notes}


def versions(sel):
    v = rv.versions(sel.rt)
    v['select_code_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    v['select_config_sha256'] = hashlib.sha256(json.dumps({'CONFIG': CONFIG, 'SYNONYMS': SYNONYMS, 'QWORDS': sorted(QWORDS),
                                                           'ENDINGS': list(ENDINGS), 'LIST_CUES': LIST_CUES, 'VALUE_CUES': VALUE_CUES,
                                                           'RULE_CUES': RULE_CUES}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return v




