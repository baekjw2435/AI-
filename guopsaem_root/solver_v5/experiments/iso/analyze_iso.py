#!/usr/bin/env python3
"""Measurement for 'reuse of small endgames that have the same structure under other names' (2026-11-06).

usage: analyze_iso.py INPUT.txt ISO.log [ISO.stats]

INPUT.txt  the solver input of the searched position ("N G ROOT", then per group "k s1..sk t count").
ISO.log    records written by solver_v5_isolog --iso-log (one per mid() call on a state with <= K live groups).
ISO.stats  the solver's stderr (last line: JSON counters of every mid() call by number of live groups).

For every logged state the live structure is rebuilt: the current vertex, the vertices R reachable through
live groups, and each live group as (its sources inside R, its target, its count). Two states with
isomorphic structures (a renaming of vertices that maps the current vertex to the current vertex and every
group to a group with the same sources, target and count) are the same game. The script reports
 * how many mid() calls / distinct states / isomorphism classes there are among the small states,
 * how many small states the current canonical form leaves undecided but an extended reduction of the same
   kind (canonical form applied to the structure restricted to R) decides at once (measurement only),
 * an upper bound on the search a perfect isomorphism table would have saved: the work of the outermost
   mid() calls whose isomorphism class had already been proven (by another state) before the call began.
Measurement only: nothing here is used to decide a position.
"""
import json
import struct
import sys
from collections import Counter, defaultdict

REC = struct.Struct('<QQQQIHBBH')  # entry, exit, h0, h1, work, cur, result, ng, depth


def read_graph(path):
    with open(path) as f:
        tok = f.read().split()
    n, g, root = int(tok[0]), int(tok[1]), int(tok[2])
    pos = 3
    srcs, dst = [], []
    for _ in range(g):
        k = int(tok[pos]); pos += 1
        srcs.append(tuple(int(x) for x in tok[pos:pos + k])); pos += k
        dst.append(int(tok[pos])); pos += 2  # target, count
    return n, srcs, dst


def read_log(path):
    data = open(path, 'rb').read()
    out, i = [], 0
    while i < len(data):
        entry, ex, h0, h1, work, cur, res, ng, depth = REC.unpack_from(data, i)
        i += REC.size
        gl = [(struct.unpack_from('<H', data, i + 3 * j)[0], data[i + 3 * j + 2]) for j in range(ng)]
        i += 3 * ng
        out.append(dict(entry=entry, exit=ex, key=(h0, h1), work=work, cur=cur, res=res, depth=depth, groups=gl))
    return out


def restrict(cur, groups):
    """groups: {(sources frozenset, target): count} -> same, sources cut to the vertices reachable from cur
    through live groups; groups that become equal are merged (their words are interchangeable)."""
    seen, q = {cur}, [cur]
    usable = defaultdict(list)
    for (S, t), c in groups.items():
        if c:
            for s in S:
                usable[s].append(t)
    while q:
        u = q.pop()
        for t in usable[u]:
            if t not in seen:
                seen.add(t); q.append(t)
    out = defaultdict(int)
    for (S, t), c in groups.items():
        S2 = frozenset(S) & seen
        if c and S2:
            out[(S2, t)] += c
    return dict(out), seen


def canon_reduce(cur, groups):
    """verify_v3 / ref_canon semantics applied to the (restricted) structure: loop mod 2 and pair
    cancellation between single-source groups, pruning, least-fixed-point static labels (a shared loop
    blocks the loop rule), unknown-core pruning. Returns (status, groups): status 0/1 static L/W, -1 core."""
    # Restrict first, then reduce; repeat, because cutting sources can make a shared group single-source
    # (the loop and pair rules are only valid for groups usable at one vertex).
    k = dict(groups)
    while True:
        k, seen = restrict(cur, k)
        changed = False
        for (S, t) in list(k):
            if len(S) == 1 and next(iter(S)) == t and k[(S, t)] >= 2:
                k[(S, t)] %= 2; changed = True
        for (S, t) in list(k):
            if len(S) == 1:
                u = next(iter(S))
                r = (frozenset([t]), u)
                if u < t and r in k and k[(S, t)] and k[r]:
                    d = min(k[(S, t)], k[r]); k[(S, t)] -= d; k[r] -= d; changed = True
        k = {e: c for e, c in k.items() if c}
        if not changed:
            break
    k, seen = restrict(cur, k)
    sb, loop, sloop = defaultdict(set), set(), set()
    for (S, t), c in k.items():
        for s in S:
            if s == t:
                (loop if len(S) == 1 else sloop).add(s)
            else:
                sb[s].add(t)
    preds = defaultdict(set)
    for u, ts in sb.items():
        for t in ts:
            preds[t].add(u)
    status, left, q = {}, {u: len(sb[u]) for u in seen}, []
    for u in seen:
        if not left[u] and u not in sloop:
            status[u] = 1 if u in loop else 0; q.append(u)
    i = 0
    while i < len(q):
        t = q[i]; i += 1
        for u in preds[t]:
            if u in status:
                continue
            if status[t] == 0:
                status[u] = 1; q.append(u)
            else:
                left[u] -= 1
                if left[u] == 0 and u not in sloop:
                    status[u] = 1 if u in loop else 0; q.append(u)
    if cur in status:
        return status[cur], {}
    seen2, q = {cur}, [cur]
    usable = defaultdict(list)
    for (S, t), c in k.items():
        for s in S:
            usable[s].append(t)
    while q:
        u = q.pop()
        for t in usable[u]:
            if t not in status and t not in seen2:
                seen2.add(t); q.append(t)
    core = {}
    for (S, t), c in k.items():
        S2 = S & seen2
        if S2 and t not in status:
            core[(S2, t)] = core.get((S2, t), 0) + c
    return -1, core


