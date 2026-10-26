import argparse
import hashlib
import json
import os
import pathlib
import re
import subprocess
import zipfile

root = pathlib.Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description='Build an independently installable DecryptHub MCP gateway component.')
parser.add_argument('--output', default=str(root / 'dist'))
args = parser.parse_args()
plugin = 'idh' if (root / 'src' / 'idh').is_dir() else 'adh'
metadata = (root / 'pyproject.toml').read_text(encoding='utf-8')
version = re.search(r'^version\s*=\s*"([^"]+)"', metadata, re.M).group(1)
if not re.fullmatch(r'\d+\.\d+\.\d+(?:-[\w.-]+)?', version):
    raise SystemExit('Unsupported component version')
repository = f'decrypthub/{plugin}-cli'
commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
launcher = ('import pathlib, runpy, sys\n'
            'sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "src"))\n'
            + ('if "--no-auto-update" not in sys.argv: sys.argv.insert(1, "--no-auto-update")\n' if plugin == 'idh' else '') +
            f'runpy.run_module("{plugin}", run_name="__main__")\n').encode()
files = []
contents = {'launch.py': launcher}
for name in ['src', 'LICENSE', 'README.md', 'pyproject.toml']:
    source = root / name
    candidates = sorted(source.rglob('*')) if source.is_dir() else [source]
    for item in candidates:
        if item.is_symlink():
            raise SystemExit(f'Refusing linked source: {item}')
        if not item.is_file() or '__pycache__' in item.parts or item.suffix in ['.pyc', '.pyo']:
            continue
        contents[item.relative_to(root).as_posix()] = item.read_bytes()
for name, data in sorted(contents.items()):
    files.append({'path': name, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
manifest = {'manifestVersion': 1, 'id': plugin, 'version': version, 'apiVersion': 1,
            'runtime': 'python', 'python': '>=3.10', 'entrypoint': 'launch.py',
            'platform': 'any', 'arch': 'any', 'source': {'repository': repository, 'commit': commit}, 'files': files}
output = pathlib.Path(args.output).resolve()
output.mkdir(parents=True, exist_ok=True)
archive = output / f'{plugin}-{version}-any.zip'
with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
    bundle.writestr('component.json', json.dumps(manifest, indent=2) + '\n')
    for name, data in sorted(contents.items()):
        info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
        info.external_attr = 0o100644 << 16
        bundle.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
digest = hashlib.sha256(archive.read_bytes()).hexdigest()
(archive.with_suffix('.zip.sha256')).write_text(f'{digest}  {archive.name}\n', encoding='utf-8')
print(json.dumps({'id': plugin, 'version': version, 'path': str(archive), 'sha256': digest, 'commit': commit}))
