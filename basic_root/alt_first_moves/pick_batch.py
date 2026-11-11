#!/usr/bin/env python3
"""Choose a small batch of unverified 'other first moves' from many syllables (fixed rule, no results used).

usage: pick_batch.py targets.json OUT.json [PER_SIDE=12] [SALT=alt817-pick-v1:]

Rule: the syllables of each side (tuning / final comparison) are taken in the order of the split
(sha256 of the split salt + syllable). From each syllable one target without verification evidence is
taken: the one with the smallest sha256(SALT + id). Syllables whose first moves are all verified are
skipped. PER_SIDE targets per side; names p01, p02, ... alternate tuning, final.
Relayed (Astra) records and solver-only mentions count as not verified, so they can be picked.
"""
import hashlib
import json
from pathlib import Path
import sys

SPLIT_SALT = 'alt817-split-v1:'


def h(s):
    return hashlib.sha256(s.encode('utf-8')).hexdigest()


def main():
    doc = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    per_side = int(sys.argv[3]) if len(sys.argv) > 3 else 12
    salt = sys.argv[4] if len(sys.argv) > 4 else 'alt817-pick-v1:'
    targets = doc['targets']
    syls = sorted({t['syllable'] for t in targets}, key=lambda s: h(SPLIT_SALT + s))
    side_of = {t['syllable']: t['split'] for t in targets}
    chosen = {'tune': [], 'final': []}
    for s in syls:
        side = side_of[s]
        if len(chosen[side]) >= per_side:
            continue
        pool = [t for t in targets if t['syllable'] == s and t['existing']['evidence'] != 'verified']
        if not pool:
            continue
        chosen[side].append(min(pool, key=lambda t: h(salt + t['id'])))
    picks = []
    for i in range(per_side):
        for side in ('tune', 'final'):
            if i < len(chosen[side]):
                t = chosen[side][i]
                picks.append({'name': f'p{len(picks) + 1:02d}', 'id': t['id'], 'syllable': t['syllable'], 'word': t['words'][0],
                              'words': t['words'], 'target': t['target'], 'input_sha256': t['input_sha256'],
                              'root_form': t['root_form'], 'split': t['split'], 'existing': t['existing']})
    out = {'rule': __doc__.split('Rule:')[1].strip(), 'per_side': per_side, 'salt': salt, 'picks': picks}
    Path(sys.argv[2]).write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    for p in picks:
        print(p['name'], p['split'], p['id'], '->', p['target'], p['root_form'], p['existing']['evidence'], p['existing'].get('verdict') or '')


if __name__ == '__main__':
    main()
