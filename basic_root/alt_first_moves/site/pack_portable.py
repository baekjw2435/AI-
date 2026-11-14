#!/usr/bin/env python3
"""Finish the portable bundle: the guide with its numbers filled in, SHA256SUMS.txt, and reproducible ZIPs.

usage:
  pack_portable.py docs BUNDLE_DIR --tests TESTS.json --date DATE --zip-name NAME.zip
        Renders PORTING_KO.template.md with the bundle's numbers and the test results in TESTS.json into
        BUNDLE_DIR/README_KO.md and (when the template sits next to this script) PORTING_KO.md beside it,
        then writes BUNDLE_DIR/SHA256SUMS.txt. The guide states the bundle's own total size, which includes the
        guide, so the number is found by iterating until it no longer changes.
  pack_portable.py zip BUNDLE_DIR ZIP_PATH [--base-sums OLD_SHA256SUMS.txt --update-zip UPDATE_PATH]
        Checks every file against SHA256SUMS.txt and writes the full ZIP: the listed files plus SHA256SUMS.txt.
        With --base-sums (the SHA256SUMS.txt of an earlier release) it also writes an update ZIP with only the
        files that are new or changed since then, SHA256SUMS.txt, and UPDATE_KO.txt (what was added, changed,
        removed). Prints sizes and SHA-256 as JSON.

Both ZIPs are byte-for-byte reproducible from the same files (with the same zlib): entries presentation-map/<path>
sorted by path, timestamps fixed to 2026-11-14 00:00, unix mode 0644, deflate level 9.
This file is also copied to the delivery repository (.github/pack_portable.py), where only 'zip' is used.
"""
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import zipfile

HERE = Path(__file__).resolve().parent
STAMP = (2026, 11, 14, 0, 0, 0)
ROOT = 'presentation-map'


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def read_sums(path):
    out = {}
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        h, name = line.split('  ', 1)
        out[name] = h
    return out


def opts(args):
    return {args[i]: args[i + 1] for i in range(0, len(args), 2)}


def n(x):
    return f'{x:,}'


def docs(bundle, o):
    tests = json.loads(Path(o['--tests']).read_text(encoding='utf-8'))
    man = json.loads((bundle / 'manifest.json').read_text(encoding='utf-8'))
    pidx = json.loads((bundle / 'pindex.json').read_text(encoding='utf-8'))
    tpl = (HERE / 'PORTING_KO.template.md').read_text(encoding='utf-8')
    others = sorted(p.relative_to(bundle).as_posix() for p in bundle.rglob('*')
                    if p.is_file() and p.name not in ('README_KO.md', 'SHA256SUMS.txt'))
    size = {f: (bundle / f).stat().st_size for f in others}
    tables = [f for f in others if f.startswith('t/')]
    big = max(size, key=lambda f: (size[f], f))
    own = [b for b in man['books'] if b['id'].startswith('p')]
    old = [b for b in man['books'] if not b['id'].startswith('p')]
    kinds = {}
    for g in pidx['groups']:
        for it in g['items']:
            kinds[it['kind']] = kinds.get(it['kind'], 0) + 1
    nfiles = len(others) + 2
    sums_len = sum(64 + 2 + len(f.encode()) + 1 for f in others + ['README_KO.md'])   # SHA256SUMS.txt lists all but itself
    v = {'date': o['--date'], 'zip_name': o['--zip-name'], 'files': n(nfiles), 'tables': n(len(tables)),
         'table_bytes': n(sum(size[f] for f in tables)), 'largest_path': big, 'largest_bytes': n(size[big]),
         'largest_mb': f'{size[big] / 1e6:.1f}', 'table_max_mb': f'{math.ceil(max(size[f] for f in tables) / 1e4) / 100:.2f}',
         'books': n(len(man['books'])), 'entries': n(man['total_entries']),
         'targets': n(pidx['progress']['targets']), 'verified': n(pidx['progress']['verified']),
         'own': n(kinds.get('own', 0)), 'old': n(kinds.get('old', 0)), 'open': n(kinds.get('open', 0)),
         'boot_mb': f"{sum(size[f] for f in ('model.json', 'manifest.json', 'pindex.json')) / 1e6:.1f}"}
    for key, bs in (('own', own), ('old', old)):
        v[key + '_books'] = n(len(bs))
        v[key + '_files'] = n(sum(len(b['files']) for b in bs))
        v[key + '_bytes'] = n(sum(f['bytes'] for b in bs for f in b['files']))
        v[key + '_entries'] = n(sum(b['entries'] for b in bs))
    for f in ('index.html', 'site-engine.js', 'model.json', 'manifest.json', 'pindex.json'):
        v['size:' + f] = n(size[f])
    for k, x in tests.items():
        v['test_' + k] = n(x) if isinstance(x, int) else x
    assert int(tests['check_files']) == len(tables) and pidx['progress']['verified'] == kinds.get('own', 0) + kinds.get('old', 0)

    def render(total):
        v['total_bytes'], v['total_mb'] = n(total), f'{total / 1e6:.0f}'
        out = re.sub(r'\{\{([^}]+)\}\}', lambda m: v[m.group(1)], tpl)
        return out
    total = sum(size.values()) + sums_len
    for _ in range(10):
        text = render(total)
        new_total = sum(size.values()) + sums_len + len(text.encode('utf-8'))
        if new_total == total:
            break
        total = new_total
    else:
        raise SystemExit('total size did not settle')
    (bundle / 'README_KO.md').write_text(text, encoding='utf-8')
    if (HERE / 'PORTING_KO.template.md').exists():
        (HERE / 'PORTING_KO.md').write_text(text, encoding='utf-8')
    listed = sorted(others + ['README_KO.md'])
    (bundle / 'SHA256SUMS.txt').write_text(''.join(f'{sha(bundle / f)}  {f}\n' for f in listed), encoding='utf-8')
    real = sum((bundle / f).stat().st_size for f in listed) + (bundle / 'SHA256SUMS.txt').stat().st_size
    assert real == total, (real, total)
    print(json.dumps({'files': nfiles, 'bytes': total, 'largest': [big, size[big]]}))


