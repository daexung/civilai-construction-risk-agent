"""교정 자료 거부 검사. 실제 적용 경로(build_index.build)에 일부러 틀린 교정 자료를 넣어 거부되는지 본다."""
import copy
import json
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import build_index as bi  # noqa: E402
import corrections  # noqa: E402

ORIG = corrections.CORRECTION_FILES[0]


def mutate(fn):
    d = json.loads(ORIG.read_text(encoding='utf-8'))
    fn(d)
    return d


CASES = [
    ('PDF 해시가 다름', lambda d: d.update(pdf_sha256='0' * 64)),
    ('입력 해시가 다름', lambda d: d['inputs_sha256'].update(store='0' * 64)),
    ('PDF 제목 글자가 다름', lambda d: d['sections'][0]['heading_pdf'].update(text='1-2-2 기계포설(본선)')),
    ('PDF 위치에 제목이 없음', lambda d: d['sections'][1]['heading_pdf'].update(bbox_pt=[78.0, 300.0, 193.0, 312.0])),
    ('기존 소속이 기대와 다름', lambda d: d['sections'][2].update(expected_previous_section='1-4-3')),
    ('대상 목록이 다음 제목 전 노드와 다름', lambda d: d['sections'][0]['members'].pop()),
    ('목차 쪽 번호가 다름', lambda d: d['sections'][0].update(printed_page=999)),
]


def main():
    out = []
    with tempfile.TemporaryDirectory() as td:
        for name, fn in CASES:
            p = Path(td) / 'c.json'
            p.write_text(json.dumps(mutate(fn), ensure_ascii=False), encoding='utf-8')
            corrections.CORRECTION_FILES[:] = [p]
            try:
                bi.build()
                out.append({'name': name, 'rejected': False})
            except corrections.CorrectionRejected as e:
                out.append({'name': name, 'rejected': True, 'reason': str(e)[:200]})
    corrections.CORRECTION_FILES[:] = [ORIG]
    res = {'note': '교정 자료를 일부러 틀리게 바꾼 시험(가상 입력). 모두 거부돼야 한다.', 'cases': out,
           'failed': sum(not x['rejected'] for x in out)}
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return res


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(1 if main()['failed'] else 0)
