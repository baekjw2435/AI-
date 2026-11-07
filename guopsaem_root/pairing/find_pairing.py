#!/usr/bin/env python3
"""Search for a pairing-proof-v1 certificate with CP-SAT (2026-11-07). FINDING ONLY.

The solver (OR-Tools CP-SAT) only searches for a candidate strategy. The output proves nothing until
verify_pairing.py has checked it. When nothing is found (infeasible, or time ran out) that is NOT
evidence that the player to move wins: the position simply stays undecided by this method.

Model. Choose a set S of vertices (containing the current vertex) and how many word pairs to form for
each pair of word groups (a, b), such that:
  - a group is used at most its count;
  - a group that can be played from S is used exactly its count (all of its words are paired);
  - for a pair (a, b): if a can be played from S then b can be played after a and b's target is in S,
    and the same with a and b swapped.
The objective prefers a small S.
usage: find_pairing.py --dictionary D --expected-word-count N --position POS.json --mode canonical|raw
                       [--seconds T] [--out CERT.json]
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'verifier_v3'))
from verify_v3 import ModelV3  # noqa: E402

from ortools.sat.python import cp_model  # noqa: E402


def find(model, current, counts, seconds=10.0, workers=1, minimize=True, relaxed=False):
    """counts: remaining count per group (raw or canonical). Returns {'status', 'S', 'group_pairs', ...}.
    status: 'found', 'none' (CP-SAT proved there is no such pairing) or 'unknown' (time ran out).
    relaxed=True is a DIAGNOSTIC, never a proof: words playable from S may stay unpaired, and the
    objective is the smallest number of such uncovered words (reported as 'uncovered').
    Uncovered words are moves of the player to move that escape the strategy."""
    t0 = time.time()
    edges = model.edges
    live = [g for g, c in enumerate(counts) if c]
    V = {current} | {edges[g][1] for g in live}
    m = cp_model.CpModel()
    x = {v: m.NewBoolVar(f'x{v}') for v in V}
    m.Add(x[current] == 1)
    y = {}
    for g in live:
        srcs = [s for s in edges[g][0] if s in V]
        if not srcs:
            y[g] = None
            continue
        b = m.NewBoolVar(f'y{g}')
        for s in srcs:
            m.AddImplication(x[s], b)
        m.AddBoolOr([x[s] for s in srcs]).OnlyEnforceIf(b)
        y[g] = b
    usable_at = {}
    for g in live:
        for s in edges[g][0]:
            usable_at.setdefault(s, []).append(g)
    cand = set()
    for a in live:
        for b in usable_at.get(edges[a][1], []):      # b can be played after a
            cand.add((min(a, b), max(a, b)))
    use = {g: [] for g in live}
    pairvars = []
    for a, b in sorted(cand):
        if a == b:
            cap = counts[a] // 2
        else:
            cap = min(counts[a], counts[b])
        if cap <= 0:
            continue
        n = m.NewIntVar(0, cap, f'm{a}_{b}')
        z = m.NewBoolVar(f'z{a}_{b}')
        m.Add(n <= cap * z)
        m.Add(n >= z)
        for p, q in ((a, b), (b, a)):
            if y[p] is None:
                continue
            ok = edges[p][1] in edges[q][0]
            if not ok:
                m.AddBoolOr([z.Not(), y[p].Not()])
            else:
                m.AddBoolOr([z.Not(), y[p].Not(), x[edges[q][1]]])
            if a == b:
                break
        if a == b:
            use[a].append((2, n))
        else:
            use[a].append((1, n))
            use[b].append((1, n))
        pairvars.append((a, b, n))
    unc = []
    for g in live:
        total = sum(k * n for k, n in use[g]) if use[g] else 0
        m.Add(total <= counts[g])
        if y[g] is not None:
            if relaxed:
                u = m.NewIntVar(0, counts[g], f'u{g}')
                m.Add(total + u >= counts[g]).OnlyEnforceIf(y[g])
                unc.append(u)
            else:
                m.Add(total >= counts[g]).OnlyEnforceIf(y[g])
    if relaxed:
        m.Minimize(1000 * sum(unc) + sum(x.values()))
    elif minimize:
        m.Minimize(sum(x.values()))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(seconds)
    solver.parameters.num_search_workers = int(workers)
    st = solver.Solve(m)
    out = {'seconds': round(time.time() - t0, 3), 'model_pairs': len(pairvars), 'model_vertices': len(V),
           'live_groups': len(live)}
    if st in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        S = {v for v in V if solver.Value(x[v])}
        gp = []
        for a, b, n in pairvars:
            gp += [(a, b)] * solver.Value(n)
        out.update(status='found', optimal=st == cp_model.OPTIMAL, S=S, group_pairs=gp)
        if relaxed:
            out.update(status='relaxed', uncovered=int(sum(solver.Value(u) for u in unc)),
                       uncovered_bound=int(solver.BestObjectiveBound() // 1000))
    elif st == cp_model.INFEASIBLE:
        out.update(status='none')
    else:
        out.update(status='unknown')
    return out


def certificate(model, dictionary_bytes, position_bytes, mode, S, group_pairs):
    """Turn group pairs into word pairs (distinct unused words of each group)."""
    current, counts, used = model.position(json.loads(position_bytes.decode('utf-8')))
    pool = {}
    for w in model.words:
        if w not in used:
            pool.setdefault(model.word_group(w), []).append(w)
    pairs = []
    for a, b in group_pairs:
        wa = pool[a].pop()
        wb = pool[b].pop()
        pairs.append([wa, wb])
    return {
        'format': 'pairing-proof-v1', 'claim': 'player_to_move_loses', 'mode': mode,
        'dictionary_sha256': hashlib.sha256(dictionary_bytes).hexdigest(),
        'position_sha256': hashlib.sha256(position_bytes).hexdigest(),
        'S': sorted(model.names[v] for v in S),
        'pairs': pairs,
        'note': 'found by CP-SAT (finding only); check with verify_pairing.py',
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--dictionary', required=True)
    ap.add_argument('--expected-word-count', type=int, required=True)
    ap.add_argument('--position', required=True)
    ap.add_argument('--mode', choices=['raw', 'canonical'], default='canonical')
    ap.add_argument('--seconds', type=float, default=10.0)
    ap.add_argument('--workers', type=int, default=1)
    ap.add_argument('--out')
    a = ap.parse_args()
    dictionary_bytes = Path(a.dictionary).read_bytes()
    position_bytes = Path(a.position).read_bytes()
    model = ModelV3(dictionary_bytes, a.expected_word_count)
    current, raw, used = model.position(json.loads(position_bytes.decode('utf-8')))
    if a.mode == 'raw':
        counts = raw
    else:
        counts, static = model.normalize(current, raw)
        if static != -1:
            print(json.dumps({'status': 'static', 'static_label': static}))
            return
    r = find(model, current, counts, a.seconds, a.workers)
    rep = {k: v for k, v in r.items() if k not in ('S', 'group_pairs')}
    if r['status'] == 'found':
        cert = certificate(model, dictionary_bytes, position_bytes, a.mode, r['S'], r['group_pairs'])
        rep.update(S=cert['S'], pairs=len(cert['pairs']))
        if a.out:
            Path(a.out).write_text(json.dumps(cert, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(rep, ensure_ascii=False))


if __name__ == '__main__':
    main()
