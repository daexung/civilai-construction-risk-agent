"""검사 실행 기록. 검사 결과는 자료 폴더가 아니라 실행마다 따로 저장하고, 과거 실행 기록을 덮어쓰지 않는다.

  out/verification_runs/<대상 ID>/<run_id>/   검사 결과 파일 + run_manifest.json(마지막에 기록)
  out/verification_runs/<대상 ID>/index.json  실행 목록(상태·run_manifest 해시·검사한 자료 목록 해시)

순서: 실행 폴더 생성(status=running) → 결과 파일 저장 → 자료 파일 해시 확인 → run_manifest(파일 해시, 상태) → index 갱신.
도중에 실패하면 run_manifest가 running 또는 error로 남고 index의 마지막 통과 실행은 바뀌지 않는다.
run_manifest는 자기 자신의 해시를 담지 않는다. index는 각 run_manifest의 해시를 담는다.
"""
import hashlib
import json
import time
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / 'out'
RUNS = OUT / 'verification_runs'


def sha_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def write_json(p, obj):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=str), encoding='utf-8')


def data_files(data_dir):
    """자료 폴더의 모든 파일(하위 폴더 제외) 해시. manifest.json도 포함해 '검사한 자료'를 그대로 고정한다."""
    return {p.name: sha_file(p) for p in sorted(Path(data_dir).iterdir()) if p.is_file()}


def rel(p):
    p = Path(p).resolve()
    return str(p.relative_to(OUT.parent)).replace('\\', '/') if p.is_relative_to(OUT.parent) else str(p)


def start(target_id, tool, data_dir, note=None, runs_root=None):
    root = Path(runs_root or RUNS) / target_id
    run_id = time.strftime('%Y%m%dT%H%M%S') + f'-{tool}'
    d = root / run_id
    if d.exists():
        raise FileExistsError(f'같은 실행 ID가 이미 있음: {d}')
    d.mkdir(parents=True)
    run = {'run_id': run_id, 'tool': tool, 'target_id': target_id, 'status': 'running', 'started': time.strftime('%Y-%m-%d %H:%M:%S'),
           'data_dir': rel(data_dir) if data_dir else None, 'note': note}
    write_json(d / 'run_manifest.json', run)
    return {'dir': d, 'root': root, 'meta': run, 'data_dir': data_dir}


def finish(run, files, passed, summary):
    """결과 파일을 먼저 저장하고, 그 뒤 해시 목록(run_manifest)과 index를 쓴다."""
    d = run['dir']
    for name, obj in files.items():
        write_json(d / name, obj)
    meta = dict(run['meta'], status='passed' if passed else 'failed', finished=time.strftime('%Y-%m-%d %H:%M:%S'),
                summary=summary, files_sha256={n: sha_file(d / n) for n in sorted(files)},
                verified_data_files_sha256=data_files(run['data_dir']) if run['data_dir'] else None)
    write_json(d / 'run_manifest.json', meta)
    update_index(run['root'])
    return meta


def fail(run, error):
    meta = dict(run['meta'], status='error', finished=time.strftime('%Y-%m-%d %H:%M:%S'), error=str(error)[:2000])
    write_json(run['dir'] / 'run_manifest.json', meta)
    update_index(run['root'])


def update_index(root):
    runs = []
    for d in sorted(p for p in Path(root).iterdir() if p.is_dir()):
        m = d / 'run_manifest.json'
        meta = json.loads(m.read_text(encoding='utf-8')) if m.exists() else {'status': 'missing_manifest'}
        runs.append({'run_id': d.name, 'tool': meta.get('tool'), 'status': meta.get('status'),
                     'run_manifest_sha256': sha_file(m) if m.exists() else None,
                     'record_kind': meta.get('record_kind', 'current_run')})
    passed = [r for r in runs if r['status'] == 'passed' and r['record_kind'] == 'current_run']
    write_json(Path(root) / 'index.json', {'target_id': Path(root).name, 'runs': runs,
                                           'latest_passed_run': passed[-1]['run_id'] if passed else None,
                                           'latest_passed_by_tool': {r['tool']: r['run_id'] for r in passed}})


def check_run(run_dir):
    """실행 폴더의 파일이 run_manifest의 해시와 같은지 독립 확인."""
    meta = json.loads((Path(run_dir) / 'run_manifest.json').read_text(encoding='utf-8'))
    bad = [n for n, h in (meta.get('files_sha256') or {}).items() if sha_file(Path(run_dir) / n) != h]
    extra = [p.name for p in Path(run_dir).iterdir() if p.name != 'run_manifest.json' and p.name not in (meta.get('files_sha256') or {})]
    return {'run_id': meta['run_id'], 'status': meta['status'], 'mismatch': bad, 'unlisted': extra}
