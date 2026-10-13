"""자료 폴더의 해시 목록과 검사 실행 기록을 파일에서 독립적으로 다시 계산해 확인한다. 아무것도 쓰지 않는다.

  python -B experiments/retrieval-v1/checks/check_records.py
"""
import hashlib
import json
import sys
from pathlib import Path

WORK = Path(__file__).resolve().parents[1]
OUT = WORK / 'out'
# 실행 기록이 있는 대상(원문 릴리스·청킹 묶음) 전부
DATA = {t: OUT / 'chunks' / t if t.startswith('cs-') else OUT / t
        for t in sorted(p.name for p in (OUT / 'verification_runs').iterdir() if p.is_dir())}


def h(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    problems, report = [], {}
    for target, d in DATA.items():
        man = json.loads((d / 'manifest.json').read_text(encoding='utf-8'))
        listed = man['files_sha256']
        files = {p.name for p in d.iterdir() if p.is_file() and p.name != 'manifest.json'}
        bad = [n for n, v in listed.items() if not (d / n).exists() or h(d / n) != v]
        unlisted = sorted(files - set(listed))
        stray = sorted(n for n in files if n in ('verification.json', 'example_queries.json'))
        problems += [f'{target}: 해시 불일치 {bad}'] * bool(bad) + [f'{target}: 목록에 없는 파일 {unlisted}'] * bool(unlisted) \
            + [f'{target}: 자료 폴더에 검사 결과 파일 {stray}'] * bool(stray)
        rd = OUT / 'verification_runs' / target
        idx = json.loads((rd / 'index.json').read_text(encoding='utf-8'))
        runs = []
        for r in idx['runs']:
            md = rd / r['run_id']
            meta = json.loads((md / 'run_manifest.json').read_text(encoding='utf-8'))
            fb = [n for n, v in meta['files_sha256'].items() if h(md / n) != v]
            un = [p.name for p in md.iterdir() if p.name != 'run_manifest.json' and p.name not in meta['files_sha256']]
            idx_ok = h(md / 'run_manifest.json') == r['run_manifest_sha256']
            # 현재 실행이 검사한 자료 파일이 지금 자료와 같은지(현재 자료를 가리키는지)
            now = {p.name: h(p) for p in sorted(d.iterdir()) if p.is_file()}
            pinned = meta.get('verified_data_files_sha256')
            pin = None if not pinned else ('지금 자료와 같음' if pinned == now else
                                           '지금 자료와 다름(자료 폴더에서 검사 결과를 옮기기 전 상태)' if meta.get('record_kind') == 'preserved_past_run'
                                           else '지금 자료와 다름')
            if fb or un or not idx_ok or (pin == '지금 자료와 다름'):
                problems.append(f"{target}/{r['run_id']}: 파일 {fb} 목록밖 {un} index {idx_ok} 자료 {pin}")
            runs.append({'run_id': r['run_id'], 'kind': meta.get('record_kind', 'current_run'), 'status': meta['status'],
                         'files_ok': not fb and not un, 'index_hash_ok': idx_ok, 'data_pin': pin})
        report[target] = {'data_files_listed': len(listed), 'data_files_ok': not bad and not unlisted and not stray,
                          'latest_passed_by_tool': idx.get('latest_passed_by_tool'), 'runs': runs}
    out = {'problems': problems, 'targets': report}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return out


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(1 if main()['problems'] else 0)
