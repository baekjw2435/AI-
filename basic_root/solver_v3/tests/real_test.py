#!/usr/bin/env python3
"""Random real-dictionary positions (random legal histories from 역): solver_v2 vs
solver_v3 results, every v3 certificate checked by verify_v2. usage: real_test.py N SEED MINPLY MAXPLY [solver args]"""
import json, random, subprocess, sys, tempfile
from pathlib import Path
sys.dont_write_bytecode = True
VDIR = '/tmp/claude-0/-home-user-AI-/80ff9426-9f7b-5815-97c0-938f621a9f93/scratchpad/verifier/route-verifier-v2'
sys.path.insert(0, VDIR)
from verify_v2 import IndependentModelV2, verify_v2
DICT = VDIR + '/words.txt'
HERE = Path(__file__).resolve().parent.parent
n, seed, lo, hi = map(int, sys.argv[1:5]); extra = sys.argv[5:]
rng = random.Random(seed)
m = IndependentModelV2(open(DICT, 'rb').read())
st = {"n": 0, "agree": 0, "v2_unknown": 0, "v3_unknown": 0, "verified": 0, "fail": 0, "W": 0, "L": 0, "nonstatic": 0, "v2_s": 0.0, "v3_s": 0.0}
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    for t in range(n):
        cur = m.vertex['역']; hist = []; used = set()
        for _ in range(rng.randint(lo, hi)):
            c = [w for w in m.words if w not in used and m.word_endpoints[w][0] == cur]
            if not c: break
            w = rng.choice(c); hist.append(w); used.add(w); cur = m.word_endpoints[w][1]
        pos = {"initial_syllable": "역", "history": hist}
        pp = td / 'p.json'; pp.write_text(json.dumps(pos, ensure_ascii=False), encoding='utf-8')
        inp = td / 'in.txt'
        subprocess.run([sys.executable, str(HERE / 'tools/mkinput.py'), DICT, str(pp), str(inp)], check=True)
        pf = td / 'proof.jsonl'
        r3 = subprocess.run([str(HERE / 'solver_v3'), str(inp), '--seconds', '30', '--proof', str(pf), '--tt-mb', '64'] + extra, capture_output=True, text=True)
        r2 = subprocess.run([VDIR + '/solver_v2', str(inp), '--seconds', '30', '--nodes', '3000000'], capture_output=True, text=True)
        try:
            o3 = json.loads(r3.stdout.strip().splitlines()[-1]); o2 = json.loads(r2.stdout.strip().splitlines()[-1])
        except Exception as ex:
            print("ERR", pos, r3.stderr, r2.stderr); st["fail"] += 1; continue
        st["n"] += 1; st["v2_s"] += o2["seconds"]; st["v3_s"] += o3["seconds"]
        st["nonstatic"] += o3["mid_calls"] > 0
        if o2["result"] == "unknown": st["v2_unknown"] += 1
        if o3["result"] == "unknown": st["v3_unknown"] += 1; continue
        st["W" if o3["result"] == "win" else "L"] += 1
        if o2["result"] != "unknown":
            if o2["result"] == o3["result"]: st["agree"] += 1
            else: st["fail"] += 1; print("DISAGREE", json.dumps(pos, ensure_ascii=False), o2, o3)
        try:
            v = verify_v2(DICT, pp, pf, inp)
            if v["verified"] and (v["result_for_player_to_move"] == 'W') == (o3["result"] == 'win'): st["verified"] += 1
            else: st["fail"] += 1; print("VERIFY-MISMATCH", pos, v)
        except Exception as ex:
            st["fail"] += 1; print("VERIFY-FAIL", json.dumps(pos, ensure_ascii=False), ex)
st["v2_s"] = round(st["v2_s"], 2); st["v3_s"] = round(st["v3_s"], 2)
print(json.dumps(st))
