"""가상 입력 검사(실제 원문 사례가 아님). 실제 연결 규칙(Resolver)과 탐색 함수(walk)를 그대로 쓴다."""
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import build_index as bi  # noqa: E402
from query import walk  # noqa: E402


def sec(div, number, title, start, end):
    level = 'section' if number.count('-') == 2 else 'group'
    return {'section_id': f'v:{bi.DIV_CODE[div]}:{number}', 'division': div, 'level': level, 'number': number,
            'title': title, 'start_order': start, 'end_order': end, 'first_page': 1}


SECTIONS = [sec('공통부문', '6-1-3', '표면 마무리', 10, 20), sec('건축부문', '6-1-3', '표면 마무리', 30, 40),
            sec('건축부문', '9-1-4', '표면 마무리', 50, 60), sec('토목부문', '9-1-4', '3급 기준점 측량', 70, 80),
            sec('토목부문', '9-1-5', '4급 기준점 측량', 80, 90)]
NODES = [{'node_id': 'src', 'kind': 'note', 'region': 'body', 'doc_order': 5, 'text': '원문', 'division': '공통부문'}]


def main():
    R = bi.Resolver(SECTIONS, NODES, {'src': None})
    checks = []

    def case(name, got, want):
        checks.append({'name': name, 'virtual': True, 'got': got, 'want': want, 'passed': got == want})

    r = R.resolve('전기부문', '1-1-1 일반사항', 'src', '공통부문')
    case('외부 문서(이 문서에 없는 부문)', r['status'], 'external')
    r = R.resolve('토목부문', '99-9-9 없는 절', 'src', '공통부문')
    case('본문에 없는 절', r['status'], 'missing')
    r = R.resolve('공통부문', '6-1-3 표면 마무리', 'src', '공통부문')
    case('부문 명시: 같은 번호의 다른 부문을 고르지 않음', [s['section_id'] for s, _ in r['targets']], ['v:common:6-1-3'])
    r = R.resolve(None, '6-1-3 표면 마무리', 'src', '공통부문')
    case('부문 생략 + 같은 번호·제목이 두 부문: 모호함(같은 부문으로 확정하지 않음)', (r['status'], r['targets']), ('ambiguous', []))
    r = R.resolve(None, '9-1-4 4급 기준점 측량', 'src', '토목부문')
    case('번호와 제목이 다른 절을 가리킴: 모호함', r['status'], 'ambiguous')
    r = R.resolve(None, '9-1-5 4급 기준점 측량', 'src', '토목부문')
    case('부문 생략, 번호·제목이 맞는 절 하나', [s['section_id'] for s, _ in r['targets']], ['v:civil:9-1-5'])

    graph = {'A': [{'target_nodes': ['B']}], 'B': [{'target_nodes': ['A']}], 'C': [{'target_nodes': ['C']}]}
    w = walk(['A'], lambda n: graph.get(n, []), max_depth=5)
    case('순환 참조 A→B→A: 같은 노드를 두 번 읽지 않고 끝남', (w['visited'], len(w['steps'])), (['A', 'B'], 2))
    w = walk(['C'], lambda n: graph.get(n, []), max_depth=3)
    case('자기 참조 C→C: 한 번만 읽음', (w['visited'], len(w['steps'])), (['C'], 1))
    chain = {str(i): [{'target_nodes': [str(i + 1)]}] for i in range(5)}
    w = walk(['0'], lambda n: chain.get(n, []), max_depth=2)
    case('깊이 한도에 걸린 경로를 미해결로 남김', w['unresolved_references'], ['2'])

    # 대상 절 목록이 바뀌면(번호가 다른 절로 옮겨짐) 연결 결과가 달라지고, 결과는 릴리스 ID로 구분된다
    moved = [dict(s) for s in SECTIONS]
    moved[0]['section_id'] = 'v:common:6-1-3-new'
    r1 = R.resolve('공통부문', '6-1-3 표면 마무리', 'src', '공통부문')
    r2 = bi.Resolver(moved, NODES, {'src': None}).resolve('공통부문', '6-1-3 표면 마무리', 'src', '공통부문')
    case('대상 변경 후 이전 연결과 섞이지 않음(대상 식별자가 바뀜)',
         [s['section_id'] for s, _ in r1['targets']] != [s['section_id'] for s, _ in r2['targets']], True)
    out = {'note': '가상 입력. 실제 원문 사례 검사와 구분한다.', 'checks': checks,
           'passed': sum(c['passed'] for c in checks), 'failed': sum(not c['passed'] for c in checks)}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return out


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(1 if main()['failed'] else 0)
