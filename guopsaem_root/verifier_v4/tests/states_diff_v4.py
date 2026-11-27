#!/usr/bin/env python3
"""Differential check of the two independent model implementations: for every node the C++
verifier expands (its --dump-states output: id, vertex, static label, SHA-256 of the state),
the state replayed with ModelV3 (verify_v3.py) must have the same vertex, static label and
bytes.  Also checks that the set of expanded nodes is the same.
Usage: states_diff_v4.py VERIFY_CPP DICT WORD_COUNT POS.json PROOF INPUT.txt DUMPFILE"""
import gzip
import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2] / "verifier_v3"))
from verify_v3 import ModelV3  # noqa: E402

cpp, dic, nwords, posf, proof, inp, dumpf = sys.argv[1:8]
r = subprocess.run([cpp, "--dictionary", dic, "--expected-word-count", nwords, "--position", posf, "--proof", proof,
                    "--input", inp, "--dump-states", dumpf], capture_output=True, text=True)
assert r.returncode == 0, r.stdout
dumped = {}
with open(dumpf) as f:
    for line in f:
        i, v, st, h = line.split()
        dumped[int(i)] = (int(v), int(st), h)
m = ModelV3(Path(dic).read_bytes(), int(nwords))
with open(proof, "rb") as f:
    gz = f.read(2) == b"\x1f\x8b"
with (gzip.open(proof, "rb") if gz else open(proof, "rb")) as f:
    f.readline()
    moves = [json.loads(line)["m"] for line in f]
cur, counts, _ = m.position(json.loads(Path(posf).read_text(encoding="utf-8")))
root = len(moves) - 1
state = {root: (cur, m.normalize(cur, counts)[0])}
stack = [root]
checked = 0
while stack:
    i = stack.pop()
    v, c = state[i]
    canon, st = m.normalize(v, c)
    assert canon == c
    assert dumped[i] == (v, st, hashlib.sha256(c).hexdigest()), (i, dumped[i], v, st)
    checked += 1
    for g, ch in moves[i]:
        if ch not in state:
            tv, tc, _ = m.child(v, c, g)
            state[ch] = (tv, tc)
            stack.append(ch)
assert checked == len(dumped)
Path(dumpf).unlink()
print(json.dumps({"nodes_compared": checked, "ok": True}))
