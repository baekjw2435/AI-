#!/usr/bin/env python3
"""Solver-generated certificates on random toy dictionaries: verify_v2 vs verify_fast
(compat+legacy dueum, and hardened/standard with pin off) acceptance and verdict, plus
random single-point mutations of every certificate; raw word-level minimax as truth."""
import json, random, subprocess, sys, tempfile
from functools import lru_cache
from pathlib import Path
S = Path("/home/user/AI-/.work")
V2 = S / "verifier/route-verifier-v2"
sys.path.insert(0, str(V2)); sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify as v1mod, verify_v2 as v2mod, verify_fast as vf
rng = random.Random(2610)
tmp = Path(tempfile.mkdtemp(dir=Path(__file__).resolve().parent))
stats = {"certificates": 0, "mutations": 0, "accept_mismatch": 0, "verdict_mismatch": 0,
         "raw_mismatch": 0, "mutation_accepted_by_v2": 0, "mutation_accepted_by_fast": 0,
         "mutation_disagree": 0, "unknown_skipped": 0}


def run(fn, *a, **k):
    try:
        return "ACCEPT:" + fn(*a, **k)["result_for_player_to_move"]
    except (v1mod.VerificationError, vf.VerificationError, OSError, EOFError, UnicodeError):
        return "reject"


for case in range(250):
    letters = "가나다마바사"[:rng.randrange(2, 7)]
    words = sorted({a + "아" * rng.choice((0, 0, 0, 1, 2)) + b for a in letters for b in letters
                    if rng.random() < 0.45}) or ["가나"]
    words = words[:15]
    first = rng.choice(words)
    history = [first] if rng.random() < 0.5 else []
    (tmp / "w.txt").write_text(" ".join(words), encoding="utf-8")
    pos = {"initial_syllable": first[0], "history": history}
    (tmp / "p.json").write_text(json.dumps(pos, ensure_ascii=False), encoding="utf-8")
    m = v2mod.IndependentModelV2((tmp / "w.txt").read_bytes(), 0)
    cur, cnt, used = m.position(pos)
    (tmp / "in.txt").write_text(f"{len(m.syllables)} {len(m.edges)} {cur}\n" +
                                "".join(f"{a} {b} {c}\n" for (a, b), c in zip(m.edges, cnt)))
    out = subprocess.run([str(V2 / "solver_v2"), str(tmp / "in.txt"), "--seconds", "5", "--nodes", "200000",
                          "--proof", str(tmp / "proof.jsonl")], capture_output=True, text=True)
    res = json.loads(out.stdout)
    if res["result"] == "unknown":
        stats["unknown_skipped"] += 1
        continue

    @lru_cache(None)
    def raw(c, avail):
        return any(not raw(w[-1], avail & ~(1 << i)) for i, w in enumerate(words) if avail >> i & 1 and w[0] == c)
    truth = "ACCEPT:" + ("W" if raw(m.syllables[cur], sum(1 << i for i, w in enumerate(words) if w not in used)) else "L")
    args = (tmp / "w.txt", tmp / "p.json", tmp / "proof.jsonl", tmp / "in.txt", 0)
    a = run(v2mod.verify_v2, *args)
    b = run(vf.verify_fast, *args, hardened=False, legacy_dueum=True)
    c = run(vf.verify_fast, *args, hardened=True, dictionary_sha256="", engine="c")
    stats["certificates"] += 1
    stats["accept_mismatch"] += not (a.startswith("ACCEPT") and b.startswith("ACCEPT") and c.startswith("ACCEPT"))
    stats["verdict_mismatch"] += not (a == b == c)
    stats["raw_mismatch"] += a != truth
    lines = (tmp / "proof.jsonl").read_text().splitlines()
    nodes = [json.loads(l) for l in lines[1:]]
    for trial in range(8):
        mutated = json.loads(json.dumps(nodes))
        k = rng.randrange(len(mutated)); node = mutated[k]; kind = rng.randrange(5)
        if kind == 0:
            node["r"] = "L" if node["r"] == "W" else "W"
        elif kind == 1 and node["m"]:
            node["m"].pop(rng.randrange(len(node["m"])))
        elif kind == 2:
            cc = bytearray.fromhex(node["c"]); g = rng.randrange(len(cc)); cc[g] = (cc[g] + rng.choice((1, 255))) % 256
            node["c"] = cc.hex()
        elif kind == 3 and node["m"]:
            mv = rng.choice(node["m"]); mv[1] = rng.randrange(max(1, k))
        elif kind == 4:
            node["v"] = rng.randrange(len(m.syllables))
        if mutated == nodes:
            continue
        (tmp / "mut.jsonl").write_text(lines[0] + "\n" + "\n".join(json.dumps(x) for x in mutated) + "\n")
        margs = (tmp / "w.txt", tmp / "p.json", tmp / "mut.jsonl", tmp / "in.txt", 0)
        ma = run(v2mod.verify_v2, *margs)
        mb = run(vf.verify_fast, *margs, hardened=False, legacy_dueum=True)
        mc = run(vf.verify_fast, *margs, hardened=True, dictionary_sha256="", engine="c")
        stats["mutations"] += 1
        stats["mutation_disagree"] += not (ma == mb == mc)
        # a mutation may be harmless (e.g. redirect to an identical node); a false verdict is not
        stats["mutation_accepted_by_v2"] += ma.startswith("ACCEPT") and ma != truth
        stats["mutation_accepted_by_fast"] += mc.startswith("ACCEPT") and mc != truth
print(json.dumps(stats))
