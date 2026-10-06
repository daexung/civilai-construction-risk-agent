"""Create a source bundle containing only API code and required serving assets."""
from pathlib import Path
import hashlib
import json
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'tmp/poomsemi-backend-deploy.zip'
SOURCE_PDF = ROOT / 'data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf'
PACKAGED_PDF = 'data/raw/standard_estimation/standard-estimation-2026.pdf'
files = {ROOT / item for item in [
    'Dockerfile', '.dockerignore', '.gcloudignore', 'deploy/run_api.py', 'deploy/backend-requirements.txt', 'deploy/cloud-shell-build.sh',
    'pipeline/requirements-rag.txt', 'data/drafts/executable.json', 'data/drafts/misfiled.json',
    'data/processed/chunks.all.jsonl', 'data/processed/chunks.jsonl', 'data/processed/page_map.json',
    'data/processed/embeddings.all.gemini-embedding-2.parquet',
]}
files.add(SOURCE_PDF)
for folder, extensions in [('backend', {'.py', '.json', '.md', '.txt'}),
                            ('data/rates', {'.json'}), ('data/drafts/specs', {'.json'})]:
    files.update(path for path in (ROOT / folder).rglob('*') if path.is_file()
                 and path.suffix in extensions and '__pycache__' not in path.parts
                 and not path.name.startswith('.env'))
missing = [path.relative_to(ROOT).as_posix() for path in files if not path.is_file()]
if missing:
    raise SystemExit('Missing deployment assets: ' + ', '.join(sorted(missing)))
OUTPUT.parent.mkdir(exist_ok=True)
manifest = {}
with zipfile.ZipFile(OUTPUT, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
    for path in sorted(files):
        relative = PACKAGED_PDF if path == SOURCE_PDF else path.relative_to(ROOT).as_posix()
        bundle.write(path, relative)
        manifest[relative] = {'bytes': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    bundle.writestr('deploy/asset-manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
with zipfile.ZipFile(OUTPUT) as bundle:
    names = bundle.namelist()
    assert not any(Path(name).name.startswith('.env') or name.startswith(('frontend/', '.git/', '.venv/', 'tmp/')) for name in names)
    assert 'data/processed/embeddings.all.gemini-embedding-2.parquet' in names
    assert PACKAGED_PDF in names
    assert PACKAGED_PDF.isascii(), 'Deployment PDF path must use ASCII'
print(f'Prepared {len(files)} files, {OUTPUT.stat().st_size / 1024**2:.1f} MiB; no environment files or frontend included.')
print(OUTPUT)
