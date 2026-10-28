#!/usr/bin/env python3
"""Random small-multigraph validation of solver_v3 against a raw word-level
minimax (no reductions at all), with every emitted certificate checked by the
UNMODIFIED verify_v2.py (imported read-only from route-verifier-v2).

usage: random_test.py TRIALS SEED [extra solver args...]
"""
import json, os, random, subprocess, sys, tempfile
from functools import lru_cache
from pathlib import Path

sys.dont_write_bytecode = True
VDIR = '/tmp/claude-0/-home-user-AI-/80ff9426-9f7b-5815-97c0-938f621a9f93/scratchpad/verifier/route-verifier-v2'
sys.path.insert(0, VDIR)
from verify import dueum  # noqa: E402
from verify_v2 import IndependentModelV2, verify_v2  # noqa: E402

HERE = Path(__file__).resolve().parent.parent
SOLVER = str(HERE / 'solver_v3')
V2 = VDIR + '/solver_v2'
# start syllables (no initial-sound change) and some end syllables that DO change
SAFE = list("가다마바사아자차카타파하고도모보소오조초")
FILL = [chr(0xAC00 + 28 * i) for i in range(0, 19 * 21, 7)]  # assorted fillers


MAXW = int(os.environ.get("MAXWORDS", "13"))
DENSE = float(os.environ.get("DENSE", "0"))


CYCLIC = int(os.environ.get("CYCLIC", "0"))


def make_cyclic(rng):
    n = rng.randint(3, 6)
    syl = rng.sample(SAFE, n)
    words = []
    fi = [0]

    def add(a, b):
        words.append(a + FILL[fi[0] % len(FILL)] + b); fi[0] += 1
    for a in syl:
        outs = rng.sample([b for b in syl if b != a], min(n - 1, rng.randint(1, 3)))
        for b in outs:
            for _ in range(1 if rng.random() < 0.7 else 2):
                add(a, b)
            if rng.random() < 0.15:
                add(b, a)  # reciprocal word
        if rng.random() < 0.3:
            for _ in range(1 if rng.random() < 0.6 else 2):
                add(a, a)
    rng.shuffle(words)
    words = words[:MAXW]
    if rng.random() < 0.2:
        words.append(rng.choice(syl))
    return list(dict.fromkeys(words))


