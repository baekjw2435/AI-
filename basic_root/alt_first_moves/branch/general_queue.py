#!/usr/bin/env python3
"""Queue of the shallowest 미확인 moves of the general route map (general_inventory.js), fixed before anything runs.

usage: general_queue.py INVENTORY.json BATCH OUT.json [--root L|W] [--main-dir DIR]
  --root L (default): syllables the receiver loses; items are the winner's 2nd moves the map does not decide.
  --root W: syllables the receiver wins; items are the receiver's 3rd moves the map does not decide.

An item is the position after the unconfirmed move, with its full history from 'the syllable received, no word used'
(e.g. 칭 received → 칭찬 → <the other side's choice>). The verdict found for an item is the verdict of that choice for
the side that made it.
Order (depends only on the inventory's counts, never on a result): syllables with fewer open moves first (ties in the
map's order), then the lines in the map's order, then the moves in the map's order. So whole positions are completed
early.
Hint per item, as branch_queue.py: replay with the verified source of the vertex handed over, else a table guide from
a map book with a proof of that vertex with no word used, else direct search.
"""
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
BASIC = HERE.parents[1]
sys.path.insert(0, str(BASIC.parent / 'guopsaem_root' / 'verifier_v3'))
from verify_v3 import ModelV3  # noqa: E402

WORK = Path('/home/user/AI-/.work')
MAIN_DIR = '/home/user/AI-/.work/main_map'   # the existing route map's files (model.json, manifest.json, t/...)


def main():
    inv = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    batch, out = sys.argv[2], Path(sys.argv[3])
    rest = sys.argv[4:]
    o = {'--root': 'L', '--main-dir': MAIN_DIR}
    o.update({rest[i]: rest[i + 1] for i in range(0, len(rest), 2)})
    m = ModelV3((BASIC / 'words_817.txt').read_bytes(), 817)
    man = json.loads((Path(o['--main-dir']) / 'manifest.json').read_text(encoding='utf-8'))
    books = {}
    for b in man['books']:
        for p in b['proofs']:
            if not p['history']:
                books.setdefault(p['start'], (b['id'], p['result_for_player_to_move'], p['id']))
    rows = [(i, r) for i, r in enumerate(inv) if r['root'] == o['--root']]
    rows.sort(key=lambda x: (x[1]['open'], x[0]))
    items, places = [], []
    for _, r in rows:
        for pl in r['places']:
            if not pl['open']:
                continue
            places.append({'syllable': r['syllable'], 'line': pl['line'], 'to_move': pl['toMove'], 'map_best': pl['best'], 'open': pl['open']})
            for ws in pl['open']:
                pos = {'initial_syllable': r['syllable'], 'history': pl['line'] + [ws[0]]}
                cur, counts, _ = m.position(pos)          # raises if the history is not legal
                v = m.names[cur]
                it = {'name': f"{batch.replace('general', 'g')}_{len(items) + 1:03d}", 'word': ws[0], 'group_words': ws, 'position': pos,
                      'parent': r['syllable'] + ':' + '→'.join(pl['line']), 'hands_over': v}
                tg = WORK / 'table_guide' / v / 'run.json'
                if (WORK / 'sources' / v / 'prep.json').exists():
                    it.update(method='replay', source=v, source_path=str(WORK / 'sources' / v / 'proof.v4.gz'))
                elif tg.exists() and json.loads(tg.read_text(encoding='utf-8')).get('accepted'):
                    it.update(method='replay', source=v, source_path=str(WORK / 'table_guide' / v / 'proof.v4.gz'))
                elif v in books:
                    bid, res, pid = books[v]
                    it.update(method='table', guide_book=bid, guide_proof=pid, expect=res, guide=str(WORK / 'table_guide' / f'book_{bid}'))
                else:
                    it.update(method='direct')
                items.append(it)
    doc = {'batch': batch, 'created': '2026-11-19', 'kind': 'general route map, shallowest 미확인 moves', 'sides': ['받은 쪽', '넘긴 쪽'],
           'root': o['--root'], 'base_position': {'initial_syllable': '(각 음절)', 'history': []},
           'question': ('받으면 지는 음절에서 받은 쪽의 각 첫 수 뒤, 이기는 쪽(상대)이 지도의 증명과 다르게 둘 수 있는 2번째 수의 승패'
                        if o['--root'] == 'L' else '받으면 이기는 음절에서 증명의 첫 수와 상대의 응수 뒤, 받은 쪽의 다른 3번째 수의 승패'),
           'places': places, 'cases': items}
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    from collections import Counter
    print(len(items), len(places), dict(Counter(i['method'] for i in items)))


if __name__ == '__main__':
    main()
