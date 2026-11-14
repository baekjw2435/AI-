#!/usr/bin/env python3
"""Finish the portable bundle: README, SHA256SUMS.txt, and a reproducible ZIP.

usage: pack_portable.py BUNDLE_DIR ZIP_PATH [SUMS_COPY]
  BUNDLE_DIR  make_portable.py's output (presentation-map/)
  ZIP_PATH    the ZIP to write; entries are presentation-map/<path>
  SUMS_COPY   where to also write the sha256 list plus the ZIP's own line (kept in the repository)

The ZIP is byte-for-byte reproducible from the same files: entries sorted by path, every timestamp 2026-11-14 00:00,
unix mode 0644, deflate level 9 for every file.
"""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile

HERE = Path(__file__).resolve().parent
STAMP = (2026, 11, 14, 0, 0, 0)


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def main():
    out, zpath = Path(sys.argv[1]), Path(sys.argv[2])
    sums_copy = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    shutil.copyfile(HERE / 'PORTING_KO.md', out / 'README_KO.md')
    files = sorted(p.relative_to(out).as_posix() for p in out.rglob('*') if p.is_file() and p.name != 'SHA256SUMS.txt')
    lines = [f'{sha(out / f)}  {f}' for f in files]
    (out / 'SHA256SUMS.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    files = sorted(files + ['SHA256SUMS.txt'])
    root = out.name
    with zipfile.ZipFile(zpath, 'w') as z:
        for f in files:
            zi = zipfile.ZipInfo(f'{root}/{f}', date_time=STAMP)
            zi.create_system = 3
            zi.external_attr = 0o100644 << 16
            zi.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(zi, (out / f).read_bytes(), compresslevel=9)
    sizes = {f: (out / f).stat().st_size for f in files}
    big = max(sizes, key=lambda f: (sizes[f], f))
    zsha, zsize = sha(zpath), zpath.stat().st_size
    if sums_copy:
        sums_copy.write_text((out / 'SHA256SUMS.txt').read_text(encoding='utf-8') +
                             f'{sha(out / "SHA256SUMS.txt")}  SHA256SUMS.txt\n{zsha}  {zpath.name}\n', encoding='utf-8')
    print(json.dumps({'files': len(files), 'bytes': sum(sizes.values()), 'largest': [big, sizes[big]],
                      'zip': zpath.name, 'zip_bytes': zsize, 'zip_sha256': zsha}, ensure_ascii=False))


if __name__ == '__main__':
    main()
