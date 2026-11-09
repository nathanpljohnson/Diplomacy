"""Build the public corresponding-source archive without private runtime files."""
from pathlib import Path
import zipfile

root = Path(__file__).parent
destination = root / 'public/source.zip'
with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root)
        if not path.is_file() or path.is_symlink():
            continue
        if any((part.startswith('.') and part not in ('.gitignore', '.vercelignore', '.env.example')) or part in ('data', '__pycache__', 'node_modules') for part in relative.parts):
            continue
        if path.suffix in ('.db', '.pyc', '.zip'):
            continue
        archive.write(path, str(relative))
print('Built public/source.zip (private data and environment files excluded).')
