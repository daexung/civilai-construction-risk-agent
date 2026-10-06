"""Offline checks for serving asset integrity and bootstrap permission boundaries."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'deploy'))
import serving_assets as assets
import setup_github_deploy as bootstrap


class DeployAssetChecks(unittest.TestCase):
    def test_current_local_snapshot_matches_deployment_manifest(self):
        found = bootstrap.locate(ROOT, assets.manifest(ROOT / 'deploy/serving-assets.json'))
        self.assertEqual(set(found), assets.ASSET_PATHS)

    def test_unknown_paths_and_bad_digests_are_rejected(self):
        expected = assets.manifest(ROOT / 'deploy/serving-assets.json')
        with tempfile.TemporaryDirectory(dir=ROOT / 'tmp') as folder:
            target = Path(folder) / 'manifest.json'
            for bad in [dict(expected, **{'../secret': {'bytes': 1, 'sha256': '0' * 64}}),
                        dict(expected, **{assets.PDF: {'bytes': 1, 'sha256': 'invalid'}})]:
                target.write_text(json.dumps(bad))
                with self.assertRaises(ValueError):
                    assets.manifest(target)

    def test_missing_data_stops_before_cloud_mutation(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'tmp') as folder, patch.object(bootstrap, 'run') as run:
            with self.assertRaises(ValueError):
                bootstrap.setup(Path(folder))
            run.assert_not_called()

    def test_corrupt_download_stops_before_other_assets(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'tmp') as folder:
            snapshot = {'data/processed/chunks.all.jsonl': {'bytes': 5, 'sha256': hashlib.sha256(b'valid').hexdigest()}}
            def download(command, **kwargs):
                Path(command[-1]).write_bytes(b'wrong')
            with patch.object(assets, 'ROOT', Path(folder)), patch.object(assets, 'manifest', return_value=snapshot), \
                    patch.object(assets.subprocess, 'run', side_effect=download) as run:
                with self.assertRaises(ValueError):
                    assets.download()
                self.assertEqual(run.call_count, 1)

    def test_iam_grants_are_scoped_and_do_not_create_keys_or_public_access(self):
        items = assets.manifest(ROOT / 'deploy/serving-assets.json')
        found = {name: Path(name) for name in items}
        with patch.object(bootstrap, 'locate', return_value=found), patch.object(bootstrap, 'exists', return_value=False), \
                patch.object(bootstrap, 'run') as run, patch.object(bootstrap, 'grant') as grant:
            bootstrap.setup(ROOT)
        commands = [call.args for call in run.call_args_list + grant.call_args_list]
        joined = '\n'.join(' '.join(map(str, args)) for args in commands)
        self.assertIn("assertion.repository_id == '1277805743'", joined)
        self.assertIn("assertion.ref == 'refs/heads/main'", joined)
        self.assertNotIn('allUsers', joined)
        self.assertNotIn('roles/owner', joined)
        self.assertNotIn('roles/editor', joined)
        self.assertNotIn('secretmanager', joined)
        self.assertNotIn('keys create', joined)
        self.assertFalse(any(args[:2] == ('projects', 'add-iam-policy-binding') for args in commands))
        self.assertIn('roles/run.developer', joined)


if __name__ == '__main__':
    unittest.main()
