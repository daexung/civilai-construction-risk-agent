"""5b단계 로컬 시험 답변 계층: 검색 상태와 답변 상태를 나누고, 모델은 원문 위치(S1.3)만 고르게 한다.

- 모델 출력의 인용은 위치 식별자뿐이다. 인용문·출처는 코드가 모델에 실제로 준 줄에서 가져온다(모델이 쓴 글은 쓰지 않는다).
- 모델에 주지 않은 줄·자료, 없는 줄, 모양이 틀린 식별자는 비슷한 식별자로 맞추지 않고 거절한다.
- 답변 값은 인용한 표 행·열·질문 조건 숫자와 대응하는지 코드가 따로 확인한다(문맥에 있다는 이유만으로 통과시키지 않는다).
- 모델·DB 없이 시험할 수 있는 순수 로직이다. 검색 정책·원문·청킹·벡터는 건드리지 않는다.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------- 상태
STATE_LABEL = {
    'confirmed': '답변 확인',
    'condition_unconfirmed': '질문 조건 확인 필요',
    'source_check_needed': '원문 확인 필요',
    'needs_confirmation': '확인 필요',
    'not_found': '근거를 찾지 못함',
    'error': '오류',
}
# 사용자에게 보이는 이유(쉬운 말). 내부 코드는 시험 정보로만 보낸다.
REASON_TEXT = {
    'verified': '질문의 조건에 대응한 설명이 원문 위치 확인을 통과했어요. 이 시험의 확인일 뿐 견적 계산 적용을 승인한 것은 아니에요.',
    'model_unmatched': '읽은 원문에서 질문의 조건에 맞는 값을 확인하지 못했어요. 문서 전체에 값이 없다는 뜻은 아니에요.',
    'condition_not_in_row': '고른 값의 행·열이 질문의 조건과 같은 칸이라고 확인되지 않아 값을 쓰지 않았어요.',
    'generation_failed': '설명을 만드는 중 문제가 생겨(시간 초과·연결 오류 등) 원문만 보여 드려요.',
    'validation_failed': '자동으로 만든 설명이 원문 위치·숫자 확인을 통과하지 못해 원문만 보여 드려요.',
    'context_budget': '읽어야 할 원문이 길어 설명에 모두 쓰지 못해 원문만 보여 드려요.',
    'cap_reached': '이번 시험의 호출 한도에 가까워 설명을 만들지 않고 원문만 보여 드려요.',
    'no_context': '설명에 쓸 원문 줄이 없어 원문만 보여 드려요.',
    'search_needs_confirmation': '검색 단계에서 소속·수식·범위 등을 확정하지 못했어요. 아래 이유와 확인할 것을 먼저 봐 주세요.',
    'search_not_found': '읽은 범위에서 질문에 맞는 근거를 찾지 못했어요. 문서 전체에 없다는 뜻은 아니에요.',
}
GEN_FAIL_CODES = {'generation_failed', 'context_budget', 'cap_reached', 'no_context'}

MONEY = re.compile(r"\d[\d,]*(?:\.\d+)?\s*원|[₩￦]|[천만억조]\s*원|KRW|원\s*[/／]", re.I)
LEAK = re.compile(r"금지되어|지시(?!부)|규칙상|제공된\s*문맥|원문에\s*직접\s*곱셈|곱하거나|환산하지|주의하여|안내합니다|제시된\s*자료|주어진\s*원문|\bS\d+(?:\.\d+)?\b")
NUM = re.compile(r'\d+(?:\.\d+)?')
SECTION = re.compile(r'\d+-\d+-\d+')
LOCATION = re.compile(r'\[?\s*(S\d+)\.(\d+)\s*\]?')
SHARED = re.compile(r'\s*\[공동값\s+(\S+?):\s+([^\]]*)\]')
MARK = re.compile(r'\[공동값#(\d+)\]')

QA_SCHEMA = {
    'type': 'object',
    'properties': {
        'status': {'type': 'string', 'description': 'answered | condition_unconfirmed | not_found'},
        'conclusion': {'type': 'string'},
        'explanation': {'type': 'string'},
        'evidence': {'type': 'array', 'items': {'type': 'object', 'properties': {
            'location': {'type': 'string'}, 'value': {'type': 'string'}, 'unit': {'type': 'string'}},
            'required': ['location', 'value', 'unit']}},
        'unmatched_conditions': {'type': 'array', 'items': {'type': 'string'}}},
    'required': ['status', 'conclusion', 'explanation', 'evidence', 'unmatched_conditions']}


# ---------------------------------------------------------------- 공동값 표지
def plain(text: str) -> str:
    """파이프라인이 칸에 덧붙인 [공동값 …] 표지를 뺀 글. 칸 대응 검사에 쓴다(원문 글 자체는 바꾸지 않는다)."""
    return SHARED.sub('', text or '').strip()


def compact(text: str, legend: dict[str, int], notes: dict[int, str]) -> str:
    """긴 공동값 표지를 [공동값#k]로 줄이고 관계 설명은 notes[k]에 모은다(설명이 같으면 같은 번호). 화면·모델 입력 표시용이며 값은 바꾸지 않는다.
    칸 식별자(c21 등)는 원문 줄 그대로 인용 기록의 shared_notes에 남는다."""
    def sub(m: re.Match) -> str:
        note = m.group(2).strip()
        k = legend.setdefault(note, len(legend) + 1)
        notes.setdefault(k, note)
        return f' [공동값#{k}]'
    return SHARED.sub(sub, text or '')


def shared_notes(text: str) -> list[dict]:
    return [{'cell': m.group(1), 'text': m.group(2).strip()} for m in SHARED.finditer(text or '')]


# ---------------------------------------------------------------- 숫자·칸 대응
def _clean(s: str) -> str:
    return re.sub(r'(?<=\d),(?=\d)', '', s or '')


def nums(s: str) -> list[float]:
    return [float(x) for x in NUM.findall(_clean(s))]


_RANGE = re.compile(r'(\d+(?:\.\d+)?)\s*(?:㎜|mm|㎝|cm|㎡|㎥|톤)?\s*[~～]\s*[øØφΦ]?\s*(\d+(?:\.\d+)?)')
_INEQ = re.compile(r'(\d+(?:\.\d+)?)\s*[^\d\s~|]{0,3}\s*(이하|미만|이상|초과)')
_OPS = {'이하': lambda x, a: x <= a, '미만': lambda x, a: x < a, '이상': lambda x, a: x >= a, '초과': lambda x, a: x > a}


def num_in(x: float, s: str) -> bool:
    """숫자 x가 칸 글에 글자 그대로 있거나, 그 칸의 a~b 범위·이하/미만/이상/초과 안에 든다."""
    s = _clean(s)
    return (x in nums(s) or any(float(a) <= x <= float(b) for a, b in _RANGE.findall(s))
            or any(_OPS[w](x, float(a)) for a, w in _INEQ.findall(s)))


_NUM_TOKEN = re.compile(r'\s*\d[\d.]*')


def value_nums(s: str) -> list[float]:
    """칸 글에서 a~b 범위·N이하 같은 조건 표기 안의 숫자(경계값)를 뺀 숫자. 이런 숫자는 품 값이 아니라 조건 경계다."""
    return nums(_INEQ.sub(' ', _RANGE.sub(' ', _clean(s))))


_COND = re.compile(r'[øØφΦ]\s*(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*(?:㎜|mm|㎝|cm|㎡|㎥|㎏|kg|톤|ton|%|m(?![A-Za-z]))')


def cond_numbers(question: str) -> list[float]:
    """질문의 규격·두께 같은 치수 숫자(단위가 붙거나 ø가 앞선 것). 절 번호·개수 표현은 뺀다."""
    q = _clean(SECTION.sub(' ', question or ''))
    out: list[float] = []
    for a, b in _COND.findall(q):
        x = float(a or b)
        if x not in out:
            out.append(x)
    return out


def question_numbers(question: str) -> set[float]:
    return set(nums(SECTION.sub(' ', question or '')))


def _groups(cols: list[str]) -> list[int]:
    """머리글이 같은 열 묶음을 반복하면(좌·우 두 벌 표) 묶음 번호를 매긴다. 아니면 모두 한 묶음."""
    key = [re.sub(r'\([^)]*\)|\s+', '', c) for c in cols]
    n = len(key)
    for k in range(2, n // 2 + 1):
        if n % k == 0 and all(key[i] == key[i % k] for i in range(n)):
            return [i // k for i in range(n)]
    return [0] * n


def cell_check(value: str, line: str, frame: list[str], conds: list[float]) -> dict:
    """값이 인용한 줄 안에 있고, 질문의 치수 조건이 같은 칸(열)·같은 행 묶음에 있는지 본다.

    - 머리글 칸 수와 줄의 칸 수가 같으면: 조건 숫자가 머리글 칸에 있으면 값은 그 열에 있어야 하고,
      머리글에 없으면(행 이름 칸) 값과 같은 열 묶음 안에 있어야 한다. 같은 길이의 값 목록이면 순서 위치도 맞아야 한다.
    - 그렇지 않으면 줄 안에 있는지만 본다('line_only'로 기록).
    반환 ok=False의 code: value_not_in_line | condition_mismatch
    """
    segs = [s.strip() for s in plain(line).split(' | ')]
    head = next((f.split(':', 1)[1].strip() for f in frame if f.startswith('머리글:')), '')
    cols = [c.strip() for c in head.split(' | ')] if head else []
    aligned = bool(cols) and len(cols) == len(segs)
    grp = _groups(cols) if aligned else None
    vs = nums(value)
    vtext = _clean(value).strip()
    if vs:
        vpos = [i for i, s in enumerate(segs) if vs[0] in value_nums(s)]
    else:
        vpos = [i for i, s in enumerate(segs) if vtext and vtext in s]
    out = {'ok': True, 'code': None, 'alignment': 'no_numeric_conditions' if not conds else ('column_row' if aligned else 'line_only'),
           'row_label': segs[0] if segs else None, 'column_name': None, 'conditions': []}
    if not vpos and vs and any(vs[0] in nums(s) for s in segs):     # 조건 경계값(예: 1.2~1.5이하의 1.5)을 가리킨 것: 값 대응 검사 대상이 아니다
        return {**out, 'alignment': 'condition_boundary'}
    if not vpos:
        return {**out, 'ok': False, 'code': 'value_not_in_line'}
    if aligned:
        out['column_name'] = cols[vpos[0]]
        out['row_label'] = next(segs[j] for j in range(len(segs)) if grp[j] == grp[vpos[0]])      # 값이 속한 열 묶음의 첫 칸
    for x in conds:
        cell = None
        if aligned:
            hcols = [j for j, c in enumerate(cols) if num_in(x, c)]
            if hcols:                                    # 열 조건: 값은 그 열에 있어야 한다
                ok = any(i in hcols for i in vpos)
                where, cell = 'column_header', (cols[next(i for i in vpos if i in hcols)] if ok else None)
            else:                                        # 행 조건: 같은 열 묶음의 행 이름 칸에 있어야 한다
                rows = [j for j, s in enumerate(segs) if num_in(x, s)]
                hit = next(((i, j) for i in vpos for j in rows if grp[j] == grp[i] and (j == i or _same_index(x, segs[j], vs, segs[i]))), None)
                ok, where = hit is not None, 'row'
                if hit:
                    seg = segs[hit[1]]
                    cell = seg if len(nums(seg)) < 2 else f'{_NUM_TOKEN.sub("", seg).strip()} {x:g}'     # 목록 칸은 조건과 같은 순서의 값만
        else:
            ok, where = any(num_in(x, s) for s in segs), 'line'
        out['conditions'].append({'number': x, 'ok': ok, 'where': where, 'cell': cell})
        if not ok:
            out.update(ok=False, code='condition_mismatch')
    return out


def _same_index(x: float, cond_seg: str, vs: list[float], val_seg: str) -> bool:
    """조건 칸과 값 칸이 같은 길이의 숫자 목록이면(한 칸에 여러 값을 쌓은 표) 같은 순서 위치여야 한다."""
    cs, vl = nums(cond_seg), nums(val_seg)
    if len(cs) != len(vl) or len(cs) < 2 or not vs:
        return True
    return any(a == x and b == vs[0] for a, b in zip(cs, vl))


# ---------------------------------------------------------------- 모델에 줄 문맥
def build_context(sources: list[dict], limit: int = 7000, per_source: int = 2500) -> tuple[str, dict, bool]:
    """정상 답변 근거(표·설명)에서 모델에 실제로 줄 줄만 모은다. 줄마다 위치 식별자(S1.3)를 붙인다.

    표에 선택 행이 있으면 틀과 선택 행만, 없으면 조각 전체. 주지 않은 줄은 provided에 없으므로 인용으로 받아들이지 않는다.
    반환: (문맥 글, provided, 잘림 여부). 잘리면 호출하지 않는다(조용히 줄이지도, 넓히지도 않는다).
    """
    parts, provided, used, truncated = [], {}, 0, False
    for idx, s in enumerate((x for x in sources if x['kind'] in ('표', '설명')), 1):
        alias = f'S{idx}'
        sel = [ln for ln in s['lines'] if ln['selected']]
        use = sel if (s['kind'] == '표' and sel) else s['lines']
        head = list(s['frame']) if (s['kind'] == '표' and sel) else []
        body = [f"{alias}.{ln['n']} {ln['display']}" for ln in use]
        marks = sorted({int(k) for ln in use for k in MARK.findall(ln['display'])})
        notes = {g['n']: g['text'] for g in s.get('shared_legend', [])}
        legend = [f'공동값#{k}: {notes[k]}' for k in marks if k in notes]
        text = '\n'.join(head + body + legend)
        if len(text) > per_source or used + len(text) > limit:
            truncated = True
            break
        used += len(text)
        label = f"{s['division']} {s['section_no']} {s['section_title']} · {s['kind']} · PDF {s['pdf_page']}쪽"
        parts.append(f'[{alias}] {label}\n{text}')
        provided[alias] = {'chunk_id': s['id'], 'kind': s['kind'], 'frame': list(s['frame']), 'label': label, 'n_total': len(s['lines']),
                           'lines': {ln['n']: ln for ln in use}}
    return '\n\n'.join(parts), provided, truncated


# ---------------------------------------------------------------- 모델 출력 검증
def _fail(code: str, **kw) -> dict:
    return {'state': 'failed', 'code': code, **kw}


def validate(raw, question: str, provided: dict) -> dict:
    """모델 출력을 검증하고 인용·값 기록을 만든다. 반환 state: answered | condition_unconfirmed | failed.

    failed(code): 원문 확인 필요로 이어지는 형식·위치·숫자 검증 실패.
    condition_unconfirmed(code): 모델이 값을 못 찾았다고 했거나, 고른 값의 칸이 질문 조건과 대응하지 않음.
    """
    if not isinstance(raw, dict) or raw.get('status') not in ('answered', 'condition_unconfirmed', 'not_found'):
        return _fail('schema')
    if not all(isinstance(raw.get(k), str) for k in ('conclusion', 'explanation')) or not isinstance(raw.get('evidence'), list) \
            or not isinstance(raw.get('unmatched_conditions'), list):
        return _fail('schema')
    qn = re.sub(r'\s+', '', question)
    unmatched = [u.strip() for u in raw['unmatched_conditions'] if isinstance(u, str) and u.strip() and re.sub(r'\s+', '', u) in qn]
    if raw['status'] != 'answered':       # 질문에 있는 표현만 확인 항목으로 남긴다(모델이 새로 쓴 표현은 버린다)
        return {'state': 'condition_unconfirmed', 'code': 'model_unmatched', 'unmatched': unmatched, 'model_status': raw['status']}
    text = raw['conclusion'] + '\n' + raw['explanation']
    if LEAK.search(text):
        return _fail('instruction_leak')
    if MONEY.search(text):
        return _fail('money')
    if not raw['evidence']:
        return _fail('citations_missing')
    cites: list[dict] = []
    claims: list[dict] = []
    conds = cond_numbers(question)
    table_text, expl_text = [], []
    for ev in raw['evidence']:
        if not isinstance(ev, dict) or not isinstance(ev.get('location'), str):
            return _fail('schema')
        m = LOCATION.fullmatch(ev['location'].strip())
        if not m:
            return _fail('location_malformed', location=ev['location'][:40])
        alias, n = m.group(1), int(m.group(2))
        p = provided.get(alias)
        if p is None:
            return _fail('source_not_provided', location=ev['location'][:40])
        if n not in p['lines']:
            return _fail('line_not_provided' if 1 <= n <= p['n_total'] else 'line_missing', location=f'{alias}.{n}')
        ln = p['lines'][n]
        loc = f'{alias}.{n}'
        if loc not in [c['location'] for c in cites]:
            cites.append({'location': loc, 'chunk_id': p['chunk_id'], 'line': n, 'kind': p['kind'], 'quote': ln['text'], 'display': ln['display'],
                          'page': ln.get('page'), 'search_uid': ln.get('search_uid'), 'shared_notes': shared_notes(ln['text']),
                          'frame': [f for f in p['frame'] if f.startswith(('기준:', '소제목:', '머리글:'))] if p['kind'] == '표' else [],
                          'unit_basis': next((f for f in p['frame'] if f.startswith('기준:')), None) if p['kind'] == '표' else None,
                          'first_cell': plain(ln['text']).split(' | ')[0] if p['kind'] == '표' else None})
            (table_text if p['kind'] == '표' else expl_text).append(plain(ln['text']))
        value = ev.get('value', '')
        unit = ev.get('unit', '')
        if not isinstance(value, str) or not isinstance(unit, str):
            return _fail('schema')
        if value.strip():
            claims.append({'value': value.strip(), 'unit': unit.strip(), 'location': loc, 'declared': True})
    # 답변 글에 쓴 표 숫자도 모두 값으로 보고 같은 칸 검사를 받는다(선언하지 않은 값이 통과하지 못하게)
    clean = _clean(SECTION.sub(' ', text))
    said = {float(x) for x in NUM.findall(clean)}
    qnums = question_numbers(question)
    declared = {nums(c['value'])[0] for c in claims if nums(c['value'])}
    cited_table = [c for c in cites if c['kind'] == '표']
    for x in sorted(said - qnums - declared):
        owner = next((c for c in cited_table if x in value_nums(plain(c['quote']))), None)
        if owner:
            claims.append({'value': f'{x:g}', 'unit': '', 'location': owner['location'], 'declared': False})
        elif not any(x in nums(plain(c['quote'])) for c in cited_table) and not any(x in nums(t) for t in expl_text):
            return _fail('numbers', detail=f'{x:g}')
    sections = set(SECTION.findall('\n'.join(l['text'] for p in provided.values() for l in p['lines'].values()) + question))
    if set(SECTION.findall(text)) - sections:
        return _fail('section')
    records, mismatch = [], None
    for cl in claims:
        c = next(x for x in cites if x['location'] == cl['location'])
        if c['kind'] != '표':
            records.append({**cl, 'alignment': 'explanation_line'})
            continue
        chk = cell_check(cl['value'], c['quote'], provided[cl['location'].split('.')[0]]['frame'], conds)
        if chk['code'] == 'value_not_in_line':
            return _fail('value_not_in_line', location=cl['location'], value=cl['value'][:30])
        unit_tokens = re.findall(r'[가-힣A-Za-z㎡㎥㎜]+', cl['unit'])
        if unit_tokens and not any(t in plain(c['quote']) + ' '.join(c['frame']) for t in unit_tokens):
            return _fail('unit_not_in_row', location=cl['location'], unit=cl['unit'][:20])
        records.append({**cl, 'row_label': chk['row_label'], 'column_name': chk['column_name'], 'unit_basis': c['unit_basis'],
                        'alignment': chk['alignment'], 'conditions': chk['conditions'], 'matches_question_conditions': chk['ok']})
        if not chk['ok'] and mismatch is None:
            mismatch = records[-1]
    if mismatch:
        return {'state': 'condition_unconfirmed', 'code': 'condition_not_in_row', 'unmatched': [], 'rejected_claim': mismatch}
    return {'state': 'answered', 'code': 'verified', 'citations': cites, 'values': records,
            'text': raw['conclusion'].strip() + (('\n\n' + raw['explanation'].strip()) if raw['explanation'].strip() else '')}


# ---------------------------------------------------------------- 검색 상태 → 답변 상태
def answer_state(search_status: str, gen: dict | None) -> tuple[str, str]:
    """(답변 상태, 이유 코드). 검색이 supported여도 원문 검증을 통과한 설명이 있을 때만 '답변 확인'이다."""
    if search_status == 'needs_confirmation':
        return 'needs_confirmation', 'search_needs_confirmation'
    if search_status == 'not_found':
        return 'not_found', 'search_not_found'
    if search_status != 'supported':
        return 'error', 'unknown_search_status'
    g = gen or {}
    st, code = g.get('state'), g.get('code')
    if st == 'answered':
        return 'confirmed', 'verified'
    if st == 'condition_unconfirmed':
        return 'condition_unconfirmed', code or 'model_unmatched'
    if code in GEN_FAIL_CODES:
        return 'source_check_needed', code
    return 'source_check_needed', 'validation_failed' if st == 'failed' else 'generation_failed'


def condition_text(unmatched: list[str]) -> str:
    base = '읽은 원문에서 질문의 조건에 맞는 값을 확인하지 못했어요.'
    if unmatched:
        base += ' 확인하지 못한 조건: ' + ', '.join(unmatched) + '.'
    return base + ' 다른 두께·규격의 값을 대신 쓰지 않았어요. 아래 원문 표에서 조건에 맞는 칸이 있는지 직접 확인해 주세요.'
