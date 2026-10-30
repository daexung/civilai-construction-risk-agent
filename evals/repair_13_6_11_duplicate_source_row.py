import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
spec_path = root / 'data/drafts/specs/기계설비/13-6-11.json'
data = json.loads(spec_path.read_text(encoding='utf-8'))
table = next(t for t in data['draft']['tables'] if t['id'] == 'p870-t1')
assert table['values'].get('교정(1차)/플랜트제관공', {}).get('수량') == '0.6'
assert table['values'].get('교정(2차)/플랜트제관공', {}).get('수량') == '0.75'
for citation in data['citations']:
    if citation.get('table_id') == 'p870-t1' and citation.get('row') == '교정/플랜트제관공':
        citation['row'] = ('교정(1차)/플랜트제관공' if citation['value'] == '0.6'
                           else '교정(2차)/플랜트제관공')
spec_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

# The calculator identifies source tasks by their task/trade alias, then maps
# that alias to the actual trade for grouped output. Preserve both repeated
# correction rows as distinct rate lookups.
draft = data['draft']
rate = draft['quantity_model']['params']['unit_rate_table']
old = '교정/플랜트제관공'
first = '교정(1차)/플랜트제관공'
second = '교정(2차)/플랜트제관공'
rate['trades'] = [first if item == old else item for item in rate['trades']]
rate['trades'].insert(rate['trades'].index(first) + 1, second)
for map_name in ('row_by_trade', 'trade_name_by_trade', 'resource_units_by_row'):
    mapping = rate[map_name]
    prior = mapping.pop(old)
    mapping[first] = ({first: prior[old]} if map_name == 'resource_units_by_row' else first) \
        if map_name == 'row_by_trade' else mapping.get(first, prior)
    if map_name == 'trade_name_by_trade':
        mapping[first] = '플랜트제관공'
        mapping[second] = '플랜트제관공'
    elif map_name == 'resource_units_by_row':
        mapping[first] = {first: '인'}
        mapping[second] = {second: '인'}
    else:
        mapping[first] = first
        mapping[second] = second
spec_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

chunk_path = root / 'data/processed/chunks.all.jsonl'
lines = chunk_path.read_text(encoding='utf-8').splitlines()
found = False
for i, line in enumerate(lines):
    chunk = json.loads(line)
    if chunk.get('chunk_id') != 'p870-t1':
        continue
    text = chunk['text']
    old1 = '교정/플랜트제관공 | 직종 플랜트제관공 | 단위 인/ton | 수량 0.6'
    old2 = '교정/플랜트제관공 | 직종 플랜트제관공 | 단위 인/ton | 수량 0.75'
    assert old1 in text and old2 in text
    text = text.replace(old1, '교정(1차)/플랜트제관공 | 직종 플랜트제관공 | 단위 인/ton | 수량 0.6')
    text = text.replace(old2, '교정(2차)/플랜트제관공 | 직종 플랜트제관공 | 단위 인/ton | 수량 0.75')
    chunk['text'] = text
    lines[i] = json.dumps(chunk, ensure_ascii=False)
    found = True
assert found
chunk_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
print('restored the two repeated source rows as distinct source-position aliases')
