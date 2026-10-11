"""가로 선 없이 여러 행이 줄로 쌓인 표를 원문 글자 위치로 다시 짠다(표별 교정 자료에 적힌 표만).

원래 ODL 표의 열(세로 선)과 행 띠(가로 선)는 그대로 둔다. 띠 안에서만 PDF 글자 줄의 기준선으로 논리 행을 정한다.

  - 줄: 띠 안 글자를 기준선(차이 LINE_TOL 이하)으로 묶은 것. 글자는 자기 기준선이 속한 줄의 논리 행에 간다.
  - 기준 열(anchor_cols)에 글이 없는 줄은 바로 위 논리 행에 이어진 줄로 합친다(줄바꿈된 이름·규격의 둘째 줄).
  - 공통 칸: 띠 안에서 줄이 하나뿐인 비기준 열 칸(논리 행이 둘 이상일 때)과 교정 자료가 지정한 칸(shared)은
    띠의 모든 논리 행에 걸친 병합 칸이다. split에 적은 칸은 한 줄이어도 나눈다. 여러 띠에 걸친 원래 병합 칸은 그대로다.
  - 나란한 독립 목록(groups): 열 묶음마다 따로 논리 행을 만든다. 한 논리 행에는 한 묶음의 칸만 있다.
  - 띠의 첫 기준 열 줄보다 위에 있는 기준 열 없는 줄은 그 아래 첫 논리 행에 붙는다(가운데 맞춘 이름 위의 값 줄).
  - 값 없는 이름 줄 잇기(merge_label_only): true면 값 없이 시작한 행 뒤의, 'always'면 어느 행 뒤든 기준 열에만 글이 있고 값이 없는 줄은 위 논리 행의 이름에 잇는다(긴 이름의 줄바꿈).
  - 묶음 괄호(bracket_groups): 기준 열 안의 세로 괄호 선 왼쪽에 있는 값 없는 이름 줄은, 괄호 높이 안에 있는 논리 행들의
    이름 앞에 붙는다(예: 목재 [각재/판재]). 괄호 선 위치를 칸에 보관한다.
  - 행 시작 표시(anchor_start {열: 정규식}): 그 기준 열 줄이 정규식으로 시작할 때만 새 논리 행(예: '1.' 번호 항목)
  - 가운데 맞춤 열(center_cols): 이 열의 줄은 행을 만들지 않고, 줄 위치가 가장 가까운 논리 행(그 행 줄들의 가운데)에 붙는다
  - 순서 대응 열(order_cols): 이 열의 줄은 행을 만들지 않고, 줄 수가 논리 행 수와 같을 때만 k번째 줄을 k번째 행에 붙인다
    (값이 항목 높이와 맞지 않게 같은 간격으로 놓인 표. 수가 다르면 오류)
  - 아래 행 열(down_cols): 이 열의 줄은 행을 만들지 않고, 줄 바로 아래(같은 높이 포함) 첫 논리 행에 붙는다
    (행 사이에 놓인 설명 줄이 아래 행 값을 설명하는 표. 548쪽 비고 산식)
  - 사이 걸침 열(between_cols): 이 열의 줄이 두 논리 행의 첫 줄 사이에 있으면 두 행에 걸친 병합 칸, 한 행 줄과 맞으면 그 행
  - 나누는 열(split_cols): 한 줄뿐이어도 공통 칸으로 두지 않고 그 줄의 행에 둔다
  - 아래로 걸치는 열(fill_down_cols): 이 열의 칸은 같은 띠에서 그 열의 다음 글이 있는 행 바로 앞까지 걸친 병합 칸(예: 기종 이름)
  - 이어진 줄 글자(continue_texts): 원문 대조로 이름의 둘째 줄임을 확인한 기준 열 글(예: '공급설비')
  - 단계 제목(heading_levels [정규식...]): 기준 열 줄이 k번째 정규식으로 시작하면 k단계. 값 없는 단계 줄은 제목이 되어
    더 깊은 단계 행 이름 앞에 차례로 붙고, 같은 단계 이하가 나오면 끝난다(예: (1) > ㉮ > ㉠).
  - 줄 끝에서 나뉜 숫자(number_wrap_cols): 이 열에서 소수 줄 바로 아래의 숫자만 있는 줄은 윗줄 숫자의 끝자리다
    (836쪽 '0.097' / '5' = 0.0975). 글자 위치는 그대로 두고 윗줄 기준선으로 옮겨 한 값으로 읽는다.
  - 설명 묶음 열(block_cols {열: 정규식}): 이 열의 줄 중 정규식으로 시작하는 줄부터 다음 시작 줄 앞까지가 설명 한 덩어리다.
    덩어리는 그 높이 범위에 첫 줄이 있는 논리 행 전체에 걸친 병합 칸이 된다(889쪽 '3. 본체조립설치 / 본체 Frame …'은
    철골공·비계공·기계설비공·용접공 네 행 공통 작업 설명). 범위 안에 행이 없으면 덩어리만으로 한 행을 만든다.
  - 묶음 제목 줄(heading_bands): 기준 열에만 글이 있고 다른 열에 글이 없는 줄은 행이 되지 않고,
    같은 띠·같은 묶음의 뒤 논리 행 기준 열 이름 앞에 붙는다(제목 줄의 원문 위치를 칸에 보관).
칸 글은 원문 글자를 줄·x 순서로 읽은 것이다. 글자 사이가 글자 높이의 0.3배보다 넓으면 공백 하나를 둔다.
"""
import collections

