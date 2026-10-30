#!/usr/bin/env python3
"""Assemble the publishable route site.

usage: pack_site.py TABLE_DIR ASTRA_DIST OUT_DIR

TABLE_DIR is site_build.py's output (model.json, manifest.json, catalog.json, t/...). Artifacts serve only web media
types, so every binary table (and Astra's proof index) is written as base64 text (.txt) and the manifest paths are
rewritten to match; the page decodes them back to bytes. Prints the upload batches (each under the per-publish
limits) as JSON maps for the Artifact tool, written to OUT_DIR/../batchN.json.
"""
import base64, json, os, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.dirname(HERE)


def main():
    tables, astra, out = sys.argv[1:4]
    if os.path.exists(out):
        shutil.rmtree(out)
    os.makedirs(out + '/astra')
    for f in ('site-engine.js', 'astra-adapter.js'):
        shutil.copy(f'{SITE}/{f}', f'{out}/{f}')
    for f in ('model.json', 'catalog.json'):
        shutil.copy(f'{tables}/{f}', f'{out}/{f}')
    manifest = json.load(open(f'{tables}/manifest.json', encoding='utf-8'))
    for book in manifest['books']:
        for f in book['files']:
            src = f'{tables}/{f["path"]}'
            f['path'] = f['path'][:-4] + '.txt'
            os.makedirs(os.path.dirname(f'{out}/{f["path"]}'), exist_ok=True)
            open(f'{out}/{f["path"]}', 'wb').write(base64.b64encode(open(src, 'rb').read()))
    manifest['encoding'] = 'base64'
    json.dump(manifest, open(f'{out}/manifest.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    shutil.copy(f'{astra}/game-data.json', f'{out}/astra/game-data.json')
    shutil.copy(f'{astra}/engine.wasm', f'{out}/astra/engine.wasm')
    open(f'{out}/astra/proof-817.txt', 'wb').write(base64.b64encode(open(f'{astra}/proof-817.bin', 'rb').read()))
    small = ['site-engine.js', 'astra-adapter.js', 'model.json', 'manifest.json', 'catalog.json',
             'astra/game-data.json', 'astra/proof-817.txt', 'astra/engine.wasm']
    rest = sorted(os.path.relpath(os.path.join(d, f), out) for d, _, fs in os.walk(f'{out}/t') for f in fs)
    batches, cur = [], list(small)
    size = sum(os.path.getsize(f'{out}/{p}') for p in cur)
    for p in rest:
        s = os.path.getsize(f'{out}/{p}')
        if size + s > 58e6 or len(cur) >= 250:
            batches.append(cur); cur, size = [], 0
        cur.append(p); size += s
    batches.append(cur)
    for i, b in enumerate(batches):
        json.dump({p: p for p in b}, open(f'{out}/../batch{i}.json', 'w'))
        print(i, len(b), round(sum(os.path.getsize(f'{out}/{p}') for p in b) / 1e6, 1), 'MB')
    total = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(out) for f in fs)
    print('total', round(total / 1e6, 1), 'MB')


if __name__ == '__main__':
    main()
