#!/usr/bin/env python3
"""Soundness test of the usage cap ('쓰일 수 없는 단어 지우기') against the plain grouped game with NO reduction.

Cap of a group g (sources S, target t) that is not a single-source loop, at current vertex c:
    uses(g) <= min(count(g), out(t) + 1, sum_{u in S} (in(u) + [u == c]))
out(x): words usable from x (a shared word counts at each of its sources); in(x): words whose target is x.
cap_normalize: normalize(); then repeat {cap the counts of the board left at that step; normalize()} until nothing
changes; stops at the first static result (the static result is returned, not dropped).

Checks (plain = value of the grouped game without any reduction, ground truth):
  cap-once        plain(c, cap(counts)) == plain(c, counts)
  cap-normalize   static result == plain, or plain(c, reduced) == plain(c, counts)
  cap-idempotent  cap_normalize(reduced) == reduced
  cap-search      a solver that applies cap_normalize after EVERY move (as a search keyed by the capped state
                  would) gives plain's value, expanding every child (no short-circuit)
on: abstract graphs (any source sets, shared loops, multiplicities 1-4), 'trap' graphs (vertices with 1-2 words out
and many words in, where the cap bites), dictionary-shaped models (test_v3_adversarial generators), and every
state visited by the plain solver (sampled).
Mutants that must be caught: out(t) without +1; no [u == c] term; caps applied to single-source loops as if the
loop were an ordinary group from u to u counted once (out(u)+1 with the loop itself excluded).

usage: test_cap.py [N] [SEED]
"""
from functools import lru_cache
from pathlib import Path
import random
import sys

V3 = Path('/home/user/AI-/guopsaem_root/verifier_v3')
sys.path.insert(0, str(V3))
import test_v3_adversarial as adv  # noqa: E402
from verify_v3 import ModelV3  # noqa: E402


def sums(model, counts):
    n = len(model.keys)
    out, inn = [0] * n, [0] * n
    for g, c in enumerate(counts):
        if c:
            src, t = model.edges[g]
            inn[t] += c
            for u in src:
                out[u] += c
    return out, inn


def cap_once(model, cur, counts, mutant=None):
    out, inn = sums(model, counts)
    new = bytearray(counts)
    for g, c in enumerate(counts):
        if not c:
            continue
        src, t = model.edges[g]
        loop1 = len(src) == 1 and src[0] == t
        if loop1 and mutant != 'loop':
            continue
        b_out = out[t] + (0 if mutant == 'no+1' else 1)
        if loop1:                                   # mutant 'loop': the loop itself left out of out(u)
            b_out = out[t] - c + 1
        b_in = sum(inn[u] + (0 if mutant == 'nocur' else int(u == cur)) for u in src)
        new[g] = min(c, b_out, b_in)
    return bytes(new)


def cap_normalize(model, cur, counts, mutant=None):
    red, st = model.normalize(cur, counts)
    while st == -1:
        capped = cap_once(model, cur, red, mutant)
        if capped == red:
            break
        red, st = model.normalize(cur, capped)
    return red, st


class Mismatch(Exception):
    pass


def checker(model, plain, stats, mutant=None):
    @lru_cache(maxsize=None)
    def capval(cur, counts):                       # search on capped canonical states, every child expanded
        stats['nodes'] += 1
        red, st = cap_normalize(model, cur, counts, mutant)
        if st != -1:
            return bool(st)
        res = False
        for g in model.available[cur]:
            if red[g]:
                c = bytearray(red); c[g] -= 1
                if not capval(model.edges[g][1], bytes(c)):
                    res = True
        return res

    def check(cur, counts):
        truth = plain(cur, counts)
        if plain(cur, cap_once(model, cur, counts, mutant)) != truth:
            raise Mismatch('cap-once')
        red, st = cap_normalize(model, cur, counts, mutant)
        if st != -1:
            if bool(st) != truth:
                raise Mismatch('cap-normalize-static')
        else:
            if plain(cur, red) != truth:
                raise Mismatch('cap-normalize')
            if cap_normalize(model, cur, red, mutant) != (red, -1):
                raise Mismatch('cap-idempotent')
            if any(a < b for a, b in zip(cap_once(model, cur, counts, mutant), red)) and False:
                pass
        if capval(cur, counts) != truth:
            raise Mismatch('cap-search')
        stats['positions'] += 1
        if red != model.normalize(cur, counts)[0] or st != model.normalize(cur, counts)[1]:
            stats['changed_by_cap'] += 1
    return check


