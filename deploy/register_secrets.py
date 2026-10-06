"""Run in Cloud Shell to import selected settings into Secret Manager."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

PROJECT = 'civil-ai-jds'
ACCOUNT_NAME = 'poomsemi-api-runtime'
ACCOUNT = f'{ACCOUNT_NAME}@{PROJECT}.iam.gserviceaccount.com'
NAMES = ['CHAT_DATABASE_URL', 'QUOTA_HASH_SECRET', 'SUPABASE_SECRET_KEY',
         'SUPABASE_URL', 'SUPABASE_PUBLISHABLE_KEY', 'GEMINI_API_KEY']
source = Path(__file__).with_name('secret-settings.json')
values = json.loads(source.read_text(encoding='utf-8'))
if set(values) != set(NAMES) or not all(isinstance(value, str) and value for value in values.values()):
    raise SystemExit('The selected server settings are incomplete.')

def run(*arguments):
    subprocess.run(['gcloud', *arguments, '--project', PROJECT, '--quiet'], check=True)

def exists(*arguments):
    return subprocess.run(['gcloud', *arguments, '--project', PROJECT],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0

run('services', 'enable', 'secretmanager.googleapis.com', 'iam.googleapis.com')
if not exists('iam', 'service-accounts', 'describe', ACCOUNT):
    run('iam', 'service-accounts', 'create', ACCOUNT_NAME, '--display-name', 'Poomsemi API runtime')
for key in NAMES:
    secret = 'poomsemi-' + key.lower().replace('_', '-')
    if not exists('secrets', 'describe', secret):
        run('secrets', 'create', secret, '--replication-policy', 'automatic')
    handle, filename = tempfile.mkstemp(prefix='poomsemi-secret-')
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as output:
            output.write(values[key])
        run('secrets', 'versions', 'add', secret, '--data-file', filename)
    finally:
        Path(filename).unlink(missing_ok=True)
    run('secrets', 'add-iam-policy-binding', secret, '--member', 'serviceAccount:' + ACCOUNT,
        '--role', 'roles/secretmanager.secretAccessor')
    print(f'Connected {key} -> {secret}:latest')
source.unlink()
print('\nService account:', ACCOUNT)
print('Registration complete. No Cloud Run service was deployed. Delete the uploaded secrets ZIP after success.')