def make_dict(rng):
    if CYCLIC:
        return make_cyclic(rng)
    n = rng.randint(1, 6) if not DENSE else rng.randint(3, 7)
    syl = rng.sample(SAFE, n)
    words = []
    fill_i = 0
    budget = rng.randint(1, MAXW) if not DENSE else rng.randint(MAXW // 2, MAXW)
    pairs = [(a, b) for a in syl for b in syl]
    rng.shuffle(pairs)
    for a, b in pairs:
        if len(words) >= budget:
            break
        r = rng.random()
        k = 0 if r < 0.45 - DENSE else 1 if r < 0.8 else 2 if r < 0.93 else 3
        if a != b and rng.random() < 0.25:
            # reciprocal pair emphasis
            k = max(k, 1)
            kk = rng.randint(1, 2)
            for _ in range(kk):
                words.append(b + FILL[fill_i % len(FILL)] + a); fill_i += 1
        for _ in range(k):
            end = b
            # use a dueum-changing ending for '아'->'라' style: 라 (rieul+ㅏ) -> 나 is not
            # in SAFE, so use 려 -> 여? Only if b == '아': '랴'? keep simple: none.
            words.append(a + FILL[fill_i % len(FILL)] + end); fill_i += 1
    if rng.random() < 0.3:  # one-syllable loop word
        words.append(rng.choice(syl))
    if rng.random() < 0.3:  # dueum-changing end: X..력 -> 역 (역 must then be a vertex)
        a = rng.choice(syl)
        words.append(a + FILL[fill_i % len(FILL)] + '력'); fill_i += 1
        if rng.random() < 0.7:
            words.append('역' + FILL[fill_i % len(FILL)] + rng.choice(syl)); fill_i += 1
    words = list(dict.fromkeys(words))
    if not words:
        words = [syl[0] + '나' + syl[0]]
    return words


def raw_value(words, cur, used):
    words = list(words)
    idx = {w: i for i, w in enumerate(words)}
    start = [w[0] for w in words]
    end = [dueum(w[-1]) for w in words]

    @lru_cache(maxsize=None)
    def win(c, mask):
        for i in range(len(words)):
            if not (mask >> i) & 1 and start[i] == c:
                if not win(end[i], mask | (1 << i)):
                    return True
        return False
    mask = 0
    for w in used:
        mask |= 1 << idx[w]
    return win(cur, mask)


def main():
    trials = int(sys.argv[1]); seed = int(sys.argv[2]); extra = sys.argv[3:]
    rng = random.Random(seed)
    stats = {"trials": 0, "W": 0, "L": 0, "static_root": 0, "v2_agree": 0, "proof_nodes": 0,
             "max_proof_nodes": 0, "resolves": 0, "fail": 0}
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        for t in range(trials):
            words = make_dict(rng)
            d = td / 'words.txt'; d.write_text(' '.join(words), encoding='utf-8')
            model = IndependentModelV2(d.read_bytes(), 0)
            init = rng.choice(model.syllables)
            # random legal history walk
            cur = model.vertex[init]; hist = []; usedw = set()
            for _ in range(rng.choice([0, 0, 1, 2, 3])):
                cand = [w for w in model.words if w not in usedw and model.word_endpoints[w][0] == cur]
                if not cand:
                    break
                w = rng.choice(cand); hist.append(w); usedw.add(w); cur = model.word_endpoints[w][1]
            pos = {"initial_syllable": init, "history": hist}
            pp = td / 'pos.json'; pp.write_text(json.dumps(pos, ensure_ascii=False), encoding='utf-8')
            current, counts, used = model.position(pos)
            inp = td / 'in.txt'
            lines = [f"{len(model.syllables)} {len(model.edges)} {current}"]
            for (s, tg), c in zip(model.edges, counts):
                lines.append(f"{s} {tg} {c}")
            inp.write_text('\n'.join(lines) + '\n')
            expect = raw_value(model.words, model.syllables[current], used)
            proof = td / 'proof.jsonl'
            if proof.exists():
                proof.unlink()
            r = subprocess.run([SOLVER, str(inp), '--proof', str(proof), '--seconds', '20', '--tt-mb', '1'] + extra,
                               capture_output=True, text=True)
            if r.returncode != 0:
                print("SOLVER ERROR", words, pos, r.stderr); stats["fail"] += 1; continue
            out = json.loads(r.stdout.strip().splitlines()[-1])
            res = out["result"]
            ok = (res == 'win') == expect and res != 'unknown'
            try:
                vr = verify_v2(d, pp, proof, inp, expected_word_count=0)
                vok = vr["verified"] and (vr["result_for_player_to_move"] == 'W') == expect
            except Exception as ex:  # noqa: BLE001
                vok = False; vr = str(ex)
            r2 = subprocess.run([V2, str(inp), '--seconds', '20'], capture_output=True, text=True)
            try:
                o2 = json.loads(r2.stdout.strip().splitlines()[-1]); stats["v2_agree"] += (o2["result"] == res)
            except Exception:  # noqa: BLE001
                pass
            stats["trials"] += 1
            stats["W" if expect else "L"] += 1
            stats["proof_nodes"] += out["proof_nodes"]
            stats["max_proof_nodes"] = max(stats["max_proof_nodes"], out["proof_nodes"])
            stats["resolves"] += out["emit_resolves"]
            stats["static_root"] += out["mid_calls"] == 0
            if not (ok and vok):
                stats["fail"] += 1
                print("MISMATCH", json.dumps({"words": words, "pos": pos, "expect": expect, "solver": out, "verify": vr},
                                             ensure_ascii=False))
    print(json.dumps(stats))
    return 1 if stats["fail"] else 0


if __name__ == '__main__':
    sys.exit(main())
