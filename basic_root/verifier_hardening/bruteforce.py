#!/usr/bin/env python3
"""Exhaustive small-graph and random word-level checks of every v2 reduction.

Part A (count level, exhaustive): every directed multigraph with self-loops on
  2 vertices (multiplicity 0..3), 3 vertices (0..2), 4 vertices (0..1), every start.
  Reference = plain minimax over remaining edge counts (words with equal endpoints
  are interchangeable, so this equals word-level minimax; Part B checks that too).
  Under test = verify_v2's IndependentModelV2 (unmodified) and verify_fast (Python and C).
Part B (word level, random): real Hangul words with ㄹ/ㄴ final syllables; reference =
  bitmask minimax over individual words using the site rule "next word starts with the
  last syllable or its standard dueum form" (route_engine.dueum semantics), written here
  independently.
"""
from functools import lru_cache
from itertools import product
import json, random, sys, time
from pathlib import Path

S = Path("/tmp/claude-0/-home-user-AI-/80ff9426-9f7b-5815-97c0-938f621a9f93/scratchpad")
sys.path.insert(0, str(S / "verifier/route-verifier-v2"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_v2 import IndependentModelV2  # noqa: E402
import verify_fast as vf                  # noqa: E402

SYL = "가나다마"
FILL = "아"
started = time.time()
stats = {k: 0 for k in ("graphs", "starts", "states_compared", "pair_only", "loop_only", "reach_only",
                        "static_vertex_labels", "core_positions", "static_positions", "idempotent",
                        "certificate_recursion", "fast_python_equal", "fast_c_equal")}
failures = []


def check(cond, what):
    if not cond:
        failures.append(what)
        if len(failures) < 10:
            print("FAIL", what, flush=True)


for n, mult in ((2, 3), (3, 2), (4, 1)):
    letters = SYL[:n]
    ordered = [(a, b) for a in range(n) for b in range(n)]

    @lru_cache(maxsize=None)
    def raw(current, counts):  # counts over `ordered`
        for k, (a, b) in enumerate(ordered):
            if a == current and counts[k]:
                nxt = counts[:k] + (counts[k] - 1,) + counts[k + 1:]
                if not raw(b, nxt):
                    return True
        return False

    for counts in product(range(mult + 1), repeat=len(ordered)):
        if not any(counts):
            continue
        words = [letters[a] + FILL * j + letters[b] for k, (a, b) in enumerate(ordered) for j in range(counts[k])]
        data = " ".join(words).encode()
        m2 = IndependentModelV2(data, 0)
        mf = vf.Model(data, 0)
        ce = vf.CEngine(mf)
        stats["graphs"] += 1
        # map model groups <-> ordered pairs; model vertices are a subset of letters
        index_of = {letters.index(s): i for i, s in enumerate(m2.syllables)}
        letter_of = {i: letters.index(s) for i, s in enumerate(m2.syllables)}

        def to_ordered(model_counts):
            out = [0] * len(ordered)
            for g, (s, t) in enumerate(m2.edges):
                out[ordered.index((letter_of[s], letter_of[t]))] = model_counts[g]
            return tuple(out)

        def value(current_model_vertex, model_counts):
            return raw(letter_of[current_model_vertex], to_ordered(model_counts))

        @lru_cache(maxsize=None)
        def reduced(current, cnts):  # certificate semantics (verify_v2 transitions)
            cnts, static = m2.normalize(current, cnts)
            if static != -1:
                return bool(static)
            for g in m2.outgoing[current]:
                if cnts[g]:
                    child, rest, _ = m2.child_v2(current, cnts, g)
                    if not reduced(child, rest):
                        return True
            return False

        # all sub-states of this graph appear as other graphs; test the full state only
        full = m2.full_counts
        for cur_letter in range(n):
            if cur_letter not in index_of:
                continue
            cur = index_of[cur_letter]
            stats["starts"] += 1
            truth = raw(cur_letter, counts)
            # T1 pair cancellation only (u != v), T2 loop parity only, T3 reachability only
            c1 = bytearray(full)
            for a, b in m2.pairs:
                d = min(c1[a], c1[b]); c1[a] -= d; c1[b] -= d
            check(value(cur, c1) == truth, ("pair_only", words, cur_letter)); stats["pair_only"] += 1
            c2 = bytearray(full)
            for g in m2.loops:
                c2[g] %= 2
            check(value(cur, c2) == truth, ("loop_only", words, cur_letter)); stats["loop_only"] += 1
            c3 = bytearray(full)
            reach = {cur}; q = [cur]
            for s in q:
                for g in m2.outgoing[s]:
                    if c3[g] and m2.edges[g][1] not in reach:
                        reach.add(m2.edges[g][1]); q.append(m2.edges[g][1])
            for g, (s, _) in enumerate(m2.edges):
                if s not in reach:
                    c3[g] = 0
            check(value(cur, c3) == truth, ("reach_only", words, cur_letter)); stats["reach_only"] += 1
            # T4 every statically labelled vertex has its true value in the paired state
            paired = m2.reduce(cur, full)
            labels = m2.static_labels(paired)
            for x, lab in enumerate(labels):
                if lab != -1:
                    check(value(x, paired) == bool(lab), ("static_label", words, cur_letter, x))
                    stats["static_vertex_labels"] += 1
            # T5 unknown core / static position, T6 idempotence
            canon, st = m2.normalize(cur, full)
            if st == -1:
                stats["core_positions"] += 1
                check(value(cur, canon) == truth, ("core", words, cur_letter))
                check(m2.normalize(cur, canon) == (canon, -1), ("idempotent_core", words, cur_letter))
            else:
                stats["static_positions"] += 1
                check(bool(st) == truth, ("static_position", words, cur_letter))
                check(m2.normalize(cur, canon) == (canon, st), ("idempotent_static", words, cur_letter))
            stats["idempotent"] += 1
            # T7 certificate-level recursion through child_v2
            check(reduced(cur, full) == truth, ("certificate", words, cur_letter))
            stats["certificate_recursion"] += 1
            # verify_fast engines agree with verify_v2 on this state and on all children
            states = [(cur, full)] + [(m2.edges[g][1], bytes(full[:g]) + bytes([full[g] - 1]) + bytes(full[g + 1:]))
                                      for g in m2.outgoing[cur] if full[g]]
            for v, c in states:
                ref = m2.normalize(v, c)
                check(mf.normalize(v, c) == ref, ("fast_python", words, v)); stats["fast_python_equal"] += 1
                check(ce.normalize(v, c) == ref, ("fast_c", words, v)); stats["fast_c_equal"] += 1
                stats["states_compared"] += 1
    print(f"n={n} mult<={mult}: cumulative graphs {stats['graphs']} starts {stats['starts']} "
          f"failures {len(failures)} t={time.time() - started:.0f}s", flush=True)

# ---------------------------------------------------------------------------- Part B
sys.path.insert(0, "/home/user/AI-")
from route_engine import dueum_variants  # site rule: [syllable] + [standard dueum form]


def raw_word_game(words, start):
    nw = len(words)

    @lru_cache(maxsize=None)
    def win(current, avail):
        variants = set(dueum_variants(current))
        for i in range(nw):
            if avail >> i & 1 and words[i][0] in variants:
                if not win(words[i][-1], avail & ~(1 << i)):
                    return True
        return False
    return win(start, (1 << nw) - 1)


def model_value(model, normalize, start_syllable):
    cur = model.vertex[model.dueum(start_syllable)] if hasattr(model, "dueum") else model.vertex[start_syllable]
    G = len(model.edges)
    out = [[g for g in range(G) if model.edges[g][0] == v] for v in range(len(model.syllables))]

    @lru_cache(maxsize=None)
    def rec(current, cnts):
        cnts, st = normalize(current, cnts)
        if st != -1:
            return bool(st)
        for g in out[current]:
            if cnts[g]:
                r = bytearray(cnts); r[g] -= 1
                if not rec(model.edges[g][1], bytes(r)):
                    return True
        return False
    return rec(cur, model.full_counts)


firsts = list("가나역여네노낙")          # dueum-invariant under both mappings
lasts = list("가나역여네노낙라력녀레로락")  # includes ㄹ/ㄴ forms; 레 is the legacy defect
rng = random.Random(20261028)
partb = {"dictionaries": 0, "positions": 0, "fast_standard_mismatch": 0, "v2_legacy_mismatch": 0,
         "v2_mismatch_examples": []}
for trial in range(1500):
    k = rng.randrange(2, 11)
    words = set()
    while len(words) < k:
        words.add(rng.choice(firsts) + FILL * rng.randrange(0, 2) + rng.choice(lasts))
    words = sorted(words)
    data = " ".join(words).encode()
    m2 = IndependentModelV2(data, 0)
    mf = vf.Model(data, 0)
    partb["dictionaries"] += 1
    for start in sorted({w[0] for w in words}):
        truth = raw_word_game(words, start)
        fast = model_value(mf, mf.normalize, start)
        v2 = model_value(m2, m2.normalize, start)
        partb["positions"] += 1
        if fast != truth:
            partb["fast_standard_mismatch"] += 1
        if v2 != truth:
            partb["v2_legacy_mismatch"] += 1
            if len(partb["v2_mismatch_examples"]) < 5:
                partb["v2_mismatch_examples"].append({"words": words, "start": start, "raw": truth, "verify_v2": v2})
print(json.dumps({"partA": stats, "partA_failures": len(failures), "partB": partb,
                  "seconds": round(time.time() - started, 1)}, ensure_ascii=False, indent=1))
Path(__file__).with_name("bruteforce_results.json").write_text(
    json.dumps({"partA": stats, "partA_failures": failures[:20], "partB": partb}, ensure_ascii=False, indent=1))
