#!/usr/bin/env python3
"""Adversarial soundness check of the v3 canonical form (shared groups).

Three layers are compared, bottom-up:
  L0  raw word game: words, used-bitmask, received syllable and an initial-sound
      table written here independently from jamo tables (no ModelV3, no conv()).
  L1  plain grouped game on ModelV3 vertices/groups, with NO reduction at all.
  L2  ModelV3 canonical game: normalize() after every move, static leaves.
L0 == L1 checks vertex merging, grouping, one-step one-way conversion and
position()/history/initial_used_words (steps 5-7). L1 == L2 and the per-node
checks below test the canonical form (steps 1-4):
  * pair cancellation alone preserves the value from EVERY vertex;
  * reduce() preserves the value from the current vertex;
  * every static label (all vertices, also unreachable ones) equals L1 on the
    reduced counts;
  * every move from a reachable unknown vertex into a labelled target is a
    losing move (child value is W for the receiver);
  * the core has the same value and normalize() is idempotent.
L2 is expanded WITHOUT short-circuit, so these checks run at every canonical node.

Targeted generators: 3-source groups (렷/녓/엿, 려/녀/여, 륜/뉸/윤, ...), shared
loops (낙..락, 낙..낙, 엿..렷), multiplicities > 1, dense cycles, single-source
pairs next to shared groups, merged vertices, empty-key end syllables, small
sub-dictionaries of REAL words of words_3436.txt around 낙/락, 눙/룽, 엿/녓,
윤/륜, 낸/랜; up to 18 words. Positions use random initial_used_words and random
raw-legal histories (every prefix is compared). Besides the generated positions,
a sample of every state visited by the plain grouped game is checked too.

Part "abstract": the same checks on ARBITRARY grouped graphs (any source sets of
size 1-3, not necessarily realizable by a dictionary), i.e. on the canonical-form
argument itself.

Part "exhaustive": every small count vector of complete abstract models (all
group types on 2 and 3 vertices) and random vectors on 4 vertices.

Part "mutants": deliberately unsound variants (shared groups paired, shared loop
used in / ignored by the loop rule, shared loops mod 2, first-source-only
availability, two-way or chained conversion, loops cancelled fully, "all sources
reachable" dropping, "all sources in core" pruning) must each be caught, and two
sound controls (no pair cancellation; no core extraction) must pass.

Part "cpp": differential test of ref_canon / gen_child / materialize from a
verbatim copy of solver_v4.cpp (adversarial/ref_canon_harness.cpp) against
ModelV3.normalize / child on random states of the real 3,436-word model and of
small random dictionaries.

Usage:
  test_v3_adversarial.py model   [DICTS] [SEED]
  test_v3_adversarial.py abstract [GRAPHS] [SEED]
  test_v3_adversarial.py exhaustive [RANDOM_N4_VECTORS] [SEED]
  test_v3_adversarial.py mutants [DICTS] [SEED]
  test_v3_adversarial.py cpp     [STATES] [SEED] [--harness BIN]
  test_v3_adversarial.py cpp-power [STATES] [SEED] [--harness BIN]
(without --harness, adversarial/ref_canon_harness.cpp is compiled into a temp dir)
"""
from functools import lru_cache
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from verify_v3 import ModelV3, VerificationError, conv as model_conv  # noqa: E402

# ---------------------------------------------------------------- independent rule
CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
JUNG = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
TO_O_AFTER_R = set("ㅑㅕㅖㅛㅠㅣ")
TO_N_AFTER_R = set("ㅏㅐㅗㅚㅜㅡ")
TO_O_AFTER_N = set("ㅕㅛㅠㅣ")


