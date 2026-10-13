"""Stage only product files for native RPM and Flatpak builders."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tomllib

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', choices=('rpm', 'flatpak'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise SystemExit('Output must be a new directory')
    version = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['version']
    output.mkdir(parents=True)
    source = output / ('source' if args.kind == 'flatpak' else f'doubao-say-{version}')
    source.mkdir()
    # Never copy Git metadata, credentials, ignored build products, or caches.
    shutil.copytree(ROOT / 'src', source / 'src', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copytree(ROOT / 'packaging/store', source / 'packaging/store')
    for name in ('README.md', 'LICENSE', 'NOTICE', 'pyproject.toml'):
        shutil.copy2(ROOT / name, source / name)
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    (output / 'SOURCE.json').write_text(json.dumps({'version': version, 'commit': revision}, indent=2) + '\n')
    if args.kind == 'rpm':
        for name in ('SOURCES', 'SPECS', 'BUILD', 'BUILDROOT', 'RPMS', 'SRPMS'):
            (output / name).mkdir()
        with tarfile.open(output / 'SOURCES' / f'doubao-say-{version}.tar.gz', 'w:gz') as archive:
            archive.add(source, arcname=source.name)
        spec = (ROOT / 'packaging/store/doubao-say.spec').read_text().replace('@VERSION@', version)
        (output / 'SPECS/doubao-say.spec').write_text(spec)
    else:
        shutil.copy2(ROOT / 'packaging/store/md.lifeos.DoubaoSay.json', output)
    print(version)


if __name__ == '__main__':
    main()