LINE_TOL = 2.5      # 같은 줄로 보는 기준선 차이(pt). 값 숫자와 항목 글자가 2pt 어긋난 표가 있음(78쪽), 행 간격은 12pt 이상


def native(box, height):
    return [box[0], height - box[3], box[2], height - box[1]]


def page_chars(page, rect):
    out = []
    for b in page.get_text('rawdict')['blocks']:
        for l in b.get('lines', []):
            for sp in l['spans']:
                for ch in sp['chars']:
                    if not ch['c'].strip():
                        continue
                    x = (ch['bbox'][0] + ch['bbox'][2]) / 2
                    y = ch['origin'][1]
                    if rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]:
                        out.append((y, x, ch['c'], tuple(ch['bbox'])))
    return out


def text_of(chars):
    lines = []
    for c in sorted(chars):
        if lines and abs(c[0] - lines[-1][0][0]) <= LINE_TOL:
            lines[-1].append(c)
        else:
            lines.append([c])
    out = []
    for ln in lines:
        ln.sort(key=lambda c: c[1])
        s = ''
        for i, c in enumerate(ln):
            if i and c[3][0] - ln[i - 1][3][2] > 0.3 * (c[3][3] - c[3][1]):
                s += ' '
            s += c[2]
        out.append(s.strip())
    return '\n'.join(out)


def cluster(ys):
    out = []
    for y in sorted(ys):
        if out and y - out[-1][-1] <= LINE_TOL:
            out[-1].append(y)
        else:
            out.append([y])
    return [sum(c) / len(c) for c in out]


def join_wrapped_numbers(chars):
    import re
    lines = []
    for c in sorted(chars):
        if lines and abs(c[0] - lines[-1][0][0]) <= LINE_TOL:
            lines[-1].append(c)
        else:
            lines.append([c])
    out = list(lines[0]) if lines else []
    prev = lines[0] if lines else None
    for ln in lines[1:]:
        t = ''.join(c[2] for c in sorted(ln, key=lambda c: c[1]))
        pt = ''.join(c[2] for c in sorted(prev, key=lambda c: c[1]))
        if re.fullmatch(r'\d+', t) and re.fullmatch(r'\d*\.\d+', pt) and ln[0][0] - prev[0][0] < 16:
            y = (prev[0][0] + ln[0][0]) / 2      # 두 줄 가운데: 값은 행 이름과 가운데 맞춤(836쪽)
            x = max(c[1] for c in prev)
            moved = [(y, c[1], c[2], c[3]) for c in prev]
            for c in prev:
                out.remove(c)
            ln = [(y, x + 0.01 * (i + 1), c[2], c[3]) for i, c in enumerate(sorted(ln, key=lambda c: c[1]))]
            prev = moved + ln
            out.extend(prev)
            continue
        out.extend(ln)
        prev = ln
    return out


