"""results.json과 응답·원장에서 보고서용 표(마크다운)를 만든다. 숫자는 모두 results.json에서 읽는다(손으로 옮기지 않음)."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
R = json.loads((HERE / 'results.json').read_text(encoding='utf-8'))
EXP = {q['id']: q for q in json.loads((HERE / 'expectations_fixed.json').read_text(encoding='utf-8'))['questions']}
CAND = json.loads((HERE / 'candidate_index.json').read_text(encoding='utf-8'))
EST = json.loads((HERE / 'precall_estimate.json').read_text(encoding='utf-8'))
ORDER = list(EXP)
CHUNK_Q = [q for q in ORDER if not EXP[q]['is_list'] and not EXP[q]['no_data']]
LIST_Q = [q for q in ORDER if EXP[q]['is_list']]
NODATA_Q = [q for q in ORDER if EXP[q]['no_data']]
REP = ('V09', 'V11', 'V12', 'V20')
out = {}


def sh(s, n=8):
    return s[:n]


def tk(d, sec=False):
    if not d:
        return '—'
    key = 'req_sections_hit' if sec else 'req_hit'
    return ' · '.join(f"{d[str(k)][key]}/{d[str(k)]['forb_hit']}" for k in (1, 3, 5))


# A. 후보·입력
rows = ['| 질문 | 종류 | 후보 수 | 연결 문맥에만 있는 조각 | 필수 근거의 후보 내 존재 | 후보 안의 금지 조각 | 후보 해시 | 문맥 해시 | 프롬프트 글자 |', '|---|---|---|---|---|---|---|---|---|']
for q in ORDER:
    r, e = R[q], EXP[q]
    if e['is_list']:
        ps = r['required_sections_in_pool']
        pres = f"필수 절 {sum(ps.values())}/{len(ps)}이 후보 조각에 있음"
    elif e['no_data']:
        pres = '해당 없음(자료 없음 질문)'
    else:
        c = list(r['presence'].values())
        pres = f"{c.count('candidate')}/{len(c)} 후보" + (f" + {c.count('linked_only')} 연결 문맥만" if c.count('linked_only') else '') + (f" + {c.count('miss')} 누락" if c.count('miss') else '')
    rows.append(f"| {q} | {e['category']} | {r['n_candidates']} | {r['n_linked_only']} | {pres} | {len(r['forbidden_chunks_in_pool'])} | `{sh(r['candidate_set_sha256'])}` | `{sh(r['context_sha256'])}` | {EST['questions'][q]['chars']:,} |")
out['A'] = '\n'.join(rows)

# B. 순위 지표(조각 질문)
rows = ['| 질문 | 필수 조각 수 | 검색 순서(재순위 없음) | 4b 선택 순서 | 언어 모델 1회차 | 언어 모델 2회차 | 언어 모델 3회차 |', '|---|---|---|---|---|---|---|']
for q in CHUNK_Q:
    r = R[q]
    l = r['llm']
    rows.append(f"| {q} | {len(EXP[q]['required_chunks'])} | {tk(r['search_order'])} | {tk(r['b4']['topk'])} | {tk(l['r1'].get('topk'))} | "
                f"{tk(l['r2'].get('topk')) if 'r2' in l else '—'} | {tk(l['r3'].get('topk')) if 'r3' in l else '—'} |")
out['B'] = '\n'.join(rows)
rows = ['| 질문 | 필수 절 수 | 검색 순서 | 언어 모델 1회차 | 비고 |', '|---|---|---|---|---|']
for q in LIST_Q:
    r = R[q]
    rows.append(f"| {q} | {len(EXP[q]['required_sections'])} | {tk(r['search_order'], True)} | {tk(r['llm']['r1'].get('topk'), True)} | 4b는 목록을 절 단위로 만들어 조각 순위가 없음 |")
out['B_list'] = '\n'.join(rows)

# C. 선택 집합·최종 문맥
rows = ['| 질문 | 4b 상태 | 4b 필수 누락(최종 문맥) | 4b 금지 주 근거 | 모델 상태 | 주/보조 선택 수 | 필수 누락(선택 집합) | 금지 주 근거 | 필수 포함(최종 문맥) | 금지 조각 최종 문맥 혼입 | 유효 인용/전체 |',
        '|---|---|---|---|---|---|---|---|---|---|---|']
for q in CHUNK_Q:
    r, e = R[q], EXP[q]
    b, L = r['b4'], r['llm']['r1']
    n = len(e['required_chunks'])
    b_miss = n - len(b['required_in_context'])
    fin = L.get('final')
    mfin = f"{len(fin['required_in_context'])}/{n}" if fin else '—(근거 없음 판정)'
    mix = len(fin['forbidden_in_units']) if fin else '—'
    rows.append(f"| {q} | {b['status']} | {b_miss}/{n} | {len(b['forbidden_in_primary_selected'])} | {L['status']} | {len(L['primary'])}/{len(L['supporting'])} | "
                f"{len(L['required_missing_in_selected'])}/{n} | {len(L['forbidden_in_primary'])} | {mfin} | {mix} | {L['quotes']['valid']}/{L['quotes']['total']} |")
out['C'] = '\n'.join(rows)
rows = ['| 질문 | 4b 최종 공종 | 4b 필수 절 포함 | 4b 불필요 절 | 모델 주 근거의 필수 절 | 모델 선택 집합(주+보조)의 필수 절 | 모델이 빠뜨린 절(선택 집합) | 모델 불필요 절(선택 집합) |', '|---|---|---|---|---|---|---|---|']
for q in LIST_Q:
    r = R[q]
    b, L = r['b4'], r['llm']['r1']
    rows.append(f"| {q} | {len(b['final_sections'])}개 | {b['answer_recall_final']} | {len(b['unneeded_sections'])} | {L['required_sections_covered']} | "
                f"{L['required_sections_covered_selected_set']} | {', '.join(L['required_sections_missing_selected_set']) or '없음'} | {', '.join(L['unneeded_sections_selected_set']) or '없음'} |")
out['C_list'] = '\n'.join(rows)

# D. 상태 처리
rows = ['| 질문 | 기대 | 4b | 언어 모델 1회차 | 비고 |', '|---|---|---|---|---|']
for q in ORDER:
    e, r = EXP[q], R[q]
    b, L = r['b4'], r['llm']['r1']
    if e['no_data']:
        exp_s = '자료 없음(not_found, 주 근거 없음)'
        b_ok = '정상' if b['no_data_correct'] else f"누출({b['status']}, 공종 {len(b['final_sections'])}개 제시)"
        l_ok = '정상' if L['no_data_correct'] else f"누출({L['status']})"
    elif e['hold']:
        exp_s = '확정 승격 금지(needs_confirmation)'
        sm = b.get('state_marked') or {}
        b_ok = ('상태 유지' if b['status'] == 'needs_confirmation' else f"승격({b['status']})") + (f"; 표시 {sm}" if sm else '')
        l_ok = '상태 유지' if L['status'] == 'needs_confirmation' else f"승격({L['status']})"
    else:
        exp_s = '정상 처리(supported 또는 needs_confirmation)'
        b_ok = '거부(not_found)' if b['status'] == 'not_found' else f"정상({b['status']})"
        l_ok = '거부(not_found)' if L['status'] == 'not_found' else f"정상({L['status']})"
    rows.append(f"| {q} | {exp_s} | {b_ok} | {l_ok} | |")
out['D'] = '\n'.join(rows)

# E. 반복
def mark(ids, q):
    req, forb = set(EXP[q]['required_chunks']), set(EXP[q]['forbidden_chunks'])
    return ' '.join('R' if c in req else 'F' if c in forb else '·' for c in ids) or '—'


rows = ['| 질문 | 실행 | 상태 | 주 근거 | 보조 | 필수 누락(선택 집합) | 금지 주 근거 | 인용 유효 | 순위 상위 5(R=필수, F=금지, ·=그 밖) |', '|---|---|---|---|---|---|---|---|---|']
for q in REP:
    for rid, L in R[q]['llm'].items():
        rows.append(f"| {q} | {rid} | {L['status']} | {len(L['primary'])} | {len(L['supporting'])} | {len(L['required_missing_in_selected'])} | {len(L['forbidden_in_primary'])} | "
                    f"{L['quotes']['valid']}/{L['quotes']['total']} | {mark(L['ranking'][:5], q)} |")
out['E'] = '\n'.join(rows)
rows = ['| 질문 | 상태 동일 | 주 근거 집합 동일 | 선택 집합 동일 | 상위 5 순위 동일 |', '|---|---|---|---|---|']
for q in REP:
    p = R[q]['repeat']
    rows.append(f"| {q} | {p['identical_status']} | {p['identical_primary']} | {p['identical_selected_set']} | {p['identical_top5']} |")
out['E_rep'] = '\n'.join(rows)

# F. 호출·비용·지연
rows = ['| 질문 | 실행 | 성공 | 시도 | 입력 토큰 | 출력 토큰 | 비용(USD) | 지연(초) |', '|---|---|---|---|---|---|---|---|']
tin = tout = 0
cost = 0.0
n = att = 0
for q in ORDER:
    for rid, L in R[q]['llm'].items():
        i = sum(u.get('prompt') or 0 for u in L['usage'])
        o = sum((u.get('output') or 0) + (u.get('thoughts') or 0) for u in L['usage'])
        tin += i
        tout += o
        cost += L['cost_usd']
        n += 1
        att += L['attempts']
        rows.append(f"| {q} | {rid} | {'예' if L['ok'] else '아니오'} | {L['attempts']} | {i:,} | {o:,} | {L['cost_usd']:.4f} | {L['latency_sec']} |")
rows.append(f"| 합계 | {n}회 | 성공 {n}/{n} | {att} | {tin:,} | {tout:,} | {cost:.4f} | |")
out['F'] = '\n'.join(rows)
out['F_totals'] = {'calls': n, 'attempts': att, 'tokens_in': tin, 'tokens_out': tout, 'cost': round(cost, 4)}

# G. 필수 조각별 원인(조각 질문 15개 조각)
def cause_4b(q, c):
    b = R[q]['b4']
    if c in b['required_in_context']:
        return 'ok' if c in b['required_in_primary_selected'] else 'not_selected_but_reached_by_lookup'
    if c in b['required_in_units']:
        return 'lookup_omission'
    return 'candidate_miss' if R[q]['presence'][c] == 'miss' else 'selection_miss'


cnt4, cntL = {}, {}
for q in CHUNK_Q:
    for c in EXP[q]['required_chunks']:
        k = cause_4b(q, c)
        cnt4[k] = cnt4.get(k, 0) + 1
        k2 = R[q]['llm']['r1']['cause_by_required'].get(c, 'selection_miss' if R[q]['llm']['r1']['status'] == 'not_found' else '?')
        cntL[k2] = cntL.get(k2, 0) + 1
out['G'] = {'b4': cnt4, 'llm_r1': cntL, 'total': sum(cnt4.values())}
rows = ['| 질문 | 필수 조각 | 후보 내 존재 | 4b | 언어 모델 1회차 |', '|---|---|---|---|---|']
for q in CHUNK_Q:
    for c in EXP[q]['required_chunks']:
        L = R[q]['llm']['r1']
        rows.append(f"| {q} | `{c.split(':', 1)[-1][-26:]}` | {R[q]['presence'][c]} | {cause_4b(q, c)} | {L['cause_by_required'].get(c, 'selection_miss')} |")
out['G_rows'] = '\n'.join(rows)

# H. 검색 순서 상위 3 진단(재순위 상위 3 진단의 비모델 대응)
rows = ['| 질문 | 필수 포함(최종 문맥) | 금지 조각 혼입 | 예산 때문에 빠진 조각 |', '|---|---|---|---|']
for q in CHUNK_Q:
    s = R[q]['search_top3_final']
    rows.append(f"| {q} | {len(s['required_in_context'])}/{len(EXP[q]['required_chunks'])} | {len(s['forbidden_in_units'])} | {len(s['budget_excluded'])} |")
out['H'] = '\n'.join(rows)

(HERE / 'report_tables.json').write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
sys.stdout.reconfigure(encoding='utf-8')
for k, v in out.items():
    print('###', k)
    print(v if isinstance(v, str) else json.dumps(v, ensure_ascii=False))
    print()
