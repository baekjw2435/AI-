#!/usr/bin/env python3
"""Winning-move tables for 'w로 t 제시' positions, from the archived, verified v4 certificates.

usage: build_site_tables.py MODEL_JSON WORK [--jobs 3] [--only 격,맹] [--staging DIR]
  MODEL_JSON  the route site's model.json (route-site-1)
  WORK        work folder: WORK/model.txt, WORK/rec/<book>.bin, WORK/items.json, WORK/items_skipped.json
Then: site_books.py OUT WORK/items.json, and check_tables.js OUT ENGINE.

Every position with an accepted certificate in results/*/archive/INDEX.json gets one item, from the first batch that
accepted it (batches in order: replay1..N, then direct1..N). The certificate file is taken from the repository
(results/<batch>/archive/certs/), the release staging folder, or downloaded from its release address; its SHA-256 must
equal the archived one. The position is the archived pos.json of that case (its own history, nothing else).
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parent / 'results'
sys.path.insert(0, str(HERE))
import site_model  # noqa: E402
from site_books import book_id  # noqa: E402

CERT2SITE = Path(os.environ.get('CERT2SITE', '/home/user/AI-/.work/measure/cert2site'))   # g++ -O2 -std=c++17 -o ... cert2site.cpp -lz


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def batches():
    def order(p):
        kind = 0 if p.name.startswith('replay') else 1
        return kind, int(re.sub(r'\D', '', p.name) or 0)
    return sorted((p for p in RESULTS.iterdir() if (p / 'archive' / 'INDEX.json').exists()), key=order)


def find_cert(batch, e, staging, tmp):
    cands = []
    if e.get('certificate'):
        cands.append(RESULTS / batch / 'archive' / e['certificate'])
    if e.get('release_tag'):
        cands.append(Path(staging) / e['release_tag'] / e['asset'])
    for c in cands:
        if c.exists() and sha(c) == e['proof_sha256']:
            return c
    if e.get('url'):
        dst = Path(tmp) / e['asset']
        r = subprocess.run(['curl', '-sSL', '--fail', '-o', str(dst), e['url']], capture_output=True)
        if r.returncode == 0 and sha(dst) == e['proof_sha256']:
            return dst
    return None


def main():
    model_json, work = sys.argv[1], Path(sys.argv[2])
    rest = sys.argv[3:]
    opt = {'--jobs': '3', '--only': '', '--staging': '/home/user/AI-/.work/release_staging'}
    opt.update({rest[i]: rest[i + 1] for i in range(0, len(rest), 2)})
    only = set(opt['--only'].split(',')) if opt['--only'] else None
    work.mkdir(parents=True, exist_ok=True); (work / 'rec').mkdir(exist_ok=True)
    sm = site_model.load(model_json)
    sm.write_numeric(work / 'model.txt')
    names = json.loads(Path(model_json).read_text(encoding='utf-8'))['syllables']
    todo, seen, skipped = [], set(), []
    for b in batches():
        idx = json.loads((b / 'archive' / 'INDEX.json').read_text(encoding='utf-8'))
        for e in idx['cases']:
            if not e.get('accepted') or e['id'] in seen:
                continue
            pos = json.loads((b / 'archive' / e['case'] / 'pos.json').read_text(encoding='utf-8'))
            if hashlib.sha256((b / 'archive' / e['case'] / 'pos.json').read_bytes()).hexdigest() != e['position_sha256']:
                sys.exit(f'{b.name}/{e["case"]}: pos.json differs from the archived hash')
            cur, counts = sm.root(pos)
            t = names[cur]
            if only and t not in only:
                continue
            seen.add(e['id'])
            todo.append((b.name, e, pos, cur, counts, t))
    tmp = tempfile.mkdtemp(dir=work)
    items = []

    def one(job):
        bname, e, pos, cur, counts, t = job
        bid = book_id(pos['initial_syllable'], pos['history'])
        out = work / 'rec' / f'{bid}.bin'
        info_path = work / 'rec' / f'{bid}.json'
        if info_path.exists() and out.exists():
            info = json.loads(info_path.read_text(encoding='utf-8'))
        else:
            cert = find_cert(bname, e, opt['--staging'], tmp)
            if cert is None:
                return None, (e['id'], 'certificate not found with the archived sha256')
            root = work / 'rec' / f'{bid}.root'
            root.write_text(f'{cur} ' + ' '.join(map(str, counts)) + '\n', encoding='utf-8')
            r = subprocess.run([str(CERT2SITE), str(work / 'model.txt'), str(cert), str(root), str(out) + '.part'],
                               capture_output=True, text=True)
            if r.returncode != 0:
                return None, (e['id'], r.stderr.strip()[-300:])
            info = json.loads(r.stdout)
            Path(str(out) + '.part').replace(out)
            info_path.write_text(json.dumps(info) + '\n', encoding='utf-8')
            root.unlink()
            if str(cert).startswith(tmp):
                cert.unlink()
        want = 'W' if e['first_move'] == 'lose' else 'L'      # the first word loses = the side to move (t's receiver) wins
        if info['root_result'] != want or info['cert_nodes'] != e['proof_nodes']:
            return None, (e['id'], f'certificate root {info["root_result"]} / nodes {info["cert_nodes"]} do not match the archive')
        return {'id': e['id'], 'start': pos['initial_syllable'], 'history': pos['history'], 'syllable': t, 'result': want,
                'nodes': e['proof_nodes'], 'proof_sha256': e['proof_sha256'], 'records': str(out),
                'source': f'basic_root/alt_first_moves/results/{bname}/archive/INDEX.json ({e["case"]})',
                'batch': bname, 'case': e['case'], 'certificate': e.get('url') or f'results/{bname}/archive/{e["certificate"]}',
                'record_count': info['records']}, None

    with ThreadPoolExecutor(int(opt['--jobs'])) as ex:
        for res, err in ex.map(one, todo):
            if res:
                items.append(res)
                print(res['id'], res['record_count'], flush=True)
            else:
                skipped.append(err)
                print('SKIP', err, flush=True)
    items.sort(key=lambda x: (x['syllable'], x['history']))
    (work / 'items.json').write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding='utf-8')
    (work / 'items_skipped.json').write_text(json.dumps(skipped, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps({'items': len(items), 'skipped': len(skipped), 'records': sum(i['record_count'] for i in items)}))


if __name__ == '__main__':
    main()
