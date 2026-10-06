"""Make a separate private upload for Secret Manager, never part of the image."""
import json
from pathlib import Path
import zipfile
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
names = ['CHAT_DATABASE_URL', 'QUOTA_HASH_SECRET', 'SUPABASE_SECRET_KEY',
         'SUPABASE_URL', 'SUPABASE_PUBLISHABLE_KEY', 'GEMINI_API_KEY']
settings = dotenv_values(ROOT / '.env')
values = {name: settings.get(name) for name in names}
if not all(values.values()):
    raise SystemExit('Missing settings: ' + ', '.join(name for name, value in values.items() if not value))
if len(values['QUOTA_HASH_SECRET']) < 32:
    raise SystemExit('QUOTA_HASH_SECRET must have at least 32 characters; do not rotate the existing value casually.')
output = ROOT / 'tmp/poomsemi-secrets-private.zip'
output.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
    bundle.writestr('secret-settings.json', json.dumps(values, ensure_ascii=False))
    bundle.write(ROOT / 'deploy/register_secrets.py', 'register_secrets.py')
print('Private Secret Manager upload prepared; 6 settings, values not displayed. This file must not be shared or included in Docker builds.')
print(output)