def write_zip(bundle, path, names):
    with zipfile.ZipFile(path, 'w') as z:
        for f in sorted(names):
            zi = zipfile.ZipInfo(f'{ROOT}/{f}', date_time=STAMP)
            zi.create_system = 3
            zi.external_attr = 0o100644 << 16
            zi.compress_type = zipfile.ZIP_DEFLATED
            data = names[f] if isinstance(names[f], bytes) else (bundle / f).read_bytes()
            z.writestr(zi, data, compresslevel=9)


def make_zip(bundle, zpath, o):
    listed = read_sums(bundle / 'SHA256SUMS.txt')
    bad = [f for f, h in listed.items() if not (bundle / f).is_file() or sha(bundle / f) != h]
    if bad:
        raise SystemExit(f'differs from SHA256SUMS.txt: {len(bad)} {bad[:5]}')
    names = {f: None for f in list(listed) + ['SHA256SUMS.txt']}
    write_zip(bundle, zpath, names)
    sizes = {f: (bundle / f).stat().st_size for f in names}
    res = {'files': len(names), 'bytes': sum(sizes.values()), 'zip': zpath.name, 'zip_bytes': zpath.stat().st_size, 'zip_sha256': sha(zpath)}
    if '--base-sums' in o:
        base = read_sums(o['--base-sums'])
        added = sorted(f for f in listed if f not in base)
        changed = sorted(f for f in listed if f in base and base[f] != listed[f])
        removed = sorted(f for f in base if f not in listed)
        note = ['이 ZIP은 이전 묶음에서 바뀐 파일만 담은 갱신본입니다. 이전 묶음 폴더 위에 풀어 덮어쓰면 됩니다.',
                f'더한 파일 {len(added)}개, 바뀐 파일 {len(changed)}개, 지울 파일 {len(removed)}개 (SHA256SUMS.txt 제외).',
                '지울 파일이 있으면 풀기 전에 이전 폴더에서 지워 주세요. 다 끝나면 sha256sum -c SHA256SUMS.txt 로 확인합니다.', '']
        for title, fs in (('[더한 파일]', added), ('[바뀐 파일]', changed), ('[지울 파일]', removed)):
            note += [title] + (fs or ['(없음)']) + ['']
        upd = {f: None for f in added + changed + ['SHA256SUMS.txt']}
        upd['UPDATE_KO.txt'] = '\n'.join(note).encode('utf-8')
        upath = Path(o['--update-zip'])
        write_zip(bundle, upath, upd)
        res.update(update_zip=upath.name, update_bytes=upath.stat().st_size, update_sha256=sha(upath),
                   added=len(added), changed=len(changed), removed=len(removed))
    print(json.dumps(res, ensure_ascii=False))


def main():
    cmd, bundle = sys.argv[1], Path(sys.argv[2])
    if cmd == 'docs':
        docs(bundle, opts(sys.argv[3:]))
    elif cmd == 'zip':
        make_zip(bundle, Path(sys.argv[3]), opts(sys.argv[4:]))
    else:
        raise SystemExit(__doc__)


if __name__ == '__main__':
    main()
