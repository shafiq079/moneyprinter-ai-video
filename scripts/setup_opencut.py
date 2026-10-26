"""Fetch the reviewed OpenCut Classic revision and build the real editor locally."""
import argparse
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / 'webui' / 'opencut_frontend'
PIN = json.loads((FRONTEND / 'upstream.json').read_text())
REVISION = PIN['revision']
REMOTE = PIN['repository']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-only', action='store_true', help='Fetch source without installing/building Node packages')
    args = parser.parse_args()
    source = FRONTEND / 'upstream'
    if not source.exists():
        subprocess.run(['git', 'clone', '--no-checkout', '--filter=blob:none', REMOTE, str(source)], check=True)
    remote = subprocess.check_output(['git', '-C', str(source), 'remote', 'get-url', 'origin'], text=True).strip()
    if remote.lower().rstrip('/') != REMOTE.lower():
        raise SystemExit('OpenCut source origin differs from the pinned upstream.')
    subprocess.run(['git', '-C', str(source), 'fetch', '--depth', '1', 'origin', REVISION], check=True)
    subprocess.run(['git', '-C', str(source), 'checkout', '--detach', REVISION], check=True)
    actual = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != REVISION:
        raise SystemExit('OpenCut revision verification failed')
    # Keep downloaded/build output out of status after switching to development.
    exclude = subprocess.check_output(['git', 'rev-parse', '--git-path', 'info/exclude'], cwd=ROOT, text=True).strip()
    exclude_path = Path(exclude) if Path(exclude).is_absolute() else ROOT / exclude
    old_excludes = exclude_path.read_text() if exclude_path.exists() else ''
    additions = [line for line in ('/webui/opencut_frontend/upstream/', '/webui/opencut_frontend/dist/') if line not in old_excludes]
    if additions:
        exclude_path.parent.mkdir(parents=True, exist_ok=True)
        exclude_path.write_text(old_excludes + '\n' + '\n'.join(additions) + '\n')
    if args.source_only:
        return
    npm = shutil.which('npm.cmd') or shutil.which('npm')
    node = shutil.which('node')
    if node and int(subprocess.check_output([node, '-p', 'process.versions.node'], text=True).split('.')[0]) < 22:
        raise SystemExit('OpenCut integration requires Node.js 22 or newer.')
    if not npm or not node:
        raise SystemExit('Install Node.js 22 LTS (with npm), then rerun this setup command.')
    subprocess.run([npm, 'ci', '--ignore-scripts'], cwd=FRONTEND, check=True)
    subprocess.run([npm, 'run', 'build'], cwd=FRONTEND, check=True)
    (FRONTEND / 'dist' / 'moneyprinter-build.json').write_text(json.dumps({'upstream': REMOTE, 'revision': REVISION}) + '\n')
    print('OpenCut is ready. Start MoneyPrinter with sh webui.sh (or webui.bat).')


if __name__ == '__main__':
    main()
