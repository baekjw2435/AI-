#!/usr/bin/env python3
"""children.py POSITION.json OUTDIR PREFIX : one child position per legal reduced group
(one representative unused word per group); writes OUTDIR/PREFIX_<k>.json and .txt and prints a TSV."""
import os, json, sys
sys.dont_write_bytecode = True
sys.path.insert(0, os.environ.get('ROUTE_VERIFIER_DIR', '/tmp/claude-0/-home-user-AI-/80ff9426-9f7b-5815-97c0-938f621a9f93/scratchpad/verifier/route-verifier-v2'))
from verify_v2 import IndependentModelV2
D = os.environ.get('ROUTE_DICTIONARY', '/tmp/claude-0/-home-user-AI-/80ff9426-9f7b-5815-97c0-938f621a9f93/scratchpad/basic_root.txt')
m = IndependentModelV2(open(D, 'rb').read())
pos = json.load(open(sys.argv[1], encoding='utf-8')); out = sys.argv[2]; pre = sys.argv[3]
cur, counts, used = m.position(pos)
if pos.get("initial_used_words"):
    sys.exit("children.py: initial_used_words is not supported; positions must be history-only")
core, st = m.normalize(cur, counts)
if st != -1:
    print("static", st); sys.exit()
for k, g in enumerate(gg for gg in m.outgoing[cur] if core[gg]):
    w = sorted(x for x in m.words if m.word_endpoints[x] == m.edges[g] and x not in used)[0]
    p = {"initial_syllable": pos["initial_syllable"], "history": pos["history"] + [w]}
    json.dump(p, open(f"{out}/{pre}_{k}.json", 'w', encoding='utf-8'), ensure_ascii=False)
    c2, cnt2, _ = m.position(p)
    open(f"{out}/{pre}_{k}.txt", 'w').write('\n'.join([f"{len(m.syllables)} {len(m.edges)} {c2}"] + [f"{s} {t} {c}" for (s, t), c in zip(m.edges, cnt2)]) + '\n')
    print(f"{pre}_{k}\t{g}\t{w}\t{'>'.join(p['history'])}")