def trap_model(rng):
    """Abstract graph with 'trap' vertices: 1-2 words out, several multi-word groups in."""
    m = adv.abstract_model(rng)
    n = len(m.keys)
    edges = {e: c for e, c in zip(m.edges, m.full_counts)}
    trap = rng.randrange(n)
    for e in [e for e in edges if trap in e[0] and e[1] != trap]:
        if len([x for x in edges if trap in x[0]]) > 2:
            del edges[e]
    for _ in range(rng.randint(1, 3)):
        k = rng.choice((1, 1, 2))
        src = tuple(sorted(rng.sample(range(n), min(k, n))))
        edges[(src, trap)] = rng.choice((2, 3, 4))
    m2 = ModelV3.__new__(ModelV3)
    m2.keys, m2.vertex, m2.names = m.keys, m.vertex, m.names
    m2.edges = sorted(edges)
    m2.group = {e: i for i, e in enumerate(m2.edges)}
    m2.full_counts = bytes(edges[e] for e in m2.edges)
    m2.available = [[] for _ in m2.keys]
    for i, (src, _) in enumerate(m2.edges):
        for x in src:
            m2.available[x].append(i)
    m2.shared = [len(src) > 1 for src, _ in m2.edges]
    m2.pairs, m2.loops = [], []
    for i, (src, t) in enumerate(m2.edges):
        if len(src) == 1:
            if src[0] == t:
                m2.loops.append(i)
            elif src[0] < t and ((t,), src[0]) in m2.group:
                m2.pairs.append((i, m2.group[(t,), src[0]]))
    return m2


def run(n, seed, mutant=None, quiet=False):
    rng = random.Random(seed)
    stats = {'models': 0, 'positions': 0, 'nodes': 0, 'changed_by_cap': 0, 'with_shared': 0, 'with_shared_loop': 0,
             'mismatches': []}
    kinds = ['abstract', 'trap', 'dict']
    while stats['models'] < n:
        kind = kinds[stats['models'] % 3]
        if kind == 'dict':
            words = adv.gen_dictionary(rng, rng.choice(adv.KINDS))
            if not words:
                continue
            model = ModelV3(' '.join(words).encode(), 0)
        else:
            model = adv.abstract_model(rng) if kind == 'abstract' else trap_model(rng)
            if sum(model.full_counts) > 14:
                continue
        stats['models'] += 1
        stats['with_shared'] += any(len(s) > 1 for s, _ in model.edges)
        stats['with_shared_loop'] += any(len(s) > 1 and t in s for s, t in model.edges)
        plain = adv.grouped_solver(model)
        check = checker(model, plain, stats, mutant)
        try:
            for _ in range(4):
                cur = rng.randrange(len(model.keys))
                counts = bytes(c - sum(rng.random() < 0.2 for _ in range(c)) for c in model.full_counts)
                check(cur, counts)
            visited = list(plain.memo)
            for cur, counts in rng.sample(visited, min(len(visited), 30)):
                check(cur, counts)
        except Mismatch as exc:
            stats['mismatches'].append({'kind': exc.args[0], 'kind_model': kind, 'edges': model.edges,
                                        'counts': list(model.full_counts)})
            if mutant:
                break
    if not quiet:
        print({k: (v if k != 'mismatches' else v[:2]) for k, v in stats.items()}, flush=True)
    return stats


if __name__ == '__main__':
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    s = run(n, seed)
    ok = not s['mismatches']
    for mut in ('no+1', 'nocur', 'loop'):
        ms = run(n, seed + 7, mutant=mut, quiet=True)
        print('mutant', mut, 'caught' if ms['mismatches'] else 'NOT caught', ms['mismatches'][:1] and ms['mismatches'][0]['kind'])
        ok = ok and bool(ms['mismatches'])
    print('ALL OK' if ok else 'PROBLEM')
