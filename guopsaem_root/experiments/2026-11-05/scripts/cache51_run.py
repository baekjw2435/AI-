#!/usr/bin/env python3
"""Proven-cache experiment on the 51 frontier jobs of 8 roots (817 list): baseline vs cumulative cache.
Deterministic budget: --nodes. usage: run.py MODE(base|cache) NODES"""
import json, subprocess, sys, glob, os
from pathlib import Path
X = Path('/tmp/claude-0/-home-user-AI-/a577aae5-294a-5110-9336-05d763879814/scratchpad/cacheexp')
F = Path('/tmp/claude-0/-home-user-AI-/a577aae5-294a-5110-9336-05d763879814/scratchpad/frontier817/w')
mode, nodes = sys.argv[1], sys.argv[2]
P = json.load(open(F / 'plan.json'))
order = sorted(P['endpoints'], key=lambda e: (-len(e['roots']), e['id']))
out = X / mode; out.mkdir(exist_ok=True)
pcs = []
for e in order:
    j = F / 'jobs' / f'e{e["id"]}'
    cmd = ['nice', '-n', '10', str(X / 'solver_v5_cache'), str(j / 'in.txt'), '--seconds', '100000', '--nodes', nodes,
           '--tt-mb', '512', '--threads', '1', '--proof', str(out / f'e{e["id"]}.cert.gz'), '--proof-format', 'v4']
    if mode == 'cache':
        for pc in pcs: cmd += ['--proven-load', pc]
        cmd += ['--proven-save', str(out / f'e{e["id"]}.pc')]
    r = subprocess.run(cmd, capture_output=True, text=True)
    d = json.loads(r.stdout.strip().splitlines()[-1])
    extra = [l for l in r.stderr.splitlines() if l.startswith('{"proven')]
    ver = None
    if d['result'] in ('win', 'loss'):
        v = subprocess.run(['/home/user/AI-/.work/measure/verify_v4', '--dictionary', '/home/user/AI-/basic_root/words_817.txt',
                            '--expected-word-count', '817', '--position', str(j / 'pos.json'), '--proof', str(out / f'e{e["id"]}.cert.gz'),
                            '--input', str(j / 'in.txt')], capture_output=True, text=True)
        vd = json.loads(v.stdout)
        ver = v.returncode == 0 and vd.get('verified') is True and vd.get('state_storage') == 'deflate-exact' and \
            vd.get('result_for_player_to_move') == ('W' if d['result'] == 'win' else 'L')
    if mode == 'cache' and (out / f'e{e["id"]}.pc').exists():
        pcs.append(str(out / f'e{e["id"]}.pc'))
    rec = {'id': e['id'], 'result': d['result'], 'mid_calls': d['mid_calls'], 'seconds': d['seconds'], 'verified': ver,
           'proven': json.loads(extra[0]) if extra else None}
    print(json.dumps(rec, ensure_ascii=False), flush=True)
