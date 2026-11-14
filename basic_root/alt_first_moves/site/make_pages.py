#!/usr/bin/env python3
"""Assemble the publishable parts of the presentation-word map ('제시 단어 수순 지도').

usage: make_pages.py WORK OUT [--parts-json PARTS.json] [--max-mb 225] [--max-files 470]
  WORK  build_site_tables.py's folder (items.json, rec/)
  OUT   OUT/part<k>/ = one artifact each: index.html, site-engine.js, model.json, manifest.json, pindex.json, t/<book>/NN.wasm
  PARTS.json (optional): {"main": URL, "parts": [URL, ...]} - the artifact addresses, once known (first build: leave out)

Positions are grouped by the presented syllable t (site vertex) and parts are filled in syllable order. Every part
carries the same pindex.json: all 497 positions of this study with their verdict and where their line can be seen
(this part, another part, the existing route map for the earlier study's proofs, or verdict only / undecided).
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ALT = HERE.parent
REPO = ALT.parents[1]
SITE = REPO / 'basic_root' / 'route-site'
sys.path.insert(0, str(HERE))
import site_model  # noqa: E402
from site_books import book_id  # noqa: E402

MAIN_URL = 'https://claude.ai/artifact/JCQ7dShxzrUdjhbxyNJPmP'


def leb(n):
    out = bytearray()
    while True:
        b = n & 0x7f
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def wasm_wrap(payload, name):     # the existing site's packing (route-site/build/pack_site.py)
    body = leb(len(name)) + name + payload
    return b'\0asm\x01\0\0\0' + b'\0' + leb(len(body)) + body


def hexid(s):
    return ''.join('%04x' % ord(c) for c in s)


def main():
    work, out = Path(sys.argv[1]), Path(sys.argv[2])
    rest = sys.argv[3:]
    opt = {'--parts-json': '', '--max-mb': '225', '--max-files': '470', '--model': ''}
    opt.update({rest[i]: rest[i + 1] for i in range(0, len(rest), 2)})
    model_json = Path(opt['--model'])
    model = json.loads(model_json.read_text(encoding='utf-8'))
    sm = site_model.SiteMap(model)
    items = json.loads((work / 'items.json').read_text(encoding='utf-8'))
    by_id = {it['id']: it for it in items}
    doc = json.loads((ALT / 'targets.json').read_text(encoding='utf-8'))
    summ = json.loads((ALT / 'results' / 'summary.json').read_text(encoding='utf-8'))
    main_cat = json.loads((Path(opt['--model']).parent / 'catalog.json').read_text(encoding='utf-8'))
    fresh = {e['start']: e for e in main_cat['entries'] if e['kind'] == 'fresh'}
    names = model['syllables']
    # every position of the study
    groups = {}
    for t in doc['targets']:
        cur, _ = sm.root({'initial_syllable': t['syllable'], 'history': [t['words'][0]]})
        tv = names[cur]
        dec = next((e for e in summ.get(t['id'], []) if e['decided']), None)
        it = by_id.get(t['id'])
        words = list(t['words'])
        rec = {'id': t['id'], 'start': t['syllable'], 'words': words}
        if it:
            w = it['history'][0]                       # the word the certificate was verified with comes first
            rec['words'] = [w] + [x for x in words if x != w]
            rec.update(status=it['result'], where='book', book=book_id(it['start'], it['history']),
                       proof={'nodes': it['nodes'], 'sha256': it['proof_sha256'], 'certificate': it['certificate'], 'source': it['source']})
        elif t['existing']['evidence'] == 'verified':
            st = 'W' if t['existing']['verdict'] == 'lose' else 'L'
            e = fresh.get(t['syllable']) or next(x for x in main_cat['entries'] if x['kind'] == 'fresh' and x['syllable'] == names[sm.root({'initial_syllable': t['syllable'], 'history': []})[0]])
            p = e['start']
            c0, _ = sm.root({'initial_syllable': p, 'history': []})
            legal = sorted(w for g in model['outgoing'][c0] for w in model['words'][g])
            rec.update(status=st, where='main', mainHash='#e' + hexid(e['id']) + '-' + str(legal.index(words[0])))
        elif dec:
            rec.update(status='W' if dec['first_move'] == 'lose' else 'L', where='record')
        else:
            rec.update(status='open', where='open')
        groups.setdefault(tv, []).append(rec)
    order = sorted(groups)                              # syllable order
    for tv in order:
        groups[tv].sort(key=lambda r: r['words'][0])
    # parts
    est = lambda tv: sum(by_id[r['id']]['record_count'] * 4.0 for r in groups[tv] if r['where'] == 'book')
    files_est = lambda tv: sum(1 + by_id[r['id']]['record_count'] // 400000 for r in groups[tv] if r['where'] == 'book')
    parts, cur_p, mb, nf = [], [], 0.0, 0
    for tv in order:
        b, f = est(tv) / 1e6, files_est(tv)
        if cur_p and (mb + b > float(opt['--max-mb']) or nf + f > int(opt['--max-files'])):
            parts.append(cur_p); cur_p, mb, nf = [], 0.0, 0
        cur_p.append(tv); mb += b; nf += f
    parts.append(cur_p)
    urls = json.loads(Path(opt['--parts-json']).read_text(encoding='utf-8')) if opt['--parts-json'] else {'main': MAIN_URL, 'parts': [''] * len(parts)}
    if len(urls['parts']) < len(parts):
        urls['parts'] += [''] * (len(parts) - len(urls['parts']))
    part_of = {tv: k for k, ps in enumerate(parts) for tv in ps}
    pnames = [f'{ps[0]}~{ps[-1]}' for ps in parts]
    head = (HERE / 'presentation_head.html').read_text(encoding='utf-8')
    style = (HERE / 'style.css.part').read_text(encoding='utf-8')
    body = (HERE / 'presentation_body.html').read_text(encoding='utf-8')
    decided = sum(1 for tv in groups for r in groups[tv] if r['status'] != 'open')
    if out.exists():
        shutil.rmtree(out)
    summary = []
    for k, ps in enumerate(parts):
        d = out / f'part{k}'
        (d / 't').mkdir(parents=True)
        sel = [by_id[r['id']] for tv in ps for r in groups[tv] if r['where'] == 'book']
        (d.parent / f'items{k}.json').write_text(json.dumps(sel, ensure_ascii=False), encoding='utf-8')
        r = subprocess.run([sys.executable, str(HERE / 'site_books.py'), str(d / '_bin'), str(d.parent / f'items{k}.json')],
                           capture_output=True, text=True)
        if r.returncode:
            sys.exit(r.stderr[-800:])
        man = json.loads((d / '_bin' / 'manifest.json').read_text(encoding='utf-8'))
        for b in man['books']:
            for f in b['files']:
                blob = (d / '_bin' / f['path']).read_bytes()
                f['path'] = f['path'][:-4] + '.wasm'
                (d / f['path']).parent.mkdir(parents=True, exist_ok=True)
                (d / f['path']).write_bytes(wasm_wrap(blob, b'rsb1'))
        man['encoding'] = 'wasm-custom'
        shutil.rmtree(d / '_bin')
        (d / 'manifest.json').write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding='utf-8')
        pg = []
        for tv in order:
            its = []
            for r0 in groups[tv]:
                r1 = dict(r0)
                if r1['where'] == 'book':
                    r1['where'] = 'here' if part_of[tv] == k else 'part'
                    r1['part'] = part_of[tv]
                its.append(r1)
            pg.append({'t': tv, 'items': its})
        pindex = {'format': 'presentation-map-1', 'self': k,
                  'parts': [{'name': n, 'url': u} for n, u in zip(pnames, urls['parts'])], 'main': {'url': urls['main']},
                  'progress': {'targets': len(doc['targets']), 'verified': decided, 'left': len(doc['targets']) - decided,
                               'note': '이번 추가 조사 대상(받는 쪽이 이기는 음절 64개의 첫 단어 572개, 국면 497개)의 진행률'},
                  'groups': pg}
        (d / 'pindex.json').write_text(json.dumps(pindex, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
        shutil.copy(model_json, d / 'model.json')
        shutil.copy(SITE / 'site-engine.js', d / 'site-engine.js')
        (d / 'index.html').write_text(head.replace('<title>제시 단어 수순 지도</title>', f'<title>제시 단어 수순 지도 {pnames[k]}</title>') + '<style>\n' + style.split('<style>', 1)[-1].rsplit('</style>', 1)[0] + '</style>\n' + body, encoding='utf-8')
        nfiles = sum(1 for _ in d.rglob('*') if _.is_file())
        size = sum(f.stat().st_size for f in d.rglob('*') if f.is_file())
        summary.append({'part': k, 'name': pnames[k], 'syllables': len(ps), 'books': len(man['books']), 'entries': man['total_entries'],
                        'files': nfiles, 'mb': round(size / 1e6, 1)})
        print(json.dumps(summary[-1], ensure_ascii=False), flush=True)
    (out / 'parts.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
