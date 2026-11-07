"""주니어 시나리오 질문(Q1)의 재료 조각을 유형별로 고른다. 외부 호출 없음.

기존 평가 질문 세트(eval/*.json)에 나온 절은 빼서 새 질문이 독립 평가가 되게 한다.
같은 입력·같은 SEED면 같은 결과가 나온다.

사용(저장소 루트): .venv/Scripts/python.exe -B experiments/retrieval-v1/eval/junior/sample_chunks.py <출력 폴더>
"""
from __future__ import annotations

import glob
import json
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

WORK = Path(__file__).resolve().parents[2]
CHUNKS = WORK / 'out/chunks/cs-37f81b5cfb1b-46f4f035c0fa/chunks.jsonl'
SEED = 1107
SEC = re.compile(r'pumsem-2026-errata1:[a-z]+:[\d-]+')

# 유형: (설명, 개수, 조각 고르는 조건)
TYPES = {
    'T1_value': ('표의 기준 수치를 묻는다 (몇 인, 몇 %, 시공량)', 8),
    'T2_surcharge': ('할증·보정 비율과 적용 조건을 묻는다', 6),
    'T3_section': ('절 번호를 대며 내용을 묻는다 ("6-1-3 내용 알려줘")', 4),
    'T4_definition': ('용어 뜻이나 적용 범위를 묻는다', 4),
    'T5_included': ('품에 무엇이 포함되는지·별도 계상인지 묻는다', 6),
    'T6_method': ('할증·보정을 어떻게 적용하는지 방법을 묻는다', 3),
    'T7_compare': ('비슷한 두 공종의 기준을 비교해 묻는다', 4),
    'T8_followup': ('첫 질문 뒤 조건만 바꿔 이어 묻는다 (2턴)', 5),
    'T9_not_found': ('품셈에 없는 자료를 묻는다 (노임단가, 자재 가격 등) → 없다고 답해야 함', 4),
    'T10_out_of_scope': ('품셈과 무관한 건설 질문 (법규, 안전교육 등) → 범위 밖', 3),
    'T11_quick_calc': ('물량을 대며 사람 수를 묻는다 → 1단위당 기준 인용 + 견적 탭 안내', 3),
}


def used_sections() -> set[str]:
    found = set()
    for path in glob.glob(str(WORK / 'eval/*.json')):
        found |= set(SEC.findall(Path(path).read_text(encoding='utf-8')))
    return found


def clean(rows: list[dict], used: set[str]) -> list[dict]:
    return [r for r in rows if r['status'] == 'ok' and not r['issues'] and r['section_id'] not in used
            and len(r['text']) < 2500]


def view(r: dict) -> dict:
    return {k: r[k] for k in ('chunk_id', 'kind', 'section_id', 'division', 'title', 'text')}


def sections_apart(rows: list[dict], n: int, rng: random.Random, taken: set[str]) -> list[dict]:
    """절이 겹치지 않게 n개. taken에 고른 절을 더한다."""
    rng.shuffle(rows)
    out = []
    for r in rows:
        if r['section_id'] not in taken:
            taken.add(r['section_id'])
            out.append(r)
        if len(out) == n:
            break
    return out


def pick(rows: list[dict], seed: int = SEED) -> list[dict]:
    rng = random.Random(seed)
    taken: set[str] = set()
    tables = [r for r in rows if r['kind'] == 'table' and re.search(r'\d\.\d', r['body_text'])]
    rules = [r for r in rows if r['kind'] == 'rule']
    works = [r for r in rows if r['kind'] == 'work']
    multi_col = [r for r in tables if r['context_text'].count('|') >= 4]
    per_unit = [r for r in tables if re.search(r'기준: \((㎡|m|㎥|개소|개|ton|톤)당\)', r['context_text'])]

    tasks = []

    def add(kind: str, groups: list[list[dict]]):
        for i, group in enumerate(groups):
            tasks.append({'task_id': f'{kind}_{i + 1}', 'type': kind, 'type_desc': TYPES[kind][0],
                          'chunks': [view(r) for r in group]})

    add('T1_value', [[r] for r in sections_apart(tables, TYPES['T1_value'][1], rng, taken)])
    add('T2_surcharge', [[r] for r in sections_apart(
        [r for r in rules if '할증' in r['body_text'] and '%' in r['body_text']], 6, rng, taken)])
    add('T3_section', [[r] for r in sections_apart(works, 4, rng, taken)])
    add('T4_definition', [[r] for r in sections_apart(
        [r for r in rules if re.search(r'말한다|라 함은|이라 한다|적용범위|적용 범위', r['body_text'])], 4, rng, taken)])
    add('T5_included', [[r] for r in sections_apart(
        [r for r in rules if re.search(r'포함되어 있|포함한다|별도 계상|별도계상', r['body_text'])], 6, rng, taken)])
    add('T6_method', [[r] for r in sections_apart(
        [r for r in rules if re.search(r'할증.*(중복|가산|곱|합산)', r['body_text'])], 3, rng, taken)])

    # 비교: 같은 상위 번호(예: 2-1)의 서로 다른 절 표 두 개
    by_parent = defaultdict(lambda: defaultdict(list))
    for r in tables:
        if r['section_id'] in taken:
            continue
        no = r['section_id'].rsplit(':', 1)[1]
        by_parent[r['section_id'].rsplit(':', 1)[0] + ':' + no.rsplit('-', 1)[0]][r['section_id']].append(r)
    parents = sorted(p for p, secs in by_parent.items() if len(secs) >= 2)
    rng.shuffle(parents)
    pairs = []
    for p in parents[:4]:
        a, b = sorted(by_parent[p])[:2]
        pairs.append([by_parent[p][a][0], by_parent[p][b][0]])
        taken |= {a, b}
    add('T7_compare', pairs)

    add('T8_followup', [[r] for r in sections_apart(multi_col, 5, rng, taken)])
    add('T9_not_found', [[] for _ in range(4)])
    add('T10_out_of_scope', [[] for _ in range(3)])
    add('T11_quick_calc', [[r] for r in sections_apart(per_unit, 3, rng, taken)])
    return tasks


def _selftest(tasks: list[dict], used: set[str]) -> None:
    assert len(tasks) == sum(n for _, n in TYPES.values()), len(tasks)
    secs = [c['section_id'] for t in tasks for c in t['chunks']]
    assert len(secs) == len(set(secs)), '절이 겹침'
    assert not set(secs) & used, '기존 평가 절이 섞임'


def main() -> int:
    sys.stdout.reconfigure(encoding='utf-8')
    out = Path(sys.argv[1])
    rows = [json.loads(line) for line in CHUNKS.read_text(encoding='utf-8').splitlines()]
    used = used_sections()
    tasks = pick(clean(rows, used))
    _selftest(tasks, used)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'input.json').write_text(json.dumps(tasks, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'과제 {len(tasks)}, 조각 {sum(len(t["chunks"]) for t in tasks)}, 제외한 기존 절 {len(used)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
