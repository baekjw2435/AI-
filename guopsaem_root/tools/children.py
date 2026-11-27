#!/usr/bin/env python3
"""children.py DICT WORD_COUNT POSITION.json OUTDIR PREFIX
One child position per legal reduced group at POSITION (one representative unused
word per group); writes OUTDIR/PREFIX_<k>.json and .txt (solver_v4 input) and prints a TSV."""
import json, sys
from pathlib import Path
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'verifier_v3'))
from verify_v3 import ModelV3  # noqa: E402
d, n, posf, out, pre = sys.argv[1:6]
m = ModelV3(open(d, 'rb').read(), int(n))
pos = json.load(open(posf, encoding='utf-8'))
if pos.get("initial_used_words"):
    sys.exit("children.py: initial_used_words is not supported; positions must be history-only")
cur, counts, used = m.position(pos)
core, st = m.normalize(cur, counts)
if st != -1:
    print("static", st); sys.exit()
for k, g in enumerate(gg for gg in m.available[cur] if core[gg]):
    w = sorted(x for x in m.words if m.word_group(x) == g and x not in used)[0]
    p = {"initial_syllable": pos["initial_syllable"], "history": pos["history"] + [w]}
    json.dump(p, open(f"{out}/{pre}_{k}.json", 'w', encoding='utf-8'), ensure_ascii=False)
    c2, cnt2, _ = m.position(p)
    open(f"{out}/{pre}_{k}.txt", 'wb').write(m.numeric_input(c2, cnt2))
    print(f"{pre}_{k}\t{g}\t{w}\t{'>'.join(p['history'])}")
