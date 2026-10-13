"""4f 작업 전 보존 기록: 변경 목록, 코드·설정·평가·출력 해시, DB 지문(읽기만). 작업 후에는 같은 도구를 --after로 다시 실행해 비교한다."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
WORK = Path(__file__).resolve().parents[2]          # experiments/retrieval-v1
ROOT = WORK.parents[1]
sys.path.insert(0, str(WORK / 'src'))
sys.path.insert(0, str(WORK / 'checks'))
import db  # noqa: E402
import fingerprint as fp  # noqa: E402

CS, REL = 'cs-37f81b5cfb1b-46f4f035c0fa', 'rk-complete-82c206c61e21-37f81b5cfb1b'


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def tree(base, pats):
    out = {}
    for pat in pats:
        for p in sorted(base.glob(pat)):
            if p.is_file():
                out[p.relative_to(ROOT).as_posix()] = sha(p)
    return out


def main(tag):
    git = subprocess.run(['git', 'status', '--porcelain'], cwd=ROOT, capture_output=True, text=True, encoding='utf-8').stdout.splitlines()
    snap = {
        'tag': tag,
        'git_status_porcelain': git,
        'code': tree(WORK, ['src/*.py', 'checks/*.py']),
        'service_llm_config': tree(ROOT / 'backend/agent/tools/llm', ['*.py', '*.json']),
        'shared_embedding': tree(ROOT / 'backend/shared', ['embedding.py']),
        'eval_and_freeze': tree(WORK, ['eval/*.json']),
        'baseline_runs': tree(WORK / 'out/verification_runs' / CS, ['20261012T123241-eval_selection_new/*.json', '20261012T123214-eval_selection_dev/*.json', 'index.json']),
        'pilot_step04c': tree(WORK / 'pilots/step04c', ['*.json', '*.jsonl', 'responses/**/*.json', 'candidates/*.json', 'prompts/*.txt']),
        'pilot_step04d': tree(WORK / 'pilots/step04d', ['*.json', '*.jsonl', 'runs/reg60-g/*.json', 'runs/rep-*/*.json', 'runs/dev12-*/*.json', 'cache/*.json', '*.py']),
        'pilot_step04e': tree(WORK / 'pilots/step04e', ['*.json', '*.jsonl', 'runs/*/*.json', 'cache/*.json', '*.py']),
        'eval_docs': tree(ROOT / 'docs/reviews', ['retrieval-step-04*.md']),
        'eval_planning': tree(ROOT / 'docs/planning', ['claude-step-04*.md']),
        'out_chunks': tree(WORK / 'out/chunks', ['**/*']),
        'out_embeddings': tree(WORK / 'out/embeddings', ['**/*']),
        'out_release': tree(WORK / 'out', [f'{REL}/**/*']),
        'db_fingerprint': fp.fingerprint(db.dsn(), REL, CS),
    }
    path = Path(__file__).parent / f'preservation_{tag}.json'
    path.write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding='utf-8')
    print(path.name, {k: (len(v) if isinstance(v, (dict, list)) else v) for k, v in snap.items()})


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'before')
