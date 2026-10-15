"""Sign, notarize and verify a drag-to-install DMG from a Developer ID app."""
import argparse
import json
import os
import plistlib
import platform
import hashlib
from pathlib import Path
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument('--identity', required=True)
parser.add_argument('--arch', choices=['arm64', 'x86_64'], default=platform.machine())
parser.add_argument('--profile')
parser.add_argument('--key')
parser.add_argument('--key-id')
parser.add_argument('--issuer')
args = parser.parse_args()
if args.profile:
    credentials = ['--keychain-profile', args.profile]
elif args.key and args.key_id and args.issuer:
    credentials = ['--key', args.key, '--key-id', args.key_id, '--issuer', args.issuer]
else:
    parser.error('Provide a keychain profile or an API key path, key ID and issuer')
app = Path(f'build/macos/{args.arch}/Doubao Say.app').resolve()
version = plistlib.loads((app / 'Contents/Info.plist').read_bytes())['CFBundleShortVersionString']
stage = Path('build/macos/dmg-stage')
stage.mkdir(parents=True, exist_ok=True)

def run(*argv):
    subprocess.run(argv, check=True)

def notarize(artifact):
    result = subprocess.check_output(['xcrun', 'notarytool', 'submit', str(artifact), *credentials, '--wait', '--output-format', 'json'], text=True)
    data = json.loads(result)
    artifact.with_suffix(artifact.suffix + '.notary.json').write_text(json.dumps(data, indent=2))
    if data.get('status') != 'Accepted':
        raise RuntimeError('Apple notarization was not accepted; inspect the submission log')
    run('xcrun', 'stapler', 'staple', str(artifact))
    run('xcrun', 'stapler', 'validate', str(artifact))

run('codesign', '--verify', '--strict', str(app))
signature = subprocess.run(['codesign', '-d', '--verbose=4', str(app)], capture_output=True, text=True, check=True).stderr
if 'Developer ID Application:' not in signature or 'runtime' not in signature:
    raise RuntimeError('Build with DOUBAO_CODESIGN_IDENTITY and hardened runtime first')
expected_team = os.environ.get('DOUBAO_EXPECTED_TEAM_ID')
if expected_team and f'TeamIdentifier={expected_team}' not in signature.splitlines():
    raise RuntimeError('Preview signing team does not match the configured release team')
archive = Path('build/macos/Doubao-Say-notarization.zip').resolve()
run('ditto', '-c', '-k', '--keepParent', str(app), str(archive))
# Apple accepts ZIP submissions; the ticket is stapled to the contained application.
result = subprocess.check_output(['xcrun', 'notarytool', 'submit', str(archive), *credentials, '--wait', '--output-format', 'json'], text=True)
data = json.loads(result)
archive.with_suffix('.notary.json').write_text(json.dumps(data, indent=2))
if data.get('status') != 'Accepted':
    raise RuntimeError('Application notarization was not accepted')
run('xcrun', 'stapler', 'staple', str(app))
run('xcrun', 'stapler', 'validate', str(app))
run('spctl', '--assess', '--type', 'execute', '--verbose=2', str(app))
run('ditto', str(app), str(stage / app.name))
shortcut = stage / 'Applications'
if not shortcut.is_symlink():
    os.symlink('/Applications', shortcut)
commit = subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD'], text=True).strip()
dmg = Path(f'build/macos/Doubao-Say-{version}-macos-{args.arch}-{commit}.dmg').resolve()
run('hdiutil', 'create', '-volname', 'Doubao Say', '-srcfolder', str(stage), '-fs', 'HFS+', '-format', 'UDZO', '-ov', str(dmg))
run('codesign', '--sign', args.identity, '--timestamp', str(dmg))
notarize(dmg)
run('spctl', '--assess', '--type', 'open', '--context', 'context:primary-signature', '--verbose=2', str(dmg))
dmg.with_suffix('.dmg.sha256').write_text(hashlib.sha256(dmg.read_bytes()).hexdigest() + '  ' + dmg.name + '\n')
print(f'PASS: signed, notarized and stapled DMG: {dmg}', flush=True)