def nearest(lines, y):
    return min(range(len(lines)), key=lambda i: abs(lines[i] - y))


def bbox_of(chars, xbox):
    return [xbox[0], min(c[3][1] for c in chars), xbox[2], max(c[3][3] for c in chars)]


def regrid(node, page, cfg, header_rows):
    """ODL 표 노드 -> 다시 짠 표 노드. 머리글(원래 행 header_rows개)은 원래 칸 그대로 옮긴다."""
    H = page.rect.height
    cells = [c for r in node.get('rows') or [] for c in (r.get('cells') or [])]
    ybounds, xbounds = collections.defaultdict(list), collections.defaultdict(list)
    for c in cells:
        b = native(c['bounding box'], H)
        r0, c0 = c['row number'] - 1, c['column number'] - 1
        ybounds[r0].append(b[1]); ybounds[r0 + c.get('row span', 1)].append(b[3])
        xbounds[c0].append(b[0]); xbounds[c0 + c.get('column span', 1)].append(b[2])
    med = lambda v: sorted(v)[len(v) // 2]
    ys = {k: med(v) for k, v in ybounds.items()}
    xs = {k: med(v) for k, v in xbounds.items()}
    n_cols, n_bands = node['number of columns'], node['number of rows']
    base_anchors = anchors = set(cfg.get('anchor_cols', [0]))
    groups = cfg.get('groups') or [list(range(n_cols))]
    force_shared = {tuple(x) for x in cfg.get('shared', [])} | {(c, b) for c in cfg.get('shared_cols', [])
                                                                   for b in range(n_bands)}
    force_split = {tuple(x) for x in cfg.get('split', [])} | {(c, b) for c in cfg.get('split_cols', []) for b in range(n_bands)}
    fill_down = set(cfg.get('fill_down_cols', []))
    headings = set(cfg.get('heading_bands', []))
    out = []
    for c in cells:
        if c['row number'] - 1 < header_rows:
            out.append({'r0': c['row number'] - 1, 'r1': c['row number'] - 1 + c.get('row span', 1),
                        'c0': c['column number'] - 1, 'c1': c['column number'] - 1 + c.get('column span', 1),
                        'orig': c, 'kind': 'header'})
    grid_row, band_first, multi = header_rows, {}, []
    source_chars, used = [], collections.Counter()      # 원문 글자가 정확히 한 번씩 쓰였는지 확인
    heading_uses = collections.Counter()                # 묶음 제목 글자(뒤 행마다 의도적으로 되풀이)
    # 띠 = 원래 행 범위. merge_bands에 적은 [시작, 끝] 원래 행(0부터, 끝 포함)은 한 띠로 다시 짠다
    merged = {tuple(m) for m in cfg.get('merge_bands', [])}
    ranges, r = [], header_rows
    while r < n_bands:
        m = next((m for m in merged if m[0] == r), None)
        ranges.append((r, (m[1] if m else r) + 1)); r = ranges[-1][1]
    for band, band_end in ranges:
        band_first[band] = grid_row
        inside = lambda c: band <= c['row number'] - 1 and c['row number'] - 1 + c.get('row span', 1) <= band_end
        in_band = [c for c in cells if inside(c) and c['row number'] - 1 >= header_rows]
        multi += [c for c in cells if c['row number'] - 1 == band and not inside(c)]
        import odl_tables
        if any(odl_tables.find_tables(c) for c in in_band):
            # 칸 안 작은 표가 있는 띠는 원래 칸 그대로 둔다(작은 표 구조를 글로 풀지 않는다)
            for c in in_band:
                out.append({'r0': grid_row, 'r1': grid_row + 1, 'c0': c['column number'] - 1,
                            'c1': c['column number'] - 1 + c.get('column span', 1), 'orig': c, 'kind': 'nested_band'})
            grid_row += 1
            continue
        info = []
        for c in in_band:
            c0, c1 = c['column number'] - 1, c['column number'] - 1 + c.get('column span', 1)
            rr = c['row number'] - 1
            box = [xs[c0], ys[rr], xs[c1], ys[rr + c.get('row span', 1)]]
            ch = page_chars(page, box)
            if c0 in set(cfg.get('number_wrap_cols', [])):
                ch = join_wrapped_numbers(ch)
            info.append({'cell': c, 'c0': c0, 'c1': c1, 'box': box, 'chars': ch, 'lines': cluster([x[0] for x in ch])})
            source_chars.extend(ch)
        rows_here = []    # (y_first, group, cells: [(info, chars)], heading)
        # 기준 열을 덮는 여러 열 병합 칸은 문장 칸이다. 그 띠는 줄을 행으로 나누지 않는다(886쪽 '검사시험및교정')
        anchors = set() if not cfg.get('merged_anchor_labels') and any(v['c1'] - v['c0'] > 1 and any(a in range(v['c0'], v['c1']) for a in base_anchors)
                               for v in info) else base_anchors
        for gi, gcols in enumerate(groups):
            g = [v for v in info if v['c0'] in gcols]
            n_lines = len(cluster([y for v in g for y in v['lines']]))
            shared = [v for v in g if (v['c0'], band) in force_shared or (
                (v['c0'], band) not in force_split and sum(len(w['lines']) for w in g if w['c0'] == v['c0']) == 1
                and n_lines > 1 and v['c0'] not in anchors)]   # 공통 칸: 띠 안에서 그 열 전체가 한 줄
            import re as _rb
            block_res = {int(k): _rb.compile(x) for k, x in (cfg.get('block_cols') or {}).items()}
            blocks = [v for v in g if v['c0'] in block_res and v not in shared]
            centers = [v for v in g if v['c0'] in set(cfg.get('center_cols', [])) | set(cfg.get('order_cols', []))
                       | set(cfg.get('between_cols', [])) | set(cfg.get('down_cols', [])) and v not in shared]
            split = [v for v in g if v not in shared and v not in centers and v not in blocks]
            lines = cluster([y for v in split for y in v['lines']])
            import re as _re
            starts = {int(k): _re.compile(v) for k, v in (cfg.get('anchor_start') or {}).items() if int(k) in gcols}
            start_re = next(iter(starts.values()), None)
            # 줄 -> 논리 행
            line_row, rows_g, pending = {}, [], []
            cont = tuple(cfg.get('continue_prefixes', []))
            levels = [_re.compile(x) for x in cfg.get('heading_levels', [])]
            level_of = lambda t: next((k for k, rx in enumerate(levels) if rx.match(t)), None)
            brackets = []
            if cfg.get('bracket_groups'):
                for d in page.get_drawings():
                    for it in d['items']:
                        if it[0] == 'l' and abs(it[1].x - it[2].x) < 0.5 and abs(it[1].y - it[2].y) > 8 and ys[band] - 1 <= min(it[1].y, it[2].y) and max(it[1].y, it[2].y) <= ys[band_end] + 1:
                            for v in split:
                                if v['c0'] in anchors and xs[v['c0']] + 5 < it[1].x < xs[v['c1']] - 5:
                                    brackets.append((it[1].x, min(it[1].y, it[2].y) - 2, max(it[1].y, it[2].y) + 6))   # 괄호 선은 끝 항목 글자 중간에서 끝남
            def bracket_label(y):
                for bx, b0, b1 in brackets:
                    if b0 - LINE_TOL <= y <= b1 + LINE_TOL:
                        left = [x for v in split if v['c0'] in anchors for x in v['chars'] if abs(x[0] - y) <= LINE_TOL]
                        if left and all(x[1] < bx for x in left):
                            return (bx, b0, b1)
            for li, y in enumerate(lines):
                anchor_text = ''.join(x[2] for v in split if v['c0'] in anchors for x in sorted(v['chars'], key=lambda x: x[1])
                                      if abs(x[0] - y) <= LINE_TOL)
                has_anchor = any(v['c0'] in anchors and any(abs(y - ly) <= LINE_TOL for ly in v['lines']) for v in split)
                if start_re and has_anchor and not start_re.match(anchor_text):
                    has_anchor = False
                has_other = any(v['c0'] not in anchors and any(abs(y - ly) <= LINE_TOL for ly in v['lines']) for v in split)
                br = bracket_label(y) if brackets and not has_other else None
                same = [k for k, r in enumerate(rows_g) if r.get('bracket') == br] if br else []
                if same:
                    line_row[li] = same[0]          # 같은 괄호의 두 번째 이름 줄
                elif br:
                    rows_g.append({'y': y, 'heading': True, 'bracket': br}); line_row[li] = len(rows_g) - 1
                elif not rows_g and not has_anchor:
                    pending.append(li)
                elif rows_g and (not has_anchor or (cont and anchor_text.startswith(cont))
                               or anchor_text in cfg.get('continue_texts', [])      # 원문 대조로 확인한 이름 둘째 줄
                               or (cfg.get('merge_label_only') and has_anchor and not has_other
                                   and (rows_g[-1].get('label_only') or cfg['merge_label_only'] == 'always')
                                   and not rows_g[-1].get('heading'))):
                    line_row[li] = len(rows_g) - 1
                elif levels and has_anchor and level_of(anchor_text) is not None and not has_other:
                    rows_g.append({'y': y, 'heading': True, 'level': level_of(anchor_text)}); line_row[li] = len(rows_g) - 1
                elif band in headings and has_anchor and not has_other:
                    rows_g.append({'y': y, 'heading': True}); line_row[li] = len(rows_g) - 1
                else:
                    rows_g.append({'y': y, 'heading': False, 'label_only': has_anchor and not has_other,
                                   'level': level_of(anchor_text) if levels and has_anchor else None})
                    line_row[li] = len(rows_g) - 1
                    for pl in pending:
                        line_row[pl] = len(rows_g) - 1
                    pending = []
            if pending and not rows_g:
                rows_g.append({'y': lines[pending[0]], 'heading': False})
                for pl in pending:
                    line_row[pl] = 0
            for k, r in enumerate(rows_g):
                r['parts'] = []
                for v in split:
                    part = [x for x in v['chars'] if line_row[nearest(lines, x[0])] == k]
                    if part:
                        r['parts'].append((v, part))
            if centers and not rows_g:
                # 기준 열 줄이 없는 띠: 가운데 맞춤 열 줄만 있으면 한 행으로 둔다(줄을 버리지 않는다)
                ys0 = [y for v in centers for y in v['lines']]
                if ys0:
                    rows_g.append({'y': min(ys0), 'heading': False, 'parts': []})
            if centers and rows_g:
                mids = []
                for k, r in enumerate(rows_g):
                    ly = [lines[li] for li, rk in line_row.items() if rk == k] or [r['y']]
                    mids.append((min(ly) + max(ly)) / 2)
                for v in centers:
                    if v['c0'] in set(cfg.get('between_cols', [])):
                        firsts = [r['y'] for r in rows_g]
                        for cy in v['lines']:
                            part = [x for x in v['chars'] if abs(x[0] - cy) <= LINE_TOL]
                            k = min(range(len(firsts)), key=lambda i: abs(firsts[i] - cy))
                            if abs(firsts[k] - cy) <= LINE_TOL:
                                rows_g[k]['parts'].append((v, part))
                            else:
                                k = max(i for i in range(len(firsts)) if firsts[i] < cy)
                                rows_g[k].setdefault('span_parts', []).append((v, part, 2))
                        continue
                    if v['c0'] in set(cfg.get('down_cols', [])):
                        firsts = [r['y'] for r in rows_g]
                        for cy in v['lines']:
                            part = [x for x in v['chars'] if abs(x[0] - cy) <= LINE_TOL]
                            k = next((i for i in range(len(firsts)) if firsts[i] >= cy - LINE_TOL), len(firsts) - 1)
                            same = [p for p in rows_g[k]['parts'] if p[0] is v]
                            if same:
                                same[0][1].extend(part)
                            else:
                                rows_g[k]['parts'].append((v, list(part)))
                        continue
                    ordered = v['c0'] in set(cfg.get('order_cols', []))
                    empty_rows = cfg.get('order_empty_rows', {}).get(str(v['c0']), [])
                    ordered_rows = [i for i in range(len(rows_g)) if i not in empty_rows]
                    if ordered and len(v['lines']) != len(ordered_rows):
                        raise ValueError(f"순서 대응 열의 줄 수가 행 수와 다름: {v['c0']} {len(v['lines'])}/{len(rows_g)}")
                    for n, cy in enumerate(v['lines']):
                        k = ordered_rows[n] if ordered else min(range(len(mids)), key=lambda i: abs(mids[i] - cy))
                        part = [x for x in v['chars'] if abs(x[0] - cy) <= LINE_TOL]
                        same = [p for p in rows_g[k]['parts'] if p[0] is v]
                        if same:
                            same[0][1].extend(part)      # 같은 칸의 여러 줄은 한 칸 글로 합친다
                        else:
                            rows_g[k]['parts'].append((v, list(part)))
            for v in blocks:
                ls = sorted(v['lines'])
                text_at = lambda y: ''.join(x[2] for x in sorted(v['chars'], key=lambda x: x[1]) if abs(x[0] - y) <= LINE_TOL)
                starts = [y for y in ls if block_res[v['c0']].match(text_at(y))] or ls[:1]
                starts[0] = -1e9      # 띠의 첫 덩어리는 띠 맨 위부터(설명이 세로 가운데 놓인 경우, 889쪽 6.)
                for i, y0 in enumerate(starts):
                    y1 = starts[i + 1] if i + 1 < len(starts) else 1e9
                    part = [x for x in v['chars'] if y0 - LINE_TOL <= x[0] < y1 - LINE_TOL]
                    ks = [k for k, r in enumerate(rows_g) if not r['heading'] and y0 - LINE_TOL <= r['y'] < y1 - LINE_TOL]
                    if not ks:
                        rows_g.append({'y': y0, 'heading': False, 'parts': []})
                        rows_g.sort(key=lambda r: r['y'])
                        ks = [k for k, r in enumerate(rows_g) if r['y'] == y0]
                    rows_g[ks[0]].setdefault('span_parts', []).append((v, part, ks[-1] - ks[0] + 1))
            stack = []
            for r in rows_g:
                lv = r.get('level')
                if r['heading'] and not r.get('bracket'):
                    stack = ([h for h in stack if h.get('level') is not None and h['level'] < lv] if lv is not None else []) + [r]
                    continue
                if r['heading']:
                    continue
                if lv is not None:
                    stack = [h for h in stack if h.get('level') is not None and h['level'] < lv]
                br = [h for h in rows_g if h.get('bracket') and h['bracket'][1] - LINE_TOL <= r['y'] <= h['bracket'][2] + LINE_TOL]
                r['prefix'] = [br[0]] if br else list(stack)
                rows_here.append((r['y'], gi, r, shared))
            if not rows_g and shared:
                rows_here.append((min((v['lines'][0] for v in shared if v['lines']), default=ys[band]), gi,
                                  {'parts': [], 'prefix': None, 'heading': False}, shared))
        rows_here.sort(key=lambda x: (x[0], x[1]))
        if not rows_here:
            for v in info:
                out.append({'r0': grid_row, 'r1': grid_row + 1, 'c0': v['c0'], 'c1': v['c1'], 'orig': v['cell'],
                            'kind': 'empty_band'})
            grid_row += 1
            continue
        first_of_group, last_of_group = {}, {}
        for n, (y, gi, r, shared) in enumerate(rows_here):
            row = grid_row + n
            first_of_group.setdefault(gi, row); last_of_group[gi] = row
            for v, part, span in r.get('span_parts', []):
                used.update(part)
                out.append({'r0': row, 'r1': row + span, 'c0': v['c0'], 'c1': v['c1'], 'text': text_of(part),
                            'box': bbox_of(part, v['box']), 'orig': v['cell'], 'kind': 'between_rows'})
            for v, part in r['parts']:
                pres = r['prefix'] if v['c0'] in anchors else []
                text = text_of(part)
                hp = []
                for pre in pres:
                    got = [p for vv, p in pre['parts'] if vv['c0'] == v['c0']]
                    if got and pre.get('bracket'):
                        got = [[x for x in got[0] if x[1] < pre['bracket'][0]]]
                    hp += got
                if hp:
                    text = '\n'.join(text_of(h) for h in hp) + '\n' + text
                used.update(part)
                for h in hp:
                    heading_uses.update(h)
                out.append({'r0': row, 'r1': row + 1, 'c0': v['c0'], 'c1': v['c1'], 'text': text,
                            'box': bbox_of(part, v['box']), 'orig': v['cell'], 'kind': 'line_row',
                            'heading': [{'text': text_of(h), 'bbox_pt': [round(t, 2) for t in bbox_of(h, v['box'])]} for h in hp]
                            or None})
        for gi in first_of_group:
            shared = next(x[3] for x in rows_here if x[1] == gi)
            by_col = collections.OrderedDict()      # 묶은 띠에서 같은 열의 공통 칸은 한 칸으로 합친다
            for v in shared:
                by_col.setdefault((v['c0'], v['c1']), []).append(v)
            for (c0, c1), vs in by_col.items():
                ch = [x for v in vs for x in v['chars']]
                if ch:
                    used.update(ch)
                    out.append({'r0': first_of_group[gi], 'r1': last_of_group[gi] + 1, 'c0': c0, 'c1': c1,
                                'text': text_of(ch), 'box': bbox_of(ch, vs[0]['box']), 'orig': vs[0]['cell'],
                                'kind': 'shared', 'orig_ids': [v['cell'].get('id') for v in vs]})
        if fill_down:
            band_end = grid_row + len(rows_here)
            mine = [o for o in out if o.get('kind') == 'line_row' and o['c0'] in fill_down and grid_row <= o['r0'] < band_end]
            for col in fill_down:
                cs = sorted((o for o in mine if o['c0'] == col), key=lambda o: o['r0'])
                for i, o in enumerate(cs):
                    o['r1'] = cs[i + 1]['r0'] if i + 1 < len(cs) else band_end
                    o['kind'] = 'fill_down'
        grid_row += len(rows_here)
    band_first[n_bands] = grid_row
    for band, band_end in ranges:            # 묶은 띠 안의 원래 행 번호도 시작 위치를 갖게 한다
        for k in range(band + 1, band_end):
            band_first.setdefault(k, band_first[band_end] if band_end in band_first else grid_row)
    src = collections.Counter(source_chars)
    missing = src - used - collections.Counter(heading_uses)
    extra = used - src
    if missing or extra:
        raise ValueError(f"다시 짠 표의 원문 글자 누락·중복: {node['id']} 누락 {''.join(c[2] for c in missing.elements())[:60]!r} "
                         f"중복 {''.join(c[2] for c in extra.elements())[:60]!r}")
    if cfg.get('colon_groups'):
        # 905쪽: '◦준비작업 : 궤도공' 다음 ': 목도' 행은 같은 단계. 단계 이름(콜론 앞)을 원문 위치와 함께 붙인다
        import re as _rc
        prefix = None
        for o in sorted((o for o in out if o.get('kind') == 'line_row' and o['c0'] in base_anchors), key=lambda o: o['r0']):
            m = _rc.match(r'^(.*?◦[^:]*?)\s*:', o['text'].replace(chr(10), ' '))
            if m:
                prefix = m.group(1).split('◦')[-1].strip()
            elif o['text'].split(chr(10))[-1].lstrip().startswith(':') and prefix:
                head = o['text'].split(chr(10))
                o['text'] = chr(10).join(head[:-1] + ['◦' + prefix + ' ' + head[-1].strip()])
                o['heading'] = (o.get('heading') or []) + [{'text': '◦' + prefix, 'source': 'same stage line above (colon_groups)'}]
    import odl_tables
    for c in multi:
        b0 = c['row number'] - 1
        c0, c1 = c['column number'] - 1, c['column number'] - 1 + c.get('column span', 1)
        cell = {'r0': band_first[b0], 'r1': band_first[b0 + c['row span']], 'c0': c0, 'c1': c1, 'orig': c,
                'kind': 'multi_band'}
        if not odl_tables.find_tables(c):
            # 여러 띠에 걸친 병합 칸도 원문 글자로 다시 읽어 한 칸 글로 둔다(세로 쓴 이름 '폭/원' 등)
            box = [xs[c0], ys[b0], xs[c1], ys[b0 + c['row span']]]
            ch = page_chars(page, box)
            if ch:
                source_chars.extend(ch); used.update(ch)
                cell.update(kind='multi_band_text', text=text_of(ch), box=bbox_of(ch, box))
        out.append(cell)
    tid = node['id']
    new_rows = [{'id': f'{tid}:lr{r}', 'cells': []} for r in range(grid_row)]
    for oc in sorted(out, key=lambda c: (c['r0'], c['c0'])):
        orig = oc['orig']
        if oc['kind'] in ('header', 'multi_band', 'empty_band', 'nested_band'):
            cell = dict(orig)
            cell.update({'row number': oc['r0'] + 1, 'row span': oc['r1'] - oc['r0']})
            cell['_regrid'] = {'kind': oc['kind'], 'orig_id': orig.get('id')}
        else:
            bx = oc['box']
            nb = [bx[0], H - bx[3], bx[2], H - bx[1]]
            cid = f"{orig.get('id')}:lr{oc['r0']}c{oc['c0']}"
            cell = {'id': cid, 'type': 'table cell', 'row number': oc['r0'] + 1, 'column number': oc['c0'] + 1,
                    'row span': oc['r1'] - oc['r0'], 'column span': oc['c1'] - oc['c0'], 'bounding box': nb,
                    'kids': [{'id': f'{cid}:text', 'type': 'paragraph', 'content': oc['text'],
                              'page number': node.get('page number'), 'bounding box': nb}],
                    '_regrid': {'kind': oc['kind'], 'orig_id': orig.get('id'),
                                'orig_ids': oc.get('orig_ids', [orig.get('id')]),
                                **({'heading': oc['heading']} if oc.get('heading') else {})}}
        new_rows[oc['r0']]['cells'].append(cell)
    # Reviewed spans retain one source label across its actual child rows.
    for group in cfg.get('manual_spans', []):
        matches = [c for row in new_rows for c in row['cells']
                   if c['column number'] - 1 == group['col']
                   and c['row number'] - 1 in group['from_rows']]
        if len(matches) != len(group['from_rows']):
            raise ValueError('원문 대조 이름 묶음의 칸 수가 다릅니다.')
        matches.sort(key=lambda c:c['row number'])
        text = '\n'.join(odl_tables.cell_text(c) for c in matches)
        source_labels=[{'text':odl_tables.cell_text(c),'bbox_native':c['bounding box'],
                        'orig_id':c['_regrid']['orig_id']} for c in matches]
        merged_box=[min(c['bounding box'][0] for c in matches),min(c['bounding box'][1] for c in matches),
                    max(c['bounding box'][2] for c in matches),max(c['bounding box'][3] for c in matches)]
        first = matches[0]
        first['row number'] = group['rows'][0] + 1
        first['row span'] = group['rows'][1] - group['rows'][0]
        first['kids'][0]['content'] = text
        first['bounding box']=merged_box
        first['kids'][0]['bounding box']=merged_box
        first['_regrid'].update(kind='reviewed_label_span',
                               orig_ids=[c['_regrid']['orig_id'] for c in matches],
                               source_labels=source_labels,
                               reviewed_rows=group['rows'])
        for cell in matches[1:]:
            new_rows[cell['row number']-1]['cells'].remove(cell)
    new = dict(node)
    new.update({'rows': new_rows, 'number of rows': grid_row,
                '_regrid': {'config': cfg, 'header_rows': header_rows, 'orig_rows': n_bands,
                            'char_check': {'source_chars': len(source_chars), 'heading_repeats': sum(heading_uses.values())}}})
    return new


def summary(node):
    """고정·비교용 칸 목록: [r0, r1, c0, c1, 글]."""
    import odl_tables
    out = []
    for r in node['rows']:
        for c in r['cells']:
            out.append([c['row number'] - 1, c['row number'] - 1 + c.get('row span', 1), c['column number'] - 1,
                        c['column number'] - 1 + c.get('column span', 1), odl_tables.cell_text(c)])
    return sorted(out)
