#!/usr/bin/env python3
"""Remove working copies of release attachments that are confirmed identical to the released files.

usage: cleanup_copies.py [--apply] DIR [DIR ...]
  DIR: a release staging folder (DIR/<tag>/<sha256>.v4.gz | .tt.gz, MANIFEST.json)

A file is removed only if
  * its name is <sha256>.v4.gz or <sha256>.tt.gz and the SHA-256 of its content equals that name, and
  * a record in this repository says that this asset of this release was downloaded again after the upload and matched
    (an entry with release_tag, asset and uploaded_verified in results/*/archive/INDEX.json, results/*/INDEX.json or
    results/states/INDEX.json).
A tag folder's MANIFEST.json (also a release attachment) is removed only when every other file of the folder was.
Without --apply nothing is deleted; the plan is printed. Git history is never touched: in a git work tree the caller
commits the deletions (they stay in history).
"""
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def verified_assets():
    out = {}

    def walk(x, src):
        if isinstance(x, dict):
            if x.get('release_tag') and x.get('asset') and x.get('uploaded_verified'):
                out[(x['release_tag'], x['asset'])] = (src, x['uploaded_verified'])
            for v in x.values():
                walk(v, src)
        elif isinstance(x, list):
            for v in x:
                walk(v, src)
    for p in sorted(list((HERE / 'results').glob('*/archive/INDEX.json')) + list((HERE / 'results').glob('*/INDEX.json'))):
        walk(json.loads(p.read_text(encoding='utf-8')), str(p.relative_to(HERE)))
    return out


def main():
    apply = '--apply' in sys.argv
    dirs = [Path(a) for a in sys.argv[1:] if a != '--apply']
    ok = verified_assets()
    plan = {'remove': [], 'keep': [], 'bytes': 0}
    for d in dirs:
        for tagdir in sorted(p for p in d.iterdir() if p.is_dir()):
            tag = tagdir.name
            files = sorted(p for p in tagdir.iterdir() if p.is_file() and p.name != 'MANIFEST.json')
            gone = 0
            for f in files:
                stem = f.name.split('.')[0]
                good = f.name.endswith(('.v4.gz', '.tt.gz')) and (tag, f.name) in ok and sha(f) == stem
                if good:
                    plan['remove'].append(str(f)); plan['bytes'] += f.stat().st_size; gone += 1
                else:
                    plan['keep'].append(str(f))
            m = tagdir / 'MANIFEST.json'
            if m.exists():
                (plan['remove'] if gone == len(files) else plan['keep']).append(str(m))
    if apply:
        for f in plan['remove']:
            Path(f).unlink()
        for d in dirs:
            for tagdir in d.iterdir():
                if tagdir.is_dir() and not any(tagdir.iterdir()):
                    tagdir.rmdir()
    print(json.dumps({'applied': apply, 'remove': len(plan['remove']), 'keep': len(plan['keep']), 'bytes_removed': plan['bytes'],
                      'kept': plan['keep'][:20]}, ensure_ascii=False))


if __name__ == '__main__':
    main()
