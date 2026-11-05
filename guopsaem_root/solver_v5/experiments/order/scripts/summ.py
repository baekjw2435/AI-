#!/usr/bin/env python3
"""summ.py FILE.jsonl [base_tag]: per-position mid_calls ratio vs base tag and geometric means
(only positions solved by both; an unsolved run within the cap counts as cap/base = lower bound)."""
import json, sys, math, os, collections
f = sys.argv[1]; base = sys.argv[2] if len(sys.argv) > 2 else 'init1'
R = collections.defaultdict(dict)
for l in open(f):
    d = json.loads(l); R[d['tag']][d['input']] = d
def name(p): return os.path.basename(os.path.dirname(p)) + '/' + os.path.basename(p) if 'jobs' in p else os.path.basename(p)
B = R[base]
for t, rr in R.items():
    if t == base: continue
    lr = []; worst = best = None; unsolved = 0
    for inp, d in rr.items():
        if inp not in B or B[inp]['result'] == 'unknown': continue
        r = d['mid_calls'] / B[inp]['mid_calls']
        if d['result'] == 'unknown': unsolved += 1
        lr.append((math.log(r), name(inp), r, d['result']))
    if not lr: continue
    lr.sort()
    gm = math.exp(sum(x[0] for x in lr) / len(lr))
    print(f"{t:14s} n={len(lr):2d} geomean_ratio={gm:.3f} unsolved_at_cap={unsolved} best={lr[0][1]}:{lr[0][2]:.2f} worst={lr[-1][1]}:{lr[-1][2]:.2f}{'(cap)' if lr[-1][3]=='unknown' else ''}")
