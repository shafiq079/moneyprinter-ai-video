"""Installed MoneyPrinter fonts served locally in browser-compatible SFNT form."""
from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from app.utils import utils


def catalog():
    root = Path(utils.root_dir()) / 'resource' / 'fonts'
    return [{'id': hashlib.sha256(p.name.encode()).hexdigest(), 'name': p.name,
             'family': 'MPT ' + p.name, 'label': p.stem}
            for p in sorted(root.iterdir()) if p.is_file() and not p.is_symlink()
            and not p.name.startswith('.') and p.suffix.lower() in {'.ttf', '.ttc', '.otf', '.woff', '.woff2'}]


def font_file(font_id):
    record = next((r for r in catalog() if r['id'] == font_id), None)
    if record is None:
        raise ValueError('font is unavailable')
    source = Path(utils.root_dir()) / 'resource' / 'fonts' / record['name']
    if source.suffix.lower() != '.ttc':
        return source
    # Browser FontFace cannot reliably read TrueType collections. Extract face 0,
    # matching the existing Pillow/MoviePy compositor's default collection face.
    from fontTools.ttLib import TTFont
    cache = Path(utils.storage_dir('opencut', create=True)) / 'fonts'
    cache.mkdir(exist_ok=True)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    target = cache / (digest + '.ttf')
    if not target.exists():
        handle, name = tempfile.mkstemp(dir=cache, suffix='.ttf')
        os.close(handle)
        temporary = Path(name)
        try:
            with TTFont(source, fontNumber=0) as font:
                font.save(temporary)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    return target