def ext_reduce(cur, groups):
    """Repeat restriction + canonical reduction until nothing changes."""
    g = groups
    while True:
        st, g2 = canon_reduce(cur, g)
        if st != -1 or g2 == g:
            return st, g2
        g = g2


def iso_form(cur, groups, budget=[0]):
    """Canonical form under renaming of vertices (cur fixed): colour refinement + individualization,
    minimum certificate over all branches. Exact (no hashing of the structure)."""
    V = sorted({cur} | {v for (S, t) in groups for v in S} | {t for (S, t) in groups})
    ix = {v: i for i, v in enumerate(V)}
    n = len(V)
    E = [(tuple(ix[s] for s in S), ix[t], c) for (S, t), c in groups.items()]
    outs, ins = [[] for _ in range(n)], [[] for _ in range(n)]
    for gi, (S, t, c) in enumerate(E):
        for s in S:
            outs[s].append(gi)
        ins[t].append(gi)

    def refine(col):
        while True:
            gs = [(c, tuple(sorted(col[s] for s in S)), col[t]) for (S, t, c) in E]
            vs = [(col[v], tuple(sorted(gs[g] for g in outs[v])), tuple(sorted(gs[g] for g in ins[v]))) for v in range(n)]
            keys = {k: i for i, k in enumerate(sorted(set(vs)))}
            new = [keys[x] for x in vs]
            if len(keys) == len(set(col)):
                return new
            col = new

    def search(col):
        budget[0] += 1
        col = refine(col)
        if len(set(col)) == n:
            return tuple(sorted((tuple(sorted(col[s] for s in S)), col[t], c) for (S, t, c) in E)) + ((col[ix[cur]],),)
        cnt = Counter(col)
        cls = min(c for c, m in cnt.items() if m > 1)
        best = None
        for v in range(n):
            if col[v] == cls:
                c2 = [2 * x for x in col]; c2[v] += 1
                r = search(c2)
                if best is None or r < best:
                    best = r
        return best

    return search([1 if v == cur else 0 for v in V])


def main():
    inp, logp = sys.argv[1], sys.argv[2]
    n, srcs, dst = read_graph(inp)
    recs = read_log(logp)
    rep = {}
    if len(sys.argv) > 3:
        st = json.loads(open(sys.argv[3]).read().strip().splitlines()[-1])
        rep['mid_calls_total'] = sum(st['mid_by_groups'])
        rep['min_live_groups'] = st['min_groups']
        rep['max_depth'] = st['max_depth']
    rep['logged_mid_calls'] = len(recs)
    keys = {}
    for r in recs:
        if r['key'] in keys:
            continue
        groups = {(frozenset(srcs[g]), dst[g]): c for g, c in r['groups']}
        g0, _ = restrict(r['cur'], groups)
        st, g1 = ext_reduce(r['cur'], g0)
        keys[r['key']] = dict(ng=len(r['groups']), ext_static=st, ext_ng=len(g1),
                              iso=iso_form(r['cur'], g0), ext_iso=('static', st) if st != -1 else iso_form(r['cur'], g1))
    rep['distinct_states'] = len(keys)
    rep['iso_classes'] = len({v['iso'] for v in keys.values()})
    rep['ext_iso_classes'] = len({v['ext_iso'] for v in keys.values()})
    rep['states_decided_by_extended_reduction'] = sum(1 for v in keys.values() if v['ext_static'] != -1)
    rep['states_by_live_groups'] = dict(sorted(Counter(v['ng'] for v in keys.values()).items()))
    # upper bound of the search saved by a perfect isomorphism table (and, separately, by the extended reduction)
    for name, fld in (('iso', 'iso'), ('ext_iso', 'ext_iso')):
        first = {}
        for r in sorted(recs, key=lambda r: r['exit']):
            if r['res'] and keys[r['key']][fld] not in first:
                first[keys[r['key']][fld]] = (r['exit'], r['key'])
        saved, calls, same, end = 0, 0, 0, -1
        for r in sorted(recs, key=lambda r: r['entry']):
            f = first.get(keys[r['key']][fld])
            reusable = (f is not None and f[0] < r['entry']) or (fld == 'ext_iso' and keys[r['key']]['ext_static'] != -1)
            if not reusable:
                continue
            calls += 1
            if f is not None and f[1] == r['key']:
                same += 1
            if r['entry'] > end:  # outermost
                saved += r['work']; end = r['exit']
        rep[f'{name}_reusable_calls'] = calls
        rep[f'{name}_reusable_same_state'] = same
        rep[f'{name}_saved_mid_calls_upper_bound'] = saved
    rep['iso_search_nodes'] = iso_form.__defaults__[0][0]
    print(json.dumps(rep, ensure_ascii=False))


if __name__ == '__main__':
    main()
