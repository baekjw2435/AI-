#!/usr/bin/env python3
"""Feasibility prototype (2026-11-07): pairing extended with 3-ply answers. NOT a proof format yet.

Claim, as for pairing: the player to move (A) loses. B's strategy:
  S  home vertices (A to move), containing the current vertex;
  M  middle vertices (A to move inside a 3-ply answer), disjoint from S.
Answers to each word x that A can play from S (every such word needs one, counted with multiplicity):
  two-way pair {x, y}: y is also playable from S, each is legal right after the other and leads back to S
                       (the plain pairing case); neither word may be playable from M;
  one-way partner p:   p is legal right after x and leads to S;
  3-ply answer:        an entry word e legal right after x and leading to a middle vertex m. Then A must play
                       some word z at m (any of them: all must be handled), and B answers from a reply set R_m.
                       For every word z playable at m, some reply in R_m is legal right after z and leads to S.
Stock conditions (the strategy must survive any order of play and A's choices in other branches):
  * B's words (one-way partners, entries, replies) can never be played by A: none is playable from S or M;
  * each B word has one role only; R_m is reserved for m alone;
  * each middle vertex has at most one entry, so it is visited at most once and one reply of R_m suffices
    (replies for different z may be the same word);
  * the words at m can only become fewer, so covering every word playable at m NOW covers the visit.
With M empty this is exactly pairing-proof-v1.

Why A loses (sketch): A always moves from S or from a middle vertex m during its single visit; every A word
there has an answer whose words A cannot touch and nobody else uses; each round removes at least two
words, so A runs out first.

check(...) re-checks a strategy from its group-level description, independently of the CP-SAT model in find().
"""
from collections import Counter
from ortools.sat.python import cp_model
import time


def check(model, current, counts, S, M, twoway, oneway, entries, replies):
    """twoway: list of (a, b) groups; oneway: list of (x, p); entries: list of (x, e); replies: {m: [h, ...]}.
    Raises AssertionError on any violated condition."""
    E = model.edges
    S, M = set(S), set(M)
    assert current in S and not (S & M)
    playS = lambda g: any(s in S for s in E[g][0])
    playM = lambda g: any(s in M for s in E[g][0])
    after = lambda x, y: E[x][1] in E[y][0]
    use = Counter()
    bwords = Counter()
    answered = Counter()
    for a, b in twoway:
        assert playS(a) and playS(b) and not playM(a) and not playM(b)
        assert after(a, b) and E[b][1] in S and after(b, a) and E[a][1] in S
        use[a] += 1; use[b] += 1; answered[a] += 1; answered[b] += 1
    for x, p in oneway:
        assert playS(x) and after(x, p) and E[p][1] in S
        use[x] += 1; use[p] += 1; bwords[p] += 1; answered[x] += 1
    visits = Counter()
    for x, e in entries:
        assert playS(x) and after(x, e) and E[e][1] in M
        use[x] += 1; use[e] += 1; bwords[e] += 1; answered[x] += 1; visits[E[e][1]] += 1
    assert all(v <= 1 for v in visits.values()), 'a middle vertex is entered twice'
    for m, hs in replies.items():
        assert m in M
        for h in hs:
            assert E[h][1] in S
            use[h] += 1; bwords[h] += 1
    for m in visits:
        hs = replies.get(m, [])
        for z, c in enumerate(counts):
            if c and m in E[z][0]:
                assert any(after(z, h) for h in hs), f'no reply for a word at middle vertex {m}'
    for g, n in use.items():
        assert n <= counts[g], f'group {g} over-used'
    for g in bwords:
        assert not playS(g) and not playM(g), f'B word group {g} can be played by A'
    for g, c in enumerate(counts):
        if c and playS(g):
            assert answered[g] == c, f'group {g}: {answered[g]} of {c} words answered'
    return True


