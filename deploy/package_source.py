"""Create a deployment-only source archive; never include datasets or credentials."""
import argparse
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[1]
FILES = ('pyproject.toml', 'uv.lock', 'README.md', '.dockerignore')
DIRECTORIES = ('src', 'website', 'extension/frontend', 'artifacts', 'deploy')


def package_source(root: Path, destination: Path):
    paths = [root / name for name in FILES]
    for name in DIRECTORIES:
        paths.extend(path for path in (root / name).rglob('*') if path.is_file())
    selected = []
    for path in paths:
        relative = path.relative_to(root)
        if any((root / Path(*relative.parts[:i])).is_symlink() for i in range(1, len(relative.parts)+1)):
            continue
        if any(part in ('__pycache__', '.venv', '.ipynb_checkpoints', '.git') for part in relative.parts):
            continue
        if path.name.startswith('.env') or path.suffix in ('.pyc', '.pem', '.key', '.env'):
            continue
        if path.resolve() == destination.resolve():
            continue
        selected.append(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(destination, 'w:gz') as archive:
        for path in sorted(selected):
            archive.add(path, arcname=str(Path('SecondThought') / path.relative_to(root)), recursive=False)
    return len(selected)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('/tmp/secondthought-demo-source.tar.gz'))
    args = parser.parse_args()
    count = package_source(ROOT, args.output)
    print(f'Wrote {args.output}: {count} files, {args.output.stat().st_size / 1024**2:.1f} MiB')
