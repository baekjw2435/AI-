#!/usr/bin/env python3
"""3-ply answers (gadget.py) against exhaustive search on small random dictionaries (2026-11-07).

For every position (raw words and canonical form): gadget.find with middle vertices allowed; every strategy
it returns must pass gadget.check and the position must be a loss for the player to move (exhaustive
search). With middle vertices switched off, gadget.find must agree with find_pairing.find (same model).
Reports how many losses need a middle vertex (3-ply answer) beyond plain pairing.
usage: test_gadget.py [DICTIONARIES] [SEED] [MIN_WORDS] [MAX_WORDS]
"""
import json
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[0] / 'verifier_v3'))
from verify_v3 import ModelV3  # noqa: E402
import find_pairing  # noqa: E402
import gadget  # noqa: E402
from test_pairing import exhaustive, positions, random_dictionary  # noqa: E402


def main():
    nd = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    rng = random.Random(int(sys.argv[2]) if len(sys.argv) > 2 else 21)
    lo = int(sys.argv[3]) if len(sys.argv) > 3 else 8
    hi = int(sys.argv[4]) if len(sys.argv) > 4 else 16
    st = dict(cases=0, losses_core=0, pairing=0, gadget=0, gadget_needs_middle=0, agree_without_middle=0)
    for _ in range(nd):
        words = random_dictionary(rng, lo, hi)
        model = ModelV3(('\n'.join(words) + '\n').encode('utf-8'), 0)
        win, idx = exhaustive(tuple(words))
        for pos in positions(rng, words):
            received = pos['history'][-1][-1] if pos['history'] else pos['initial_syllable']
            lose = not win(received, sum(1 << idx[w] for w in pos['history']))
            current, raw, _ = model.position(pos)
            canon, static = model.normalize(current, raw)
            for mode, counts in (('raw', raw), ('canonical', canon)):
                if mode == 'canonical' and static != -1:
                    continue
                st['cases'] += 1
                if mode == 'canonical' and lose:
                    st['losses_core'] += 1
                p = find_pairing.find(model, current, counts, seconds=10)
                g0 = gadget.find(model, current, counts, seconds=10, allow_middle=False)
                assert p['status'] in ('found', 'none') and g0['status'] in ('found', 'none')
                assert (p['status'] == 'found') == (g0['status'] == 'found'), f'model mismatch without middle: {words} {pos} {mode}'
                st['agree_without_middle'] += 1
                g = gadget.find(model, current, counts, seconds=10, allow_middle=True)
                assert g['status'] in ('found', 'none'), g
                if g['status'] == 'found':
                    gadget.check(model, current, counts, g['S'], g['M'], g['twoway'], g['oneway'], g['entries'], g['replies'])
                    assert lose, f'3-ply strategy for a WINNING position: {words} {pos} {mode} {g}'
                    if mode == 'canonical':
                        st['gadget'] += 1
                        st['pairing'] += p['status'] == 'found'
                        st['gadget_needs_middle'] += p['status'] != 'found'
                else:
                    assert p['status'] != 'found', 'pairing found but the extended model found nothing'
    print(json.dumps(st))
    print('all checks passed')


if __name__ == '__main__':
    main()
