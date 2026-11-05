#!/usr/bin/env python3
"""bench.py OUT.jsonl TAG CAPFACTOR INPUT... -- [solver options]
Runs the order solver (single thread, nice 10, one at a time) on each input and appends
{"tag","input","result","mid_calls","pn","dn","rc_*"} lines to OUT.jsonl. Inputs already
present for TAG are skipped. CAPFACTOR>0 caps --nodes at CAPFACTOR x the default's mid_calls
(read from the same OUT file, tag 'init1'); results above the cap are reported as unknown."""
import json, os, subprocess, sys
VERIFIER = '/home/user/AI-/.work/measure/verify_v4'
SOLVER = os.environ.get('SOLVER', '/tmp/claude-0/-home-user-AI-/a577aae5-294a-5110-9336-05d763879814/scratchpad/wf2/order/solver_order')
out, tag, cap = sys.argv[1], sys.argv[2], float(sys.argv[3])
rest = sys.argv[4:]
k = rest.index('--')
inputs, opts = rest[:k], rest[k + 1:]
done = {}
if os.path.exists(out):
    for l in open(out):
        d = json.loads(l); done[(d['tag'], d['input'])] = d
for inp in inputs:
    if (tag, inp) in done: continue
    o = list(opts)
    if cap > 0 and ('init1', inp) in done and '--nodes' not in o:
        o += ['--nodes', str(int(cap * done[('init1', inp)]['mid_calls']) + 1024)]
    if '--seconds' not in o: o += ['--seconds', '1200']
    if '--tt-mb' not in o: o += ['--tt-mb', '1024']
    proof = None
    if os.environ.get('PROOF'):
        proof = os.path.join(os.environ['PROOF'], 'p.jsonl.gz')
        o += ['--proof', proof, '--proof-format', 'v4']
    r = subprocess.run(['nice', '-n', '10', SOLVER, inp, '--threads', '1'] + o, capture_output=True, text=True)
    try: d = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception: print('FAIL', inp, r.stderr[-500:], file=sys.stderr); continue
    rec = {'tag': tag, 'input': inp, 'opts': o}
    for f in ('result', 'reason', 'mid_calls', 'pn', 'dn', 'proof_nodes', 'proof_error', 'rc_total', 'rc_win', 'rc_loss', 'seconds'):
        rec[f] = d.get(f)
    if proof and d.get('result') in ('win', 'loss'):
        pos = inp[:-4] + '.json' if os.path.exists(inp[:-4] + '.json') else os.path.join(os.path.dirname(inp), 'pos.json')
        v = subprocess.run(['nice', '-n', '10', VERIFIER, '--dictionary', os.environ['DICT'], '--expected-word-count', os.environ['WC'],
                            '--position', pos, '--proof', proof, '--input', inp], capture_output=True, text=True)
        try: vd = json.loads(v.stdout)
        except Exception: vd = {}
        want = 'W' if d['result'] == 'win' else 'L'
        rec['verify'] = {'exit': v.returncode, 'verified': vd.get('verified'), 'result': vd.get('result_for_player_to_move', vd.get('result')),
                         'state_storage': vd.get('state_storage'), 'proof_nodes': d.get('proof_nodes')}
        rec['verify_ok'] = (v.returncode == 0 and vd.get('verified') is True and rec['verify']['state_storage'] == 'deflate-exact'
                            and rec['verify']['result'] in (want, d['result']))
        os.remove(proof)
    with open(out, 'a') as fh: fh.write(json.dumps(rec, ensure_ascii=False) + '\n')
    print(tag, os.path.basename(os.path.dirname(inp)) + '/' + os.path.basename(inp), rec['result'], rec['mid_calls'], round(rec['seconds'], 1), 'verify_ok=%s' % rec.get('verify_ok'), flush=True)
