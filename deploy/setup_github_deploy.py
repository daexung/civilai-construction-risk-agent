"""One-time Cloud Shell setup using existing serving data, no service account keys."""
import argparse
import json
import subprocess
import time
from pathlib import Path

from serving_assets import BUCKET, PDF, VERSION, manifest, matches

PROJECT = 'civil-ai-jds'
NUMBER = '691785957289'
REGION = 'asia-northeast3'
POOL = 'poomsemi-github'
CALLER = f'poomsemi-github-deploy@{PROJECT}.iam.gserviceaccount.com'
RUNTIME = f'poomsemi-api-runtime@{PROJECT}.iam.gserviceaccount.com'
SUBJECT = 'repo:daexung/civilai-construction-risk-agent:ref:refs/heads/main'
CONDITION = "assertion.repository_id == '1277805743' && assertion.repository_owner_id == '164707261' && assertion.ref == 'refs/heads/main'"


def command(*args):
    return ['gcloud', *args, '--project', PROJECT, '--quiet']


def run(*args):
    subprocess.run(command(*args), check=True)


def exists(*args):
    return subprocess.run(command(*args), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def grant(*args):
    # A newly created service account/pool may not be visible to IAM immediately.
    for delay in (5, 10, 20, 30, 30):
        result = subprocess.run(command(*args))
        if result.returncode == 0:
            return
        print(f'IAM not ready; retrying in {delay}s', flush=True)
        time.sleep(delay)
    subprocess.run(command(*args), check=True)


def locate(source: Path, items: dict) -> dict:
    found = {}
    for name, expected in items.items():
        candidate = source / name
        if matches(candidate, expected):
            found[name] = candidate
        elif name == PDF:
            # Also handles filenames converted by the old unzip command.
            candidates = sorted((source / 'data/raw/standard_estimation').glob('*.pdf'))
            found[name] = next((item for item in candidates if matches(item, expected)), None)
        else:
            found[name] = None
        if found[name] is None:
            raise ValueError(f'Missing or changed serving file: {name}; no cloud settings changed')
    return found


def setup(source: Path):
    items = manifest(Path(__file__).with_name('serving-assets.json'))
    found = locate(source.resolve(), items)
    print('Existing serving files verified. Preparing private storage and GitHub IAM.', flush=True)
    run('services', 'enable', 'iam.googleapis.com', 'iamcredentials.googleapis.com',
        'sts.googleapis.com', 'storage.googleapis.com', 'artifactregistry.googleapis.com', 'run.googleapis.com')
    bucket = f'gs://{BUCKET}'
    if not exists('storage', 'buckets', 'describe', bucket):
        run('storage', 'buckets', 'create', bucket, '--location', REGION,
            '--uniform-bucket-level-access', '--public-access-prevention')
    else:
        info = json.loads(subprocess.check_output(command('storage', 'buckets', 'describe', bucket, '--format=json')))
        if str(info.get('project_number', info.get('projectNumber', ''))) != NUMBER:
            raise ValueError('Asset bucket is not in the expected GCP project')
        run('storage', 'buckets', 'update', bucket, '--uniform-bucket-level-access', '--public-access-prevention')
    for name, path in found.items():
        run('storage', 'cp', str(path), f'{bucket}/{VERSION}/{name}')
    if not exists('iam', 'workload-identity-pools', 'describe', POOL, '--location=global'):
        run('iam', 'workload-identity-pools', 'create', POOL, '--location=global', '--display-name=Poomsemi GitHub')
    provider_args = ('--location=global', f'--workload-identity-pool={POOL}')
    if not exists('iam', 'workload-identity-pools', 'providers', 'describe', 'github', *provider_args):
        run('iam', 'workload-identity-pools', 'providers', 'create-oidc', 'github', *provider_args,
            '--issuer-uri=https://token.actions.githubusercontent.com',
            '--attribute-mapping=google.subject=assertion.sub', f'--attribute-condition={CONDITION}')
    else:
        run('iam', 'workload-identity-pools', 'providers', 'update-oidc', 'github', *provider_args,
            '--issuer-uri=https://token.actions.githubusercontent.com',
            '--attribute-mapping=google.subject=assertion.sub', f'--attribute-condition={CONDITION}')
    if not exists('iam', 'service-accounts', 'describe', CALLER):
        run('iam', 'service-accounts', 'create', 'poomsemi-github-deploy', '--display-name=Poomsemi GitHub deploy')
    grant('iam', 'service-accounts', 'add-iam-policy-binding', CALLER,
          '--role=roles/iam.workloadIdentityUser',
          f'--member=principal://iam.googleapis.com/projects/{NUMBER}/locations/global/workloadIdentityPools/{POOL}/subject/{SUBJECT}')
    member = f'--member=serviceAccount:{CALLER}'
    grant('storage', 'buckets', 'add-iam-policy-binding', bucket, member, '--role=roles/storage.objectViewer')
    grant('artifacts', 'repositories', 'add-iam-policy-binding', 'poomsemi', '--location', REGION,
          member, '--role=roles/artifactregistry.writer')
    grant('run', 'services', 'add-iam-policy-binding', 'poomsemi-api', '--region', REGION,
          member, '--role=roles/run.developer')
    grant('iam', 'service-accounts', 'add-iam-policy-binding', RUNTIME,
          member, '--role=roles/iam.serviceAccountUser')
    print('GitHub deployment setup complete', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, default=Path.home() / 'poomsemi-deploy')
    setup(parser.parse_args().source)
