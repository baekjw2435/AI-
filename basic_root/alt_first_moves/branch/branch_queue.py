#!/usr/bin/env python3
"""Fix the next level of follow-up branches as one ordered queue, from a branch summary.

usage: branch_queue.py SUMMARY.json BATCH OUT.json [--main-dir DIR]
  SUMMARY.json  branch_summary.py's summary of the level above
  BATCH         name of the new batch (e.g. branch2)
  OUT.json      the queue, written once before anything runs (the order never depends on a result)

An item is one unconfirmed choice of the winning side, with the full history of its position:
  the level above said 'the side to move wins' (root W): its other real moves (not the certificate's, not decided
    by the static rule) -> each one is an item;
  the level above said 'the side to move loses' (root L): after each of its moves, the winner's other real answers
    (not the certificate's, not static) -> each one is an item.
Order: the cases of the summary in their order, then the moves in the model's order (ModelV3.available).

The hint for each item, in this order of preference (the position itself is always the item's own history):
  replay  a verified source certificate of 'V received, no word used' for the vertex V handed over by the item's word:
          sources/V/prep.json (replay_prep.py), else table_guide/V/run.json accepted (table guide test)
  table   a book of the existing route map that holds a proof starting at V with no word used (make_guide.py builds the
          guide from it); the expected root value is that proof's result
  direct  the plain solver
"""
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
BASIC = HERE.parents[1]
sys.path.insert(0, str(BASIC.parent / 'guopsaem_root' / 'verifier_v3'))
from verify_v3 import ModelV3  # noqa: E402

WORK = Path('/home/user/AI-/.work')
MAIN_DIR = '/tmp/claude-0/-home-user-AI-/2401d150-dd76-525a-a003-834c39d611b3/scratchpad/artifact-files/8b42c88b-1088-4496-9137-10f8866f75de'


def main():
    summ = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    batch, out = sys.argv[2], Path(sys.argv[3])
    rest = sys.argv[4:]
    o = {'--main-dir': MAIN_DIR}
    o.update({rest[i]: rest[i + 1] for i in range(0, len(rest), 2)})
    m = ModelV3((BASIC / 'words_817.txt').read_bytes(), 817)
    man = json.loads((Path(o['--main-dir']) / 'manifest.json').read_text(encoding='utf-8'))
    books = {}
    for b in man['books']:
        for p in b['proofs']:
            if not p['history']:
                books.setdefault(p['start'], (b['id'], p['result_for_player_to_move'], p['id']))
    items = []
    for r in summ['cases']:
        if not r.get('accepted'):
            continue
        base = r['position']['history']
        if r['mover_result'] == 'W':
            alts = [(base, x['words']) for x in r['mover_other'] if x['class'] == 'unconfirmed']
        else:
            alts = [(base + [a['words'][0]], x) for a in r['replies'] for x in a.get('answer_alternatives', [])]
        for hist, ws in alts:
            pos = {'initial_syllable': r['position']['initial_syllable'], 'history': hist + [ws[0]]}
            cur, _, _ = m.position(pos)
            v = m.names[cur]
            it = {'name': f"{batch.replace('branch', 'b')}_{len(items) + 1:03d}", 'word': ws[0], 'group_words': ws, 'position': pos,
                  'parent': r['name'], 'hands_over': v}
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
    doc = {'batch': batch, 'from_summary': str(sys.argv[1]), 'base_position': summ.get('base_position'), 'cases': items}
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    from collections import Counter
    print(len(items), dict(Counter(i['method'] for i in items)))


if __name__ == '__main__':
    main()
