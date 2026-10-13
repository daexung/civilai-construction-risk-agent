"""5b단계 작업 전·후 보존 기록(5단계 기록 포함): 서비스 코드(backend, frontend/src), 검색 코드, 원문·청크·임베딩, 이전 단계 결과, DB 지문."""
import hashlib, json, subprocess, sys
from pathlib import Path
sys.dont_write_bytecode = True
WORK = Path(__file__).resolve().parents[2]
ROOT = WORK.parents[1]
sys.path.insert(0, str(WORK / 'src')); sys.path.insert(0, str(WORK / 'checks'))
import db  # noqa
import fingerprint as fp  # noqa
CS, REL = 'cs-37f81b5cfb1b-46f4f035c0fa', 'rk-complete-82c206c61e21-37f81b5cfb1b'

def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()

def tree(base, pats, skip=('node_modules', '__pycache__', 'build')):
    out = {}
    for pat in pats:
        for p in sorted(base.glob(pat)):
            if p.is_file() and not any(s in p.parts for s in skip):
                out[p.relative_to(ROOT).as_posix()] = sha(p)
    return out

tag = sys.argv[1] if len(sys.argv) > 1 else 'before'
git = subprocess.run(['git', 'status', '--porcelain'], cwd=ROOT, capture_output=True, text=True, encoding='utf-8').stdout.splitlines()
snap = {'tag': tag, 'git_status_porcelain': git,
        'backend': tree(ROOT / 'backend', ['**/*.py', '**/*.json', '**/*.md']),
        'frontend_src': tree(ROOT / 'frontend/src', ['**/*']),
        'frontend_config': tree(ROOT / 'frontend', ['package.json', 'package-lock.json', 'tsconfig.json', 'vercel.json']),
        'retrieval_code': tree(WORK, ['src/*.py', 'checks/*.py']),
        'eval_files': tree(WORK, ['eval/*.json']),
        'pilots_prior': tree(WORK / 'pilots', ['step04d/*.json', 'step04e/*.json', 'step04f/*.json', 'step04g/*.json', 'step04h/*.json', 'step04i/*.json',
                                                'step04h/runs/*/*.json', 'step04i/runs/*/*.json', 'step04g/runs/*/*.json', 'step05/*.json', 'step05/*.jsonl', 'step05/*.py', 'step05/cache/*.json']),
        'out_chunks': tree(WORK / 'out/chunks', ['**/*']),
        'out_embeddings_docs': {k: v for k, v in tree(WORK / 'out/embeddings', ['**/*']).items() if 'queries.jsonl' not in k},
        'out_embeddings_queries': {k: v for k, v in tree(WORK / 'out/embeddings', ['**/queries.jsonl']).items()},
        'out_release': tree(WORK / 'out', [f'{REL}/**/*']),
        'data_chunks_legacy': tree(ROOT / 'data/processed', ['chunks.all.jsonl', 'page_map.json']),
        'db_fingerprint': fp.fingerprint(db.dsn(), REL, CS)}
p = Path(__file__).parent / f'preservation_{tag}.json'
p.write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding='utf-8')
print(p.name, {k: (len(v) if isinstance(v, (dict, list)) else v) for k, v in snap.items()})