def find(model, current, counts, seconds=30.0, workers=1, allow_middle=True):
    """CP-SAT search for (S, M, answers). FINDING ONLY: results must pass check()."""
    t0 = time.time()
    E = model.edges
    live = [g for g, c in enumerate(counts) if c]
    V = sorted({current} | {E[g][1] for g in live})
    m_ = cp_model.CpModel()
    xs = {v: m_.NewBoolVar(f'x{v}') for v in V}
    ws = {v: m_.NewBoolVar(f'w{v}') for v in V} if allow_middle else {}
    for v in V:
        if allow_middle:
            m_.Add(xs[v] + ws[v] <= 1)
    m_.Add(xs[current] == 1)
    if allow_middle:
        m_.Add(ws[current] == 0)

    def orvar(vs, name):
        if not vs:
            return None
        b = m_.NewBoolVar(name)
        for v in vs:
            m_.AddImplication(v, b)
        m_.AddBoolOr(vs).OnlyEnforceIf(b)
        return b
    yS = {g: orvar([xs[s] for s in E[g][0] if s in xs], f'yS{g}') for g in live}
    yM = {g: (orvar([ws[s] for s in E[g][0] if s in ws], f'yM{g}') if allow_middle else None) for g in live}
    usable = {}
    for g in live:
        for s in E[g][0]:
            usable.setdefault(s, []).append(g)
    use = {g: [] for g in live}
    ans = {g: [] for g in live}
    vars_ = []

    def forbid(z, lit):            # z -> not lit
        if lit is not None:
            m_.AddBoolOr([z.Not(), lit.Not()])

    def need(z, lit):              # z -> lit (lit None means impossible)
        if lit is None:
            m_.Add(z == 0)
        else:
            m_.AddImplication(z, lit)
    # two-way pairs and one-way partners / entries, for x playable from S
    for a in live:
        if yS[a] is None:
            continue
        for b in usable.get(E[a][1], []):
            cap = counts[a] // 2 if a == b else min(counts[a], counts[b])
            # one-way partner b for a
            if counts[b] >= 1:
                n = m_.NewIntVar(0, min(counts[a], counts[b]), f'o{a}_{b}')
                z = m_.NewBoolVar(f'zo{a}_{b}')
                m_.Add(n <= counts[a] * z); m_.Add(n >= z)
                need(z, yS[a]); need(z, xs.get(E[b][1])); forbid(z, yS[b]); forbid(z, yM[b])
                use[a].append(n); use[b].append(n); ans[a].append(n); vars_.append(('o', a, b, n))
                # entry b for a (3-ply answer into m = target of b)
                if allow_middle and E[b][1] in ws:
                    n2 = m_.NewBoolVar(f'e{a}_{b}')
                    need(n2, yS[a]); need(n2, ws[E[b][1]]); forbid(n2, yS[b]); forbid(n2, yM[b])
                    use[a].append(n2); use[b].append(n2); ans[a].append(n2); vars_.append(('e', a, b, n2))
            # two-way pair {a, b} (b < a handled when iterating b, avoid duplicates by a <= b)
            if a <= b and cap >= 1 and yS.get(b) is not None and E[b][1] in xs and E[a][1] in xs and E[b][1] in xs:
                if E[b][1] in [s for s in E[a][0]] or a == b:
                    n3 = m_.NewIntVar(0, cap, f't{a}_{b}')
                    z3 = m_.NewBoolVar(f'zt{a}_{b}')
                    m_.Add(n3 <= cap * z3); m_.Add(n3 >= z3)
                    need(z3, yS[a]); need(z3, yS[b]); need(z3, xs[E[a][1]]); need(z3, xs[E[b][1]])
                    forbid(z3, yM[a]); forbid(z3, yM[b])
                    if a == b:
                        use[a].append(2 * n3); ans[a].append(2 * n3)
                    else:
                        use[a].append(n3); use[b].append(n3); ans[a].append(n3); ans[b].append(n3)
                    vars_.append(('t', a, b, n3))
    # middle vertices: single visit, replies
    res = []
    if allow_middle:
        entries_into = {}
        for kind, a, b, n in vars_:
            if kind == 'e':
                entries_into.setdefault(E[b][1], []).append(n)
        for mv, ns in entries_into.items():
            vis = m_.NewBoolVar(f'vis{mv}')
            m_.Add(sum(ns) == vis)
            zs = [z for z in live if mv in E[z][0]]
            rv = {}
            for z in zs:
                opts = []
                for h in usable.get(E[z][1], []):
                    if h not in rv:
                        r = m_.NewBoolVar(f'r{mv}_{h}')
                        need(r, xs.get(E[h][1])); forbid(r, yS[h]); forbid(r, yM[h]); m_.AddImplication(r, vis)
                        rv[h] = r
                        use[h].append(r)
                        res.append((mv, h, r))
                    opts.append(rv[h])
                m_.AddBoolOr(opts + [vis.Not()])
    for g in live:
        if use[g]:
            m_.Add(sum(use[g]) <= counts[g])
        if yS[g] is not None:
            m_.Add(sum(ans[g]) >= counts[g]).OnlyEnforceIf(yS[g]) if ans[g] else m_.Add(yS[g] == 0)
    m_.Minimize(sum(xs.values()) + (sum(ws.values()) if allow_middle else 0))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(seconds)
    solver.parameters.num_search_workers = int(workers)
    st = solver.Solve(m_)
    out = {'seconds': round(time.time() - t0, 3), 'live_groups': len(live)}
    if st in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        S = [v for v in V if solver.Value(xs[v])]
        M = [v for v in V if allow_middle and solver.Value(ws[v])]
        tw, ow, en = [], [], []
        for kind, a, b, n in vars_:
            k = solver.Value(n)
            if kind == 't':
                tw += [(a, b)] * k
            elif kind == 'o':
                ow += [(a, b)] * k
            else:
                en += [(a, b)] * k
        rep = {}
        for mv, h, r in res:
            if solver.Value(r):
                rep.setdefault(mv, []).append(h)
        out.update(status='found', S=S, M=M, twoway=tw, oneway=ow, entries=en, replies=rep,
                   middle_used=len({E[b][1] for a, b in en}))
    elif st == cp_model.INFEASIBLE:
        out.update(status='none')
    else:
        out.update(status='unknown')
    return out
