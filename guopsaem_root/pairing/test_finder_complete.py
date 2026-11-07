#!/usr/bin/env python3
"""Is the finder's 'none' right? Brute force on tiny dictionaries (2026-11-07).

For random dictionaries of 4-8 words (the syllables of test_pairing.py) and positions after 0-2 words,
both modes (raw and canonical): try EVERY vertex set S that contains the current vertex and EVERY set of
disjoint word pairs, and decide by brute force whether a valid pairing exists. Then compare with
find_pairing.find(): it must report 'found' exactly when one exists. Every brute-force pairing is also
given to verify_pairing.check_groups, which must accept it.
usage: test_finder_complete.py [DICTIONARIES] [SEED]
"""
from itertools import combinations
import json
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[0] / 'verifier_v3'))
from verify_v3 import ModelV3, VerificationError  # noqa: E402
import find_pairing  # noqa: E402
import verify_pairing  # noqa: E402
from test_pairing import positions, random_dictionary  # noqa: E402


def brute(model, current, counts):
    """Return (S, group_pairs) of some valid pairing, or None. Word units: count copies per group."""
    edges = model.edges
    n = len(model.keys)
    others = [v for v in range(n) if v != current]
    units = [g for g, c in enumerate(counts) for _ in range(c)]
    for k in range(len(others) + 1):
        for extra in combinations(others, k):
            S = {current, *extra}
            playable = [any(s in S for s in edges[g][0]) for g in range(len(edges))]

            def ok(x, y):
                return edges[x][1] in edges[y][0] and edges[y][1] in S

            def valid(a, b):
                return (not playable[a] or ok(a, b)) and (not playable[b] or ok(b, a))
            used = [False] * len(units)

            def rec(pairs):
                i = next((i for i, g in enumerate(units) if not used[i] and playable[g]), None)
                if i is None:
                    return list(pairs)
                used[i] = True
                for j in range(len(units)):
                    if not used[j] and valid(units[i], units[j]):
                        used[j] = True
                        r = rec(pairs + [(units[i], units[j])])
                        if r is not None:
                            return r
                        used[j] = False
                used[i] = False
                return None
            r = rec([])
            if r is not None:
                return S, r
    return None


def main():
    ndict = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    rng = random.Random(int(sys.argv[2]) if len(sys.argv) > 2 else 11)
    st = dict(cases=0, exists=0, finder_found=0, mismatches=0, brute_rejected=0)
    for _ in range(ndict):
        words = random_dictionary(rng, 4, 8)
        dbytes = ('\n'.join(words) + '\n').encode('utf-8')
        model = ModelV3(dbytes, 0)
        for pos in positions(rng, words):
            pos['history'] = pos['history'][:2]
            current, raw, _used = model.position(pos)
            canon, static = model.normalize(current, raw)
            for mode, counts in (('raw', raw), ('canonical', canon)):
                if mode == 'canonical' and static != -1:
                    continue
                st['cases'] += 1
                b = brute(model, current, counts)
                f = find_pairing.find(model, current, counts, seconds=10)
                assert f['status'] in ('found', 'none'), f
                st['exists'] += b is not None
                st['finder_found'] += f['status'] == 'found'
                if (b is not None) != (f['status'] == 'found'):
                    st['mismatches'] += 1
                    print('MISMATCH', mode, words, pos, 'brute', b, 'finder', f['status'])
                if b is not None:
                    try:
                        verify_pairing.check_groups(model, current, counts, b[0], b[1])
                    except VerificationError as e:
                        st['brute_rejected'] += 1
                        print('BRUTE PAIRING REJECTED', mode, words, pos, b, e)
    print(json.dumps(st))
    assert st['mismatches'] == 0 and st['brute_rejected'] == 0
    print('all checks passed')


if __name__ == '__main__':
    main()
