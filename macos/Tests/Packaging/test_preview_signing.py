"""Synthetic CI-signing checks; never access the real keychain or Apple services."""
import base64
import json
import os
from pathlib import Path
import plistlib
import runpy
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SIGNING = ROOT / 'Packaging/prepare-preview-signing.sh'
PACKAGE = ROOT / 'package-dmg.py'


class PreviewSigningTests(unittest.TestCase):
    def prepare(self, directory, identities, missing=None):
        binary = directory / 'bin'
        binary.mkdir()
        security = binary / 'security'
        security.write_text('''#!/usr/bin/env python3
import os, sys
from pathlib import Path
with open(os.environ['CALLS'], 'a') as output: output.write(sys.argv[1] + '\\n')
if sys.argv[1] == 'find-identity': print(os.environ['IDENTITIES'])
''')
        security.chmod(0o755)
        env = {**os.environ, 'PATH': str(binary) + ':' + os.environ['PATH'],
               'RUNNER_TEMP': str(directory), 'GITHUB_ENV': str(directory / 'job.env'),
               'CALLS': str(directory / 'calls'), 'IDENTITIES': identities,
               'MACOS_CERTIFICATE_P12_BASE64': base64.b64encode(b'fake certificate').decode(),
               'MACOS_CERTIFICATE_PASSWORD': 'synthetic-password',
               'MACOS_NOTARY_KEY_P8_BASE64': base64.b64encode(b'fake notary key').decode(),
               'MACOS_NOTARY_KEY_ID': 'FAKEKEY123', 'MACOS_NOTARY_ISSUER_ID': 'fake-issuer',
               'MACOS_SIGNING_TEAM_ID': 'FAKETEAM12'}
        if missing:
            env.pop(missing)
        return subprocess.run(['bash', str(SIGNING)], env=env, capture_output=True, text=True)

    def test_missing_credentials_fail_before_keychain_access(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            result = self.prepare(directory, '', 'MACOS_NOTARY_KEY_P8_BASE64')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('MACOS_NOTARY_KEY_P8_BASE64', result.stderr)
            self.assertFalse((directory / 'calls').exists())
            self.assertFalse((directory / 'job.env').exists())

    def test_only_one_valid_distribution_identity_is_accepted(self):
        identity = 'A' * 40
        for identities, accepted in [
            (f'1) {identity} "Apple Development: Synthetic"', False),
            (f'1) {identity} "Developer ID Application: Synthetic"', True),
            (f'1) {identity} "Developer ID Application: First"\n'
             f'2) {"B" * 40} "Developer ID Application: Second"', False),
        ]:
            with self.subTest(accepted=accepted), tempfile.TemporaryDirectory() as folder:
                directory = Path(folder)
                result = self.prepare(directory, identities)
                self.assertEqual(result.returncode == 0, accepted, result.stderr)
                self.assertEqual((directory / 'job.env').exists(), accepted)
                if accepted:
                    output = (directory / 'job.env').read_text()
                    self.assertIn('DOUBAO_CODESIGN_IDENTITY=' + identity, output)
                    self.assertNotIn('synthetic-password', output + result.stdout + result.stderr)
                    self.assertNotIn('fake notary key', output + result.stdout + result.stderr)
                    for name in ['doubao-preview-certificate.p12', 'doubao-preview-notary.p8']:
                        self.assertEqual((directory / name).stat().st_mode & 0o777, 0o600)

    def package_failure(self, team, notarization):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            info = directory / 'build/macos/arm64/Doubao Say.app/Contents/Info.plist'
            info.parent.mkdir(parents=True)
            info.write_bytes(plistlib.dumps({'CFBundleShortVersionString': '1.0.0'}))
            calls = []

            def run(argv, **kwargs):
                calls.append(argv)
                signature = 'Authority=Developer ID Application: Synthetic\nflags=runtime\nTeamIdentifier=' + team
                return subprocess.CompletedProcess(argv, 0, stdout='', stderr=signature)

            def output(argv, **kwargs):
                calls.append(argv)
                return json.dumps({'status': notarization})

            previous = Path.cwd()
            try:
                os.chdir(directory)
                with patch.dict(os.environ, {'DOUBAO_EXPECTED_TEAM_ID': 'FAKETEAM12'}), \
                     patch('sys.argv', [str(PACKAGE), '--identity', 'fake', '--arch', 'arm64',
                                        '--key', 'fake.p8', '--key-id', 'fake', '--issuer', 'fake']), \
                     patch('subprocess.run', side_effect=run), \
                     patch('subprocess.check_output', side_effect=output):
                    with self.assertRaises(RuntimeError):
                        runpy.run_path(str(PACKAGE), run_name='__main__')
            finally:
                os.chdir(previous)
            self.assertFalse(list(directory.rglob('*.dmg')))
            return calls

    def test_preview_manifest_records_cross_compiled_artifact(self):
        manifest_script = ROOT / 'Packaging/preview-manifest.py'
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            for arch in ['arm64', 'x86_64']:
                app = directory / f'build/macos/{arch}/Doubao Say.app/Contents'
                app.mkdir(parents=True)
                (app / 'Info.plist').write_bytes(plistlib.dumps({
                    'CFBundleShortVersionString': '1.8.1',
                    'CFBundleIdentifier': 'md.lifeos.doubao-say.macos',
                }))
                (directory / f'build/macos/Doubao-Say-1.8.1-macos-{arch}-abc123.dmg').write_bytes(arch.encode())
            previous = Path.cwd()
            try:
                os.chdir(directory)
                for arch in ['arm64', 'x86_64']:
                    with self.subTest(arch=arch), \
                         patch.dict(os.environ, {'DOUBAO_MAC_ARCH': arch}), \
                         patch('platform.machine', return_value='arm64'), \
                         patch('subprocess.run', return_value=subprocess.CompletedProcess(
                             [], 0, stdout='designated => synthetic requirement', stderr='')), \
                         patch('subprocess.check_output', return_value='abc123'):
                        runpy.run_path(str(manifest_script), run_name='__main__')
                    manifest = json.loads(Path('build/macos/preview-manifest.json').read_text())
                    self.assertEqual(manifest['architecture'], arch)
                    self.assertEqual(manifest['artifact'], f'Doubao-Say-1.8.1-macos-{arch}-abc123.dmg')
                    self.assertEqual(manifest['commit'], 'abc123')
            finally:
                os.chdir(previous)

    def test_wrong_team_is_rejected_before_notarization(self):
        calls = self.package_failure('OTHERTEAM1', 'Accepted')
        self.assertFalse(any('notarytool' in call for call in calls))

    def test_rejected_notarization_never_reaches_dmg_creation(self):
        calls = self.package_failure('FAKETEAM12', 'Invalid')
        self.assertTrue(any('notarytool' in call for call in calls))
        self.assertFalse(any('hdiutil' in call for call in calls))


if __name__ == '__main__':
    unittest.main()
