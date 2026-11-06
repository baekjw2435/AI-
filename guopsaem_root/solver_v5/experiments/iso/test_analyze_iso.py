#!/usr/bin/env python3
"""Checks of analyze_iso.py on random small structures (2026-11-06).

1. iso_form is a canonical form: equal for a random renaming of the same structure, and equal for two
   structures exactly when a brute-force search over all renamings finds an isomorphism.
2. ext_reduce keeps the game value: a static answer equals the exhaustive game value, and a reduced
   core has the same exhaustive value as the original structure.
3. (added after review) larger structures (6-7 vertices): renamed copies give the same form, copies with one
   change (a count, a target, a source) agree with brute force; and symmetric families where colour
   refinement alone cannot finish and individualization decides (directed and two-way cycles, disjoint
   copies, complete patterns, K3,3 against the prism, shared groups over symmetric pairs).
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
    big, sym = test_larger(rng, max(50, trials // 20)), test_symmetric(rng)
    print(f'larger structures: {big} renamed/changed pairs; symmetric families: {sym} checks: all passed')


def two_way(edges, c=1):
    g = {}
    for u, v in edges:
        g[(frozenset([u]), v)] = c
        g[(frozenset([v]), u)] = c
    return g


def families():
    """(name, cur, groups) structures with many automorphisms."""
    out = []
    for n in (3, 4, 5, 6):
        out.append((f'directed C{n}', 0, {(frozenset([i]), (i + 1) % n): 1 for i in range(n)}))
        out.append((f'two-way C{n}', 0, two_way([(i, (i + 1) % n) for i in range(n)])))
    out.append(('C6', 0, two_way([(i, (i + 1) % 6) for i in range(6)])))
    out.append(('2 x C3', 0, two_way([(0, 1), (1, 2), (2, 0), (3, 4), (4, 5), (5, 3)])))
    out.append(('K3,3', 0, two_way([(a, b) for a in (0, 1, 2) for b in (3, 4, 5)])))
    out.append(('prism', 0, two_way([(0, 1), (1, 2), (2, 0), (3, 4), (4, 5), (5, 3), (0, 3), (1, 4), (2, 5)])))
    out.append(('K4', 0, two_way([(a, b) for a in range(4) for b in range(a + 1, 4)])))
    out.append(('K4 minus edge', 0, two_way([(0, 1), (0, 2), (0, 3), (1, 2), (1, 3)])))
    star = {(frozenset([0]), i): 1 for i in range(1, 5)}
    star.update({(frozenset([i]), 0): 1 for i in range(1, 5)})
    out.append(('star 4', 0, star))
    sh = {(frozenset([0, 1]), 2): 2, (frozenset([2]), 0): 1, (frozenset([2]), 1): 1, (frozenset([0, 1]), 3): 1, (frozenset([3]), 0): 1}
    out.append(('shared over symmetric pair', 0, sh))
    out.append(('shared over symmetric pair, other cur', 2, dict(sh)))
    sh2 = dict(sh); sh2[(frozenset([3]), 1)] = 1
    out.append(('shared, extra word', 0, sh2))
    loops = {(frozenset([i]), i): 1 for i in range(4)}
    loops.update(two_way([(0, 1), (2, 3), (1, 2)]))
    out.append(('path with loops', 1, loops))
    return out


def test_symmetric(rng):
    fam = families()
    checks = 0
    for name, cur, g in fam:
        f0 = iso_form(cur, g)
        verts = sorted({cur} | {v for (S, t) in g for v in S} | {t for (S, t) in g})
        for _ in range(12):
            perm = dict(zip(verts, rng.sample(range(20, 20 + len(verts)), len(verts))))
            c2, g2 = rename(cur, g, perm)
            assert iso_form(c2, g2) == f0, f'renaming changed the form of {name}'
            checks += 1
    for (n1, c1, g1), (n2, c2, g2) in itertools.combinations(fam, 2):
        same = iso_form(c1, g1) == iso_form(c2, g2)
        assert same == brute_iso((c1, g1), (c2, g2)), f'form disagrees with brute force: {n1} / {n2}'
        checks += 1
    return checks


def random_big(rng):
    n = rng.randint(6, 7)
    g = {}
    for _ in range(rng.randint(n, 2 * n + 2)):
        k = 1 if rng.random() < 0.75 else rng.randint(2, 3)
        S = frozenset(rng.sample(range(n), k))
        t = rng.randrange(n)
        g[(S, t)] = g.get((S, t), 0) + rng.randint(1, 2)
    return rng.randrange(n), g


def test_larger(rng, trials):
    done = 0
    for _ in range(trials):
        cur, g = random_big(rng)
        verts = sorted({cur} | {v for (S, t) in g for v in S} | {t for (S, t) in g})
        perm = dict(zip(verts, rng.sample(range(30, 30 + len(verts)), len(verts))))
        c2, g2 = rename(cur, g, perm)
        assert iso_form(cur, g) == iso_form(c2, g2), 'renaming changed the form (large)'
        # one change: a count, a target, or a source; then compare with brute force
        e = rng.choice(sorted(g, key=lambda e: (sorted(e[0]), e[1])))
        h = dict(g)
        kind = rng.randrange(3)
        if kind == 0:
            h[e] += 1
        else:
            c = h.pop(e)
            S, t = e
            if kind == 1:
                e2 = (S, rng.choice([v for v in verts if v != t] or [t]))
            else:
                e2 = (frozenset(set(S) ^ {rng.choice(verts)}) or S, t)
            h[e2] = h.get(e2, 0) + c
        hc, hg = rename(cur, h, perm)
        same = iso_form(cur, g) == iso_form(hc, hg)
        assert same == brute_iso((cur, g), (hc, hg)), 'form disagrees with brute force (large, changed)'
        done += 1
    return done


if __name__ == '__main__':
    main()
