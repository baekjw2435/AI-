#!/usr/bin/env python3
"""report.py DIR: per-position tables (mid_calls default vs model) for roots.jsonl, frontier.jsonl,
myeon.jsonl in DIR, with geometric means; positions whose default mid_calls were used to tune the
mapping (dev: 낭 죽 퇴 율) are reported separately."""
import json, sys, math, os, collections
D = sys.argv[1]
DEV = {'낭', '죽', '퇴', '율'}
def load(f):
    R = collections.defaultdict(dict)
    if os.path.exists(f):
        for l in open(f):
            d = json.loads(l); R[d['tag']][d['input']] = d
    return R
def nm(p):
    return os.path.basename(os.path.dirname(p)) if p.endswith('in.txt') else os.path.basename(p)[:-4]
def gm(xs): return math.exp(sum(map(math.log, xs)) / len(xs)) if xs else float('nan')
R = load(os.path.join(D, 'roots.jsonl'))
print('## 817 roots (mid_calls to solve; model trained on the other fold)')
rows = []
for t in ('mlA', 'mlB'):
    for inp, d in R[t].items():
        b = R['init1'][inp]
        rows.append((nm(inp), t, b['result'], b['mid_calls'], d['result'], d['mid_calls'], d['mid_calls'] / b['mid_calls'], d.get('verify_ok')))
rows.sort(key=lambda r: r[3])
for r in rows: print('%s %s base=%s %d model=%s %d ratio=%.3f verified=%s' % r)
allr = [r[6] for r in rows]; held = [r[6] for r in rows if r[0] not in DEV]
print('geomean all 28: %.3f  | excluding dev 낭죽퇴율 (24): %.3f | fold B (model A, 13): %.3f | fold A w/o dev (11): %.3f' % (
    gm(allr), gm(held), gm([r[6] for r in rows if r[1] == 'mlA']), gm([r[6] for r in rows if r[1] == 'mlB' and r[0] not in DEV])))
print('better: %d, worse: %d; total mid default %d vs model %d' % (sum(x < 1 for x in allr), sum(x > 1 for x in allr), sum(r[3] for r in rows), sum(r[5] for r in rows)))
F = load(os.path.join(D, 'frontier.jsonl'))
print('\n## 817 frontier jobs solved by the default within 60 s (tt-mb 512; model A)')
rows = []
for inp, d in F['mlA'].items():
    b = F['init1'][inp]
    rows.append((nm(inp), b['mid_calls'], d['result'], d['mid_calls'], d['mid_calls'] / b['mid_calls'], d.get('verify_ok'), b['result']))
rows.sort(key=lambda r: r[1])
for r in rows: print('%s base=%d model=%s %d ratio=%.3f verified=%s (base %s)' % r)
solved = [r for r in rows if r[2] != 'unknown']
print('n=%d, solved by model within 3x cap: %d; geomean ratio (unsolved counted at the cap, a lower bound) %.3f; better %d worse %d' % (
    len(rows), len(solved), gm([r[4] for r in rows]), sum(r[4] < 1 for r in rows), sum(r[4] > 1 for r in rows)))
M = load(os.path.join(D, 'myeon.jsonl'))
print('\n## 3,436-word 면 first moves c_0..c_14 after --nodes 2,000,000 (final root pn/dn and root children proven)')
for t in sorted(M):
    for inp, d in sorted(M[t].items(), key=lambda x: int(nm(x[0])[2:])):
        print('%s %s result=%s pn=%d dn=%d root_children=%d proven_win_for_child_mover=%d proven_loss=%d' % (
            t, nm(inp), d['result'], d['pn'], d['dn'], d['rc_total'], d['rc_win'], d['rc_loss']))