def decompose(s):
    o = ord(s) - 0xAC00
    assert 0 <= o < 11172
    return CHO[o // 588], JUNG[(o % 588) // 28], o % 28


def compose(cho, jung, jong):
    return chr(0xAC00 + (CHO.index(cho) * 21 + JUNG.index(jung)) * 28 + jong)


def alt(s):
    """The rule text, independently: the one alternative first syllable after s."""
    c, v, j = decompose(s)
    if c == "ㄹ" and v in TO_O_AFTER_R:
        return compose("ㅇ", v, j)
    if c == "ㄹ" and v in TO_N_AFTER_R:
        return compose("ㄴ", v, j)
    if c == "ㄴ" and v in TO_O_AFTER_N:
        return compose("ㅇ", v, j)
    return None


def check_conv_table():
    for i in range(11172):
        s = chr(0xAC00 + i)
        assert alt(s) == model_conv(s), (s, alt(s), model_conv(s))
        a = alt(s)
        if a is not None:          # one step only: an alternative never converts again
            assert alt(a) is None, (s, a)
    return 11172


# ---------------------------------------------------------------- L0 raw game
class Budget(Exception):
    pass


def raw_solver(words, budget=400000):
    index = {w: i for i, w in enumerate(words)}
    calls = [0]

    @lru_cache(maxsize=None)
    def value(received, used):
        calls[0] += 1
        if calls[0] > budget:
            raise Budget
        a = alt(received)
        for i, w in enumerate(words):
            if used >> i & 1:
                continue
            if w[0] == received or w[0] == a:
                if not value(w[-1], used | 1 << i):
                    return True
        return False
    return index, value, calls


# ---------------------------------------------------------------- L1 grouped game
def grouped_solver(model):
    memo = {}

    def value(v, counts):
        key = (v, counts)
        r = memo.get(key)
        if r is None:
            r = False
            for g in model.available[v]:
                if counts[g]:
                    c = bytearray(counts)
                    c[g] -= 1
                    if not value(model.edges[g][1], bytes(c)):
                        r = True
                        break
            memo[key] = r
        return r
    value.memo = memo
    value.cache_clear = memo.clear
    return value


def pairs_only(model, counts):
    c = bytearray(counts)
    for a, b in model.pairs:
        m = min(c[a], c[b])
        c[a] -= m
        c[b] -= m
    for g in model.loops:
        c[g] %= 2
    return bytes(c)


# ---------------------------------------------------------------- L2 + node checks
class Mismatch(AssertionError):
    pass


def model_checker(model, plain, stats, full_pairs_check=True):
    def fail(kind, **info):
        raise Mismatch(kind, info)

    def check_node(cur, counts):
        truth = plain(cur, counts)
        if full_pairs_check:
            po = pairs_only(model, counts)
            for y in range(len(model.keys)):
                if plain(y, po) != plain(y, counts):
                    fail("pair-cancellation", vertex=model.names[y], cur=model.names[cur])
        paired = bytes(model.reduce(cur, counts))
        if plain(cur, paired) != truth:
            fail("reduce", cur=model.names[cur])
        labels = model.static_labels(paired)
        if type(model) is ModelV3 and variant_labels(model, paired, "block") != labels:
            fail("label-reimplementation", cur=model.names[cur])
        for y, lab in enumerate(labels):
            if lab != -1:
                stats["labels"] += 1
                if plain(y, paired) != bool(lab):
                    fail("static-label", vertex=model.names[y], label=lab, cur=model.names[cur])
        normalized, static = model.normalize(cur, counts)
        if static != -1:
            if static != labels[cur] or normalized != paired:
                fail("normalize-static")
            if model.normalize(cur, normalized) != (normalized, static):
                fail("idempotence-static")
            return truth
        # moves from reachable unknown vertices into labelled targets must lose
        seen = {cur}
        queue = [cur]
        for s in queue:
            for g in model.available[s]:
                if paired[g]:
                    t = model.edges[g][1]
                    if labels[t] == -1:
                        if t not in seen:
                            seen.add(t)
                            queue.append(t)
                    else:
                        c = bytearray(paired)
                        c[g] -= 1
                        stats["pruned_moves"] += 1
                        if not plain(t, bytes(c)):
                            fail("pruned-move-wins", src=model.names[s], tgt=model.names[t])
        if plain(cur, normalized) != truth:
            fail("core", cur=model.names[cur])
        if model.normalize(cur, normalized) != (normalized, -1):
            fail("idempotence-core", cur=model.names[cur])
        return truth

    @lru_cache(maxsize=None)
    def value(cur, counts):
        stats["nodes"] += 1
        truth = check_node(cur, counts)
        normalized, static = model.normalize(cur, counts)
        if static != -1:
            result = bool(static)
        else:
            result = False
            for g in model.available[cur]:      # no short-circuit: visit every child
                if normalized[g]:
                    t, child, child_static = model.child(cur, normalized, g)
                    cv = bool(child_static) if child_static != -1 else value(t, child)
                    if child_static != -1 and plain(t, child) != cv:
                        fail("child-static", tgt=model.names[t])
                    if not cv:
                        result = True
        if result != truth:
            fail("model-value", cur=model.names[cur], model=result, plain=truth)
        return result
    return value


# ---------------------------------------------------------------- generators
TRI = [("렷", "녓", "엿"), ("려", "녀", "여"), ("륜", "뉸", "윤"), ("료", "뇨", "요"),
       ("리", "니", "이"), ("류", "뉴", "유")]
DUO = [("락", "낙"), ("룽", "눙"), ("랜", "낸"), ("례", "예"), ("로", "노"), ("략", "약")]
PLAIN = list("가다마바사") + ["녜", "렌", "넨", "뇌"]   # 녜/렌 do not convert; 뇌 has no alt
FILL = [chr(0xAC00 + i) for i in range(5, 11172, 131)]


def make_word(first, last, rng, taken):
    if first == last and first + "" not in taken and rng.random() < 0.15:
        return first
    for _ in range(100):
        w = first + "".join(rng.choice(FILL) for _ in range(rng.randint(0, 2))) + last
        if len(w) == 1:
            w = first + last if first != last else first
        if w not in taken:
            return w
    return None


def gen_dictionary(rng, kind):
    if kind == "real":
        return gen_real(rng)
    sylls = []
    if kind in ("tri", "mixed", "sharedloop", "dense", "multi", "pairs"):
        for fam in rng.sample(TRI, rng.randint(1, 2)):
            sylls += [s for s in fam if rng.random() < 0.85] or [fam[-1]]
    if kind in ("duo", "mixed", "sharedloop", "dense", "multi", "pairs", "merge"):
        for fam in rng.sample(DUO, rng.randint(1, 2)):
            sylls += list(fam)
    if kind == "merge":
        fam = rng.choice(TRI)
        sylls += list(fam)
    sylls += rng.sample(PLAIN, rng.randint(1 if kind != "dense" else 0, 3))
    sylls = list(dict.fromkeys(sylls))
    if kind == "dense":
        sylls = sylls[:rng.randint(3, 5)]
    # the "base" syllables (the converted forms) are favoured as first syllables
    bases = [s for s in sylls if any(alt(x) == s for x in sylls)] or sylls
    size = {"dense": rng.randint(10, 18), "multi": rng.randint(8, 16)}.get(kind, rng.randint(5, 14))
    # some syllables never start a word (vertex merging, empty keys)
    starters = [s for s in sylls if s in bases or rng.random() < (0.6 if kind == "merge" else 0.9)]
    live = [s for s in sylls if s in starters or alt(s) in starters]   # ends with a move
    words = set()

    def add(first, last, mult=1):
        for _ in range(mult):
            w = make_word(first, last, rng, words)
            if w and len(words) < size:
                words.add(w)

    for first in rng.sample(starters, len(starters)):        # every starter starts a word
        add(first, rng.choice(live if rng.random() < 0.9 else sylls))
    attempts = 0
    while len(words) < size and attempts < 1000:
        attempts += 1
        last_pool = live if rng.random() < (0.97 if kind == "dense" else 0.85) else sylls
        if kind == "sharedloop" and rng.random() < 0.5:
            first = rng.choice(bases)
            fam = [x for x in sylls if alt(x) == first] + [first]
            last = rng.choice(fam)
        elif rng.random() < 0.5:
            first, last = rng.choice(bases), rng.choice(last_pool)
        else:
            first, last = rng.choice(starters), rng.choice(last_pool)
        mult = rng.randint(1, 4) if kind == "multi" or rng.random() < 0.15 else 1
        if kind == "pairs" and rng.random() < 0.4:
            # single-source pair u->v and v->u with multiplicities, next to shared groups
            add(first, last, rng.randint(1, 3))
            add(last, first, rng.randint(1, 3))
            continue
        add(first, last, mult)
    words = sorted(words)[:18] if len(words) > 18 else sorted(words)
    return words


_REAL = {}


def real_words():
    if not _REAL:
        words = (HERE.parent / "words_3436.txt").read_text(encoding="utf-8").split()
        starts = {w[0] for w in words}
        fam = sorted((x, alt(x)) for x in starts if alt(x) in starts)
        by_first = {}
        for w in words:
            by_first.setdefault(w[0], []).append(w)
        _REAL.update(words=words, fam=fam, by_first=by_first)
    return _REAL


def gen_real(rng):
    """Up to 18 REAL words of the 3,436-word list around the shared families
    (낙/락, 눙/룽, 엿/녓, 윤/륜, 낸/랜), closed a little under 'next word'."""
    r = real_words()
    chosen = set()
    for pair in rng.sample(r["fam"], rng.randint(1, 3)):
        for x in pair:
            chosen.update(rng.sample(r["by_first"][x], min(len(r["by_first"][x]), rng.randint(1, 4))))
    size = rng.randint(8, 18)
    frontier = sorted(chosen)
    while len(chosen) < size and frontier:
        w = rng.choice(frontier)
        nxt = [x for y in (w[-1], alt(w[-1])) if y for x in r["by_first"].get(y, [])]
        nxt = [x for x in nxt if x not in chosen]
        if not nxt:
            frontier.remove(w)
            continue
        x = rng.choice(nxt)
        chosen.add(x)
        frontier.append(x)
    return sorted(chosen)[:18]


KINDS = ["tri", "duo", "mixed", "sharedloop", "dense", "multi", "pairs", "merge", "real"]


# ---------------------------------------------------------------- model part
def run_model(dicts, seed, model_class=ModelV3, stop_at_first=False, quiet=False,
              full_pairs_check=True, positions_per_dict=4, extra_states=40):
    rng = random.Random(seed)
    stats = {"dictionaries": 0, "positions": 0, "raw_compared": 0, "raw_skipped_budget": 0,
             "extra_states": 0, "nodes": 0, "labels": 0, "pruned_moves": 0, "with_shared": 0,
             "with_3source": 0, "with_shared_loop": 0, "max_words": 0, "mismatches": []}
    for _ in range(dicts):
        kind = rng.choice(KINDS)
        words = gen_dictionary(rng, kind)
        if not words:
            continue
        stats["dictionaries"] += 1
        stats["max_words"] = max(stats["max_words"], len(words))
        try:
            model = model_class(" ".join(words).encode(), 0)
        except VerificationError as exc:
            raise AssertionError(("model construction failed", words, str(exc)))
        if any(model.shared):
            stats["with_shared"] += 1
        if any(len(s) >= 3 for s, _ in model.edges):
            stats["with_3source"] += 1
        if any(len(s) > 1 and t in s for s, t in model.edges):
            stats["with_shared_loop"] += 1
        index, raw, calls = raw_solver(words)
        plain = grouped_solver(model)
        mval = model_checker(model, plain, stats, full_pairs_check)
        in_dict = sorted({w[0] for w in words} | {w[-1] for w in words})
        others = sorted({x for fam in TRI + DUO for x in fam} | set(PLAIN))
        for _ in range(positions_per_dict):
            initial = rng.choice(in_dict if rng.random() < 0.85 else others)
            used_words = [w for w in words if rng.random() < rng.choice((0.0, 0.15, 0.35))]
            used = sum(1 << index[w] for w in used_words)
            # random legal history under the RAW rule
            history = []
            received = initial
            for _ in range(rng.randint(0, 4)):
                a = alt(received)
                legal = [w for w in words if not (used >> index[w] & 1) and w not in history
                         and (w[0] == received or w[0] == a)]
                if not legal:
                    break
                w = rng.choice(legal)
                history.append(w)
                received = w[-1]
            for plies in range(len(history) + 1):
                hist = history[:plies]
                manifest = {"initial_syllable": initial, "history": hist,
                            "initial_used_words": used_words}
                rec = hist[-1][-1] if hist else initial
                mask = used | sum(1 << index[w] for w in hist)
                try:
                    current, counts, _ = model.position(manifest)
                except VerificationError as exc:
                    # only acceptable if the receiver's usable set is empty AND no raw
                    # syllable has an empty set (vertex outside the model): then raw must lose
                    a = alt(rec)
                    usable = [w for w in words if w[0] in (rec, a)]
                    if "outside the model" in str(exc) and not usable:
                        continue
                    raise AssertionError(("position rejected", words, manifest, str(exc)))
                stats["positions"] += 1
                try:
                    got = mval(current, counts)
                    expected_plain = plain(current, counts)
                    if got != expected_plain:
                        raise Mismatch("model-vs-plain", {})
                    try:
                        calls[0] = 0
                        r = raw(rec, mask)
                        stats["raw_compared"] += 1
                        if r != expected_plain:
                            raise Mismatch("raw-vs-grouped", {"raw": r, "grouped": expected_plain})
                    except Budget:
                        stats["raw_skipped_budget"] += 1
                except Mismatch as exc:
                    stats["mismatches"].append({"kind": exc.args[0], "info": exc.args[1],
                                                "dictionary": words, "position": manifest})
                    if stop_at_first:
                        return stats
                    break
        # every state the plain grouped game visited is a legal position too
        # (arbitrary, non-canonical counts): check a sample of them through the model
        visited = list(plain.memo)
        for cur, counts in rng.sample(visited, min(len(visited), extra_states)):
            stats["extra_states"] += 1
            try:
                if mval(cur, counts) != plain(cur, counts):
                    raise Mismatch("model-vs-plain-extra", {})
            except Mismatch as exc:
                stats["mismatches"].append({"kind": exc.args[0], "info": exc.args[1],
                                            "dictionary": words, "state": (model.names[cur], counts.hex())})
                if stop_at_first:
                    return stats
                break
        mval.cache_clear()
        plain.cache_clear()
        raw.cache_clear()
    if not quiet:
        print(stats, flush=True)
    return stats


# ---------------------------------------------------------------- abstract part
def abstract_model(rng):
    """A ModelV3 object for an ARBITRARY grouped graph (any source sets of size 1-3,
    shared loops, multi-source groups whose target is a source, multiplicities 1-4).
    This is more general than what a dictionary can produce, so passing here supports
    the canonical-form argument itself, not only the dictionary-shaped cases."""
    m = ModelV3.__new__(ModelV3)
    n = rng.randint(2, 6)
    m.keys = [("v%d" % i,) for i in range(n)]
    m.vertex = {k: i for i, k in enumerate(m.keys)}
    m.names = ["v%d" % i for i in range(n)]
    edges = {}
    for _ in range(rng.randint(2, 11)):
        k = rng.choice((1, 1, 2, 2, 3))
        src = tuple(sorted(rng.sample(range(n), min(k, n))))
        t = rng.choice(src) if rng.random() < 0.25 else rng.randrange(n)
        edges[(src, t)] = rng.choice((1, 1, 1, 2, 2, 3, 4))
    m.edges = sorted(edges)
    m.group = {e: i for i, e in enumerate(m.edges)}
    m.full_counts = bytes(edges[e] for e in m.edges)
    m.available = [[] for _ in m.keys]
    for i, (src, _) in enumerate(m.edges):
        for x in src:
            m.available[x].append(i)
    m.shared = [len(src) > 1 for src, _ in m.edges]
    m.pairs, m.loops = [], []
    for i, (src, t) in enumerate(m.edges):
        if len(src) != 1:
            continue
        if src[0] == t:
            m.loops.append(i)
        elif src[0] < t and ((t,), src[0]) in m.group:
            m.pairs.append((i, m.group[(t,), src[0]]))
    return m


def run_abstract(graphs, seed, budget_words=13):
    rng = random.Random(seed)
    stats = {"graphs": 0, "positions": 0, "extra_states": 0, "nodes": 0, "labels": 0,
             "pruned_moves": 0, "mismatches": []}
    while stats["graphs"] < graphs:
        model = abstract_model(rng)
        if sum(model.full_counts) > budget_words:
            continue
        stats["graphs"] += 1
        plain = grouped_solver(model)
        mval = model_checker(model, plain, stats)
        try:
            for _ in range(4):
                cur = rng.randrange(len(model.keys))
                counts = bytes(c - sum(rng.random() < 0.2 for _ in range(c)) for c in model.full_counts)
                stats["positions"] += 1
                if mval(cur, counts) != plain(cur, counts):
                    raise Mismatch("abstract-value", {})
            visited = list(plain.memo)
            for cur, counts in rng.sample(visited, min(len(visited), 25)):
                stats["extra_states"] += 1
                if mval(cur, counts) != plain(cur, counts):
                    raise Mismatch("abstract-value-extra", {})
        except Mismatch as exc:
            stats["mismatches"].append({"kind": exc.args[0], "info": exc.args[1],
                                        "edges": model.edges, "counts": list(model.full_counts)})
    print(stats if not stats["mismatches"] else dict(stats, mismatches=stats["mismatches"][:3]),
          flush=True)
    return stats


def complete_model(n, max_sources=3):
    """Abstract ModelV3 with EVERY group type (source set of size <= max_sources, target)."""
    from itertools import combinations
    m = ModelV3.__new__(ModelV3)
    m.keys = [("v%d" % i,) for i in range(n)]
    m.vertex = {k: i for i, k in enumerate(m.keys)}
    m.names = ["v%d" % i for i in range(n)]
    m.edges = sorted((src, t) for k in range(1, max_sources + 1)
                     for src in combinations(range(n), k) for t in range(n))
    m.group = {e: i for i, e in enumerate(m.edges)}
    m.full_counts = bytes([255] * len(m.edges))
    m.available = [[] for _ in m.keys]
    for i, (src, _) in enumerate(m.edges):
        for x in src:
            m.available[x].append(i)
    m.shared = [len(src) > 1 for src, _ in m.edges]
    m.pairs, m.loops = [], []
    for i, (src, t) in enumerate(m.edges):
        if len(src) == 1:
            if src[0] == t:
                m.loops.append(i)
            elif src[0] < t:
                m.pairs.append((i, m.group[(t,), src[0]]))
    return m


def run_exhaustive(limit_random, seed):
    """All count vectors of small complete abstract models:
       n=2: every vector with counts 0..3 on all 6 group types (4,096 vectors);
       n=3: every vector with at most 5 groups of count 1 (27,896 vectors) and every
            vector with at most 3 groups of counts 1..3;
       n=4: LIMIT_RANDOM random vectors with 3..7 nonzero groups of counts 1..2."""
    from itertools import combinations, product
    rng = random.Random(seed)
    stats = {"vectors": 0, "positions": 0, "nodes": 0, "labels": 0, "pruned_moves": 0,
             "mismatches": []}

    def run(model, vectors):
        plain = grouped_solver(model)
        mval = model_checker(model, plain, stats)
        for counts in vectors:
            stats["vectors"] += 1
            for cur in range(len(model.keys)):
                stats["positions"] += 1
                try:
                    if mval(cur, counts) != plain(cur, counts):
                        raise Mismatch("exhaustive-value", {})
                except Mismatch as exc:
                    stats["mismatches"].append({"kind": exc.args[0], "info": exc.args[1], "n": len(model.keys),
                                                "groups": [(model.edges[g], c) for g, c in enumerate(counts) if c],
                                                "cur": cur})
                    return

    m2 = complete_model(2)
    run(m2, (bytes(v) for v in product(range(4), repeat=len(m2.edges))))
    m3 = complete_model(3)
    G3 = len(m3.edges)

    def vecs(model, k_max, values):
        G = len(model.edges)
        for k in range(k_max + 1):
            for idx in combinations(range(G), k):
                for vals in product(values, repeat=k):
                    v = bytearray(G)
                    for i, x in zip(idx, vals):
                        v[i] = x
                    yield bytes(v)
    run(m3, vecs(m3, 5, (1,)))
    run(m3, vecs(m3, 3, (1, 2, 3)))
    m4 = complete_model(4)
    G4 = len(m4.edges)

    def rand4():
        for _ in range(limit_random):
            v = bytearray(G4)
            for i in rng.sample(range(G4), rng.randint(3, 7)):
                v[i] = rng.choice((1, 1, 2))
            yield bytes(v)
    run(m4, rand4())
    print(stats if not stats["mismatches"] else dict(stats, mismatches=stats["mismatches"][:3]),
          {"groups_n3": G3, "groups_n4": G4}, flush=True)
    return stats


# ---------------------------------------------------------------- mutants
class PairShared(ModelV3):
    """Unsound: also cancels shared groups u->v against v->u as if single-source."""
    def reduce(self, current, counts):
        c = bytearray(counts)
        for i, (si, ti) in enumerate(self.edges):
            for j, (sj, tj) in enumerate(self.edges):
                if i < j and ti in sj and tj in si and ti != tj and (len(si) > 1 or len(sj) > 1):
                    m = min(c[i], c[j])
                    c[i] -= m
                    c[j] -= m
        for i, (si, ti) in enumerate(self.edges):
            if len(si) > 1 and ti in si:
                c[i] %= 2
        return ModelV3.reduce(self, current, bytes(c))


def variant_labels(model, counts, shared_loop_mode):
    """static_labels with a different treatment of shared loops (for mutants only).
    mode 'as_single': a shared loop counts like a single-source loop in the loop rule;
    mode 'ignore': shared loops neither block nor count;
    mode 'block': the real v3 rule (used as a control against ModelV3.static_labels)."""
    n = len(model.keys)
    labels = [-1] * n
    succ = [set() for _ in range(n)]
    loop = [0] * n
    block = [0] * n
    for g, c in enumerate(counts):
        if not c:
            continue
        sources, t = model.edges[g]
        for s in sources:
            if s == t:
                if len(sources) == 1 or shared_loop_mode == "as_single":
                    loop[s] = 1
                elif shared_loop_mode == "block":
                    block[s] = 1
            else:
                succ[s].add(t)
    changed = True
    while changed:
        changed = False
        for u in range(n):
            if labels[u] != -1:
                continue
            if any(labels[t] == 0 for t in succ[u]):
                labels[u] = 1
                changed = True
            elif all(labels[t] == 1 for t in succ[u]) and not block[u]:
                labels[u] = loop[u]
                changed = True
    return labels


class SharedLoopRule(ModelV3):
    """Unsound: a shared loop counts like a single-source loop in the loop rule."""
    def static_labels(self, counts):
        return variant_labels(self, counts, "as_single")


class SharedLoopIgnored(ModelV3):
    """Unsound: shared loops neither block nor count in the loop rule."""
    def static_labels(self, counts):
        return variant_labels(self, counts, "ignore")


class FirstSourceOnly(ModelV3):
    """Unsound: reachability/core only look at the first source of a shared group."""
    def __init__(self, *a):
        ModelV3.__init__(self, *a)
        self.available = [[] for _ in self.keys]
        for i, (s, _) in enumerate(self.edges):
            self.available[s[0]].append(i)


class TwoWay(ModelV3):
    """Unsound: conversion treated as two-way (낙 also allows 락-words)."""
    def key(self, syllable):
        a = model_conv(syllable)
        back = {x for x in self.starts if model_conv(x) == syllable}
        return tuple(sorted(s for s in {syllable, a} | back if s is not None and s in self.starts))


class Chain(ModelV3):
    """Unsound: conversion chains (려 -> 녀 -> 여)."""
    def key(self, syllable):
        out = {syllable}
        c, v, j = decompose(syllable)
        if c == "ㄹ" and v in TO_O_AFTER_R:
            out.add(compose("ㄴ", v, j))
        a = model_conv(syllable)
        while a is not None:
            out.add(a)
            a = model_conv(a)
        return tuple(sorted(s for s in out if s in self.starts))


class LoopNoParity(ModelV3):
    """Unsound: single-source loops cancelled completely (mod 1 instead of mod 2)."""
    def reduce(self, current, counts):
        c = bytearray(counts)
        for g in self.loops:
            c[g] = 0
        return ModelV3.reduce(self, current, bytes(c))


class SharedLoopParity(ModelV3):
    """Suspect: shared loops reduced modulo 2 like single-source loops."""
    def reduce(self, current, counts):
        c = bytearray(counts)
        for i, (si, ti) in enumerate(self.edges):
            if len(si) > 1 and ti in si:
                c[i] %= 2
        return ModelV3.reduce(self, current, bytes(c))


class AllSourcesReachable(ModelV3):
    """Unsound: step 2 drops a group unless ALL of its sources are reachable."""
    def reduce(self, current, counts):
        r = ModelV3.reduce(self, current, counts)
        reach = {current}
        queue = [current]
        for s in queue:
            for g in self.available[s]:
                if r[g] and self.edges[g][1] not in reach:
                    reach.add(self.edges[g][1])
                    queue.append(self.edges[g][1])
        for g, (src, _) in enumerate(self.edges):
            if not all(x in reach for x in src):
                r[g] = 0
        return r


class CoreAllSources(ModelV3):
    """Unsound: step 4 keeps a group only if ALL of its sources are in the unknown core."""
    def normalize(self, current, counts):
        core, static = ModelV3.normalize(self, current, counts)
        if static != -1:
            return core, static
        seen = {current}
        queue = [current]
        for s in queue:
            for g in self.available[s]:
                if core[g] and self.edges[g][1] not in seen:
                    seen.add(self.edges[g][1])
                    queue.append(self.edges[g][1])
        c = bytearray(core)
        for g, (src, _) in enumerate(self.edges):
            if not all(x in seen for x in src):
                c[g] = 0
        return bytes(c), -1


class NoPairs(ModelV3):
    """CONTROL (sound): no u->v / v->u pair cancellation (loop parity is kept: the
    static loop rule needs single-source loop counts <= 1; without parity it is wrong,
    which this test also detects)."""
    def __init__(self, *a):
        ModelV3.__init__(self, *a)
        self.pairs = []


class NoCore(ModelV3):
    """CONTROL (sound): no core extraction (paired counts are kept)."""
    def normalize(self, current, counts):
        paired = bytes(self.reduce(current, counts))
        labels = self.static_labels(paired)
        return paired, labels[current]


CONTROLS = [NoPairs, NoCore]


MUTANTS = [PairShared, SharedLoopRule, SharedLoopIgnored, FirstSourceOnly, TwoWay, Chain, LoopNoParity,
           SharedLoopParity, AllSourcesReachable, CoreAllSources]


def run_mutants(dicts, seed):
    report = {}
    for mutant in MUTANTS:
        found = None
        for k in range(dicts):
            st = run_model(1, seed * 100003 + k, mutant, stop_at_first=True, quiet=True,
                           full_pairs_check=False)
            if st["mismatches"]:
                m = st["mismatches"][0]
                found = {"after_dictionaries": k + 1, "check": m["kind"], "dictionary": m["dictionary"]}
                break
        report[mutant.__name__] = found
    controls = {}
    for control in CONTROLS:     # sound variants must never be flagged
        st = run_model(dicts, seed, control, quiet=True, full_pairs_check=False)
        controls[control.__name__] = {"positions": st["positions"], "nodes": st["nodes"],
                                      "mismatches": len(st["mismatches"])}
    print({"mutants_caught": {k: (v["after_dictionaries"], v["check"]) if v else None
                              for k, v in report.items()},
           "controls": controls}, flush=True)
    return report, controls


# ---------------------------------------------------------------- C++ differential part
def build_harness(out_dir):
    src = HERE / "adversarial" / "ref_canon_harness.cpp"
    binary = Path(out_dir) / "ref_canon_harness"
    subprocess.run(["g++", "-O2", "-march=native", "-std=c++17", "-o", str(binary), str(src),
                    "-lz", "-pthread"], check=True)
    return binary


class Harness:
    def __init__(self, binary, model, workdir):
        self.model = model
        fd, path = tempfile.mkstemp(suffix=".txt", dir=workdir)
        os.write(fd, model.numeric_input(0, model.full_counts))
        os.close(fd)
        self.path = path
        self.p = subprocess.Popen([str(binary), path], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, text=True, bufsize=1)

    def ask(self, mode, cur, counts):
        self.p.stdin.write(f"{mode} {cur} {counts.hex()}\n")
        self.p.stdin.flush()
        if mode == "C":
            out = []
            while True:
                line = self.p.stdout.readline().split()
                if not line:
                    raise RuntimeError("harness died")
                if line[0] == "END":
                    return out
                out.append((int(line[0]), int(line[1]), int(line[2]), int(line[3]), bytes.fromhex(line[4])))
        s, h = self.p.stdout.readline().split()
        return int(s), bytes.fromhex(h)

    def close(self):
        self.p.stdin.close()
        self.p.wait()
        os.unlink(self.path)


def cpp_compare(h, model, cur, counts, stats, tag):
    """R (pairs) on any state; P (no pairs) on pair-reduced states; C on canonical states."""
    mism = stats["mismatches"]
    norm, static = model.normalize(cur, counts)
    s, k = h.ask("R", cur, counts)
    stats["R"] += 1
    if (s, k) != (static, norm):
        mism.append({"mode": "R", "tag": tag, "cur": cur, "counts": counts.hex(), "py": static, "cpp": s})
    po = pairs_only(model, counts)
    norm2, static2 = model.normalize(cur, po)
    s, k = h.ask("P", cur, po)
    stats["P"] += 1
    if (s, k) != (static2, norm2):
        mism.append({"mode": "P", "tag": tag, "cur": cur, "counts": po.hex(), "py": static2, "cpp": s})
    if static == -1:
        out = h.ask("C", cur, norm)
        legal = [g for g in model.available[cur] if norm[g]]
        if [o[0] for o in out] != legal:
            mism.append({"mode": "C-moves", "tag": tag, "cur": cur, "counts": norm.hex()})
        for g, sinc, sref, ok, kk in out:
            stats["C"] += 1
            t, child, cs = model.child(cur, norm, g)
            if not (sinc == sref == cs and ok == 1 and kk == child):
                mism.append({"mode": "C", "tag": tag, "cur": cur, "counts": norm.hex(), "group": g,
                             "inc": sinc, "ref": sref, "py": cs, "ok": ok})
    return norm, static


def random_walk_states(model, rng, cur, counts, length):
    """Canonical states along a random play from (cur, counts)."""
    out = []
    norm, static = model.normalize(cur, counts)
    for _ in range(length):
        if static != -1:
            break
        legal = [g for g in model.available[cur] if norm[g]]
        if not legal:
            break
        g = rng.choice(legal)
        cur, norm, static = model.child(cur, norm, g)
        out.append((cur, norm))
    return out


def run_cpp(states, seed, binary=None, model_class=ModelV3, quiet=False):
    rng = random.Random(seed)
    work = tempfile.mkdtemp(prefix="v3adv_")
    if binary is None:
        binary = build_harness(work)
    stats = {"R": 0, "P": 0, "C": 0, "real_states": 0, "small_states": 0, "real_static": 0,
             "mismatches": []}
    root = HERE.parent
    real = model_class((root / "words_3436.txt").read_bytes(), 3436)
    h = Harness(binary, real, work)
    n = len(real.keys)
    # roots that have a reachable unknown core are the interesting ones
    roots = [real.vertex_of(x) for x in "락낙면가나다마바사아자차카타파하려여녀룽눙윤륜랜낸"
             if real.key(x) in real.vertex]
    half = states // 2
    while stats["real_states"] < half:
        r = rng.random()
        cur = rng.choice(roots) if rng.random() < 0.6 else rng.randrange(n)
        if r < 0.4:          # random subset of the full dictionary
            p = rng.choice((0.02, 0.1, 0.3, 0.6, 0.9))
            counts = bytes(c - sum(rng.random() < p for _ in range(c)) for c in real.full_counts)
            todo = [(cur, counts)]
        else:                # canonical states along random plays (incl. deep ones)
            p = rng.choice((0.0, 0.0, 0.05, 0.3))
            counts = bytes(c - sum(rng.random() < p for _ in range(c)) for c in real.full_counts)
            todo = [(cur, counts)] + random_walk_states(real, rng, cur, counts, rng.randint(1, 60))
        for c_cur, c_counts in todo:
            _, st = cpp_compare(h, real, c_cur, c_counts, stats, "real")
            stats["real_states"] += 1
            stats["real_static"] += st != -1
            if stats["real_states"] % 2000 == 0 and not quiet:
                print({k: v if k != "mismatches" else len(v) for k, v in stats.items()}, flush=True)
    h.close()
    while stats["small_states"] < states - half:
        words = gen_dictionary(rng, rng.choice(KINDS))
        if not words:
            continue
        model = model_class(" ".join(words).encode(), 0)
        h = Harness(binary, model, work)
        for _ in range(30):
            cur = rng.randrange(len(model.keys))
            counts = bytes(c - sum(rng.random() < 0.3 for _ in range(c)) for c in model.full_counts)
            for c_cur, c_counts in [(cur, counts)] + random_walk_states(model, rng, cur, counts, 6):
                cpp_compare(h, model, c_cur, c_counts, stats, words)
                stats["small_states"] += 1
        h.close()
    try:
        for f in Path(work).iterdir():
            f.unlink()
        os.rmdir(work)
    except OSError:
        pass
    stats["mismatch_count"] = len(stats["mismatches"])
    stats["mismatches"] = stats["mismatches"][:5]
    if not quiet:
        print(stats, flush=True)
    return stats


def run_cpp_power(states, seed, binary=None):
    """The C++ comparison must flag Python mutants (shows the comparison has power)."""
    out = {}
    for mutant in (SharedLoopRule, PairShared, SharedLoopParity):
        st = run_cpp(states, seed, binary, mutant, quiet=True)
        out[mutant.__name__] = st["mismatch_count"]
    print({"cpp_vs_python_mutants_mismatches": out}, flush=True)
    return out


def main():
    args = sys.argv[1:]
    binary = None
    if "--harness" in args:
        i = args.index("--harness")
        binary = args[i + 1]
        del args[i:i + 2]
    part = args[0] if args else "model"
    count = int(args[1]) if len(args) > 1 else 500
    seed = int(args[2]) if len(args) > 2 else 1
    if part == "model":
        print({"conv_table_checked": check_conv_table()})
        st = run_model(count, seed)
        if st["mismatches"]:
            print({"FIRST_MISMATCH": st["mismatches"][0]})
            return 1
    elif part == "abstract":
        st = run_abstract(count, seed)
        if st["mismatches"]:
            return 1
    elif part == "exhaustive":
        st = run_exhaustive(count, seed)
        if st["mismatches"]:
            return 1
    elif part == "mutants":
        rep, controls = run_mutants(count, seed)
        if not all(rep.values()) or any(c["mismatches"] for c in controls.values()):
            return 1
    elif part == "cpp-power":
        out = run_cpp_power(count, seed, binary)
        if not all(out.values()):
            return 1
    elif part == "cpp":
        st = run_cpp(count, seed, binary)
        if st["mismatch_count"]:
            return 1
    else:
        raise SystemExit(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
