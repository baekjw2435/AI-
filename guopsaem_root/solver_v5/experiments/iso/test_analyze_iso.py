#!/usr/bin/env python3
"""Checks of analyze_iso.py on random small structures (2026-11-06).

1. iso_form is a canonical form: equal for a random renaming of the same structure, and equal for two
   structures exactly when a brute-force search over all renamings finds an isomorphism.
2. ext_reduce keeps the game value: a static answer equals the exhaustive game value, and a reduced
   core has the same exhaustive value as the original structure.
usage: test_analyze_iso.py [TRIALS] [SEED]
"""
import itertools
import random
import sys
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_iso import ext_reduce, iso_form, restrict  # noqa: E402


def value(cur, groups):
    """Exhaustive value for the player to move (1 = W, 0 = L)."""
    keys = sorted(groups, key=lambda e: (sorted(e[0]), e[1]))
    idx = {e: i for i, e in enumerate(keys)}

    @lru_cache(maxsize=None)
    def win(v, counts):
        for i, (S, t) in enumerate(keys):
            if counts[i] and v in S:
                c = list(counts); c[i] -= 1
                if not win(t, tuple(c)):
                    return True
        return False
    return 1 if win(cur, tuple(groups[e] for e in keys)) else 0


def random_structure(rng):
    n = rng.randint(1, 5)
    groups = {}
    for _ in range(rng.randint(1, 7)):
        k = 1 if n == 1 or rng.random() < 0.7 else rng.randint(2, min(3, n))
        S = frozenset(rng.sample(range(n), min(k, n)))
        t = rng.randrange(n)
        groups[(S, t)] = groups.get((S, t), 0) + rng.randint(1, 3)
    return rng.randrange(n), groups


def rename(cur, groups, perm):
    return perm[cur], {(frozenset(perm[s] for s in S), perm[t]): c for (S, t), c in groups.items()}


def brute_iso(a, b):
    (ca, ga), (cb, gb) = a, b
    va = sorted({ca} | {v for (S, t) in ga for v in S} | {t for (S, t) in ga})
    vb = sorted({cb} | {v for (S, t) in gb for v in S} | {t for (S, t) in gb})
    if len(va) != len(vb) or len(ga) != len(gb):
        return False
    for p in itertools.permutations(vb):
        m = dict(zip(va, p))
        if m[ca] == cb and rename(ca, ga, m) == (cb, gb):
            return True
    return False


def main():
    trials = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
    rng = random.Random(int(sys.argv[2]) if len(sys.argv) > 2 else 1)
    iso_ok = pair_checks = red_ok = static_hits = 0
    for _ in range(trials):
        cur, g = random_structure(rng)
        g, _seen = restrict(cur, g)
        if not g:
            continue
        verts = sorted({cur} | {v for (S, t) in g for v in S} | {t for (S, t) in g})
        perm = dict(zip(verts, rng.sample(range(10, 10 + len(verts)), len(verts))))
        c2, g2 = rename(cur, g, perm)
        assert iso_form(cur, g) == iso_form(c2, g2), 'renaming changed the form'
        iso_ok += 1
        cur3, g3 = random_structure(rng)
        g3, _ = restrict(cur3, g3)
        if g3:
            same = iso_form(cur, g) == iso_form(cur3, g3)
            assert same == brute_iso((cur, g), (cur3, g3)), 'form disagrees with brute force'
            pair_checks += 1
        st, core = ext_reduce(cur, g)
        v = value(cur, g)
        if st != -1:
            assert st == v, f'static {st} but value {v}: {cur} {g}'
            static_hits += 1
        else:
            assert value(cur, core) == v, f'core value differs: {cur} {g} -> {core}'
        red_ok += 1
    print(f'iso renaming checks {iso_ok}, iso vs brute force {pair_checks}, reduction checks {red_ok} '
          f'(static {static_hits}): all passed')


if __name__ == '__main__':
    main()
