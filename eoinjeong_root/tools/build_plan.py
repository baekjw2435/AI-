#!/usr/bin/env python3
"""Write the position lists (plans) of the 어인정 621-word study.

usage:
  build_plan.py roots   OUT.jsonl            173 start syllables, empty history          (ids R001..)
  build_plan.py first   OUT.jsonl            every legal first word of every syllable    (ids F0001..)
  build_plan.py second  OUT.jsonl ROOT_RES   for every syllable whose root was ACCEPTED as L (the receiver
                                             loses): every first word, then every legal reply of the
                                             winning side                                (ids S00001..)
  build_plan.py next_w  OUT.jsonl RESULTS    deeper list only (not run): W syllables, every presenter reply
                                             after each winning first move              (ids NW00001..)
  build_plan.py next_l  OUT.jsonl RESULTS    deeper list only (not run): L syllables, every 3rd move of the
                                             receiver after each winning 2nd move      (ids NL00001..)
ROOT_RES is the res/ folder of the roots run; RESULTS is the results/ folder.  A move is legal if its first syllable is one the player
to move may use (the received syllable or its dueum alternative) and the word is still unused.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parent
sys.path.insert(0, str(REPO / 'guopsaem_root' / 'verifier_v3'))
from verify_v3 import ModelV3  # noqa: E402


def legal(m, s, history):
    cur, _, used = m.position({'initial_syllable': s, 'history': history})
    return [w for w in m.words if w[0] in m.keys[cur] and w not in used]


def main():
    kind, out = sys.argv[1], Path(sys.argv[2])
    m = ModelV3((HERE / 'words_621.txt').read_bytes(), 621)
    syls = (HERE / 'syllables_173.txt').read_text(encoding='utf-8').split()
    rows = []
    if kind == 'roots':
        for i, s in enumerate(syls, 1):
            rows.append({'id': f'R{i:03d}', 'initial_syllable': s, 'history': []})
    elif kind == 'first':
        for s in syls:
            for w in legal(m, s, []):
                rows.append({'id': f'F{len(rows) + 1:04d}', 'initial_syllable': s, 'history': [w]})
    elif kind == 'second':
        resdir = Path(sys.argv[3])
        for i, s in enumerate(syls, 1):
            r = json.loads((resdir / f'R{i:03d}.json').read_text(encoding='utf-8'))
            assert r['position'] == {'initial_syllable': s, 'history': []}
            if not (r.get('accepted') and r.get('result_for_player_to_move') == 'L'):
                continue
            for w1 in legal(m, s, []):
                for w2 in legal(m, s, [w1]):
                    rows.append({'id': f'S{len(rows) + 1:05d}', 'initial_syllable': s, 'history': [w1, w2]})
    elif kind in ('next_w', 'next_l'):
        # Deeper branches, written as lists only (not run):
        #   next_w: syllables won by the receiver: after every ACCEPTED winning first move, every reply of the presenter
        #   next_l: syllables lost by the receiver: after every ACCEPTED winning 2nd move, every 3rd move of the receiver
        base = Path(sys.argv[3])
        res = {}
        for st in ('roots', 'first', 'second'):
            for f in (base / st / 'res').glob('*.json'):
                r = json.loads(f.read_text(encoding='utf-8'))
                if r.get('accepted'):
                    res[(r['position']['initial_syllable'], tuple(r['position']['history']))] = r['result_for_player_to_move']
        for s in syls:
            if kind == 'next_w' and res.get((s, ())) == 'W':
                for w1 in legal(m, s, []):
                    if res.get((s, (w1,))) == 'L':
                        for w2 in legal(m, s, [w1]):
                            rows.append({'id': f'NW{len(rows) + 1:05d}', 'initial_syllable': s, 'history': [w1, w2]})
            if kind == 'next_l' and res.get((s, ())) == 'L':
                for w1 in legal(m, s, []):
                    for w2 in legal(m, s, [w1]):
                        if res.get((s, (w1, w2))) == 'L':
                            for w3 in legal(m, s, [w1, w2]):
                                rows.append({'id': f'NL{len(rows) + 1:05d}', 'initial_syllable': s,
                                             'history': [w1, w2, w3]})
    else:
        raise SystemExit(__doc__)
    out.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')
    print(kind, len(rows), 'positions ->', out)


if __name__ == '__main__':
    main()
