"""실행 기록 저장 경로의 실패 처리 시험(가상 실행, 임시 폴더). 실제 검사 기록은 건드리지 않는다."""
import json
import sys
import tempfile
import time
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import run_records as rr  # noqa: E402


def main():
    out = []

    def check(name, ok, detail=None):
        out.append({'name': name, 'passed': bool(ok), 'detail': detail})

    with tempfile.TemporaryDirectory() as td:
        data = Path(td) / 'data'
        data.mkdir()
        (data / 'a.json').write_text('{}', encoding='utf-8')
        idx = lambda: json.loads((Path(td) / 'T' / 'index.json').read_text(encoding='utf-8'))
        r1 = rr.start('T', 'tool', data, runs_root=td)
        rr.finish(r1, {'verification.json': {'failed': 0}}, True, {})
        good = r1['meta']['run_id']
        time.sleep(1.1)
        r2 = rr.start('T', 'tool', data, runs_root=td)
        rr.finish(r2, {'verification.json': {'failed': 1}}, False, {})
        check('검사 실패 실행은 failed로 남고 마지막 통과 실행이 바뀌지 않음',
              idx()['latest_passed_run'] == good and rr.check_run(r2['dir'])['status'] == 'failed')
        time.sleep(1.1)
        r3 = rr.start('T', 'tool', data, runs_root=td)
        try:
            rr.finish(r3, {'a.json': {'x': 1}, 'a.json/b.json': {'x': 2}}, True, {})   # 저장 실패(파일 아래에 파일)
            saved = True
        except OSError as e:
            rr.fail(r3, e)
            saved = False
        check('결과 저장 실패는 error로 남고 통과로 표시하지 않음', not saved and rr.check_run(r3['dir'])['status'] == 'error'
              and idx()['latest_passed_run'] == good)
        time.sleep(1.1)
        r4 = rr.start('T', 'tool', data, runs_root=td)               # 끝내지 못하고 멈춘 실행
        rr.update_index(Path(td) / 'T')
        check('도중에 멈춘 실행은 running으로 남고 통과로 표시하지 않음',
              [x['status'] for x in idx()['runs']][-1] == 'running' and idx()['latest_passed_run'] == good)
        check('이전 실행 기록이 모두 남음', len(idx()['runs']) == 4, [x['run_id'] for x in idx()['runs']])
        (r1['dir'] / 'verification.json').write_text('{"changed": true}', encoding='utf-8')
        check('실행 뒤 결과 파일이 바뀌면 해시 확인에서 드러남', rr.check_run(r1['dir'])['mismatch'] == ['verification.json'])
    res = {'note': '가상 실행(임시 폴더). 실제 기록과 무관.', 'checks': out, 'failed': sum(not x['passed'] for x in out)}
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return res


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(1 if main()['failed'] else 0)
