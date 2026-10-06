"""Validate and retrieve a versioned serving snapshot; never regenerate embeddings."""
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUCKET = 'civil-ai-jds-poomsemi-assets'
VERSION = 'serving/20261006'
PDF = 'data/raw/standard_estimation/standard-estimation-2026.pdf'
ASSET_PATHS = {
    'data/processed/chunks.all.jsonl', 'data/processed/chunks.jsonl',
    'data/processed/page_map.json', 'data/processed/embeddings.all.gemini-embedding-2.parquet', PDF,
}


def manifest(path: Path) -> dict:
    items = json.loads(path.read_text(encoding='utf-8'))
    if set(items) != ASSET_PATHS:
        raise ValueError('Serving manifest must contain exactly the expected five assets')
    for name, expected in items.items():
        if not re.fullmatch(r'[a-f0-9]{64}', expected.get('sha256', '')):
            raise ValueError(f'Invalid serving digest: {name}')
        if not isinstance(expected.get('bytes'), int) or expected['bytes'] <= 0:
            raise ValueError(f'Invalid serving size: {name}')
    return items


def matches(path: Path, expected: dict) -> bool:
    if not path.is_file() or path.stat().st_size != expected['bytes']:
        return False
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest() == expected['sha256']


def download() -> None:
    for name, expected in manifest(ROOT / 'deploy/serving-assets.json').items():
        target = ROOT / name
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['gcloud', 'storage', 'cp', f'gs://{BUCKET}/{VERSION}/{name}', str(target)], check=True)
        if not matches(target, expected):
            raise ValueError(f'Serving asset checksum mismatch: {name}')
        print(f'Verified {name}', flush=True)


if __name__ == '__main__':
    download()
