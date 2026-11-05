#!/usr/bin/env python3
"""mid_calls to solve the 28 small 817 roots with --init modes (deterministic), certificates verified."""
import json, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
X = '/tmp/claude-0/-home-user-AI-/a577aae5-294a-5110-9336-05d763879814/scratchpad/order'
S = '/tmp/claude-0/-home-user-AI-/a577aae5-294a-5110-9336-05d763879814/scratchpad/v5cmp/b817'
solved = json.load(open(f'{S}/solved.json'))
roots = [s for s, (r, n) in sorted(solved.items(), key=lambda x: x[1][1]) if n <= 120000]
modes = sys.argv[1].split(',')
cap = sys.argv[2]

def run(job):
    s, mode = job
    out = f'{X}/c_{s}_{mode}.jsonl.gz'
    r = subprocess.run(['nice', '-n', '12', f'{X}/solver_v5_order', f'{S}/{s}.txt', '--seconds', '100000', '--nodes', cap,
                        '--tt-mb', '512', '--threads', '1', '--init', mode, '--proof', out, '--proof-format', 'v4'],
                       capture_output=True, text=True)
    d = json.loads(r.stdout.strip().splitlines()[-1])
    ok = None
    if d['result'] in ('win', 'loss'):
        v = subprocess.run(['/home/user/AI-/.work/measure/verify_v4', '--dictionary', '/home/user/AI-/basic_root/words_817.txt',
                            '--expected-word-count', '817', '--position', f'{S}/{s}.json', '--proof', out, '--input', f'{S}/{s}.txt'],
                           capture_output=True, text=True)
        vd = json.loads(v.stdout)
        ok = v.returncode == 0 and vd.get('verified') is True and vd.get('state_storage') == 'deflate-exact' and \
            vd.get('result_for_player_to_move') == ('W' if d['result'] == 'win' else 'L') == solved[s][0]
        subprocess.run(['rm', '-f', out])
    return s, mode, d['result'], d['mid_calls'], ok

jobs = [(s, m) for s in roots for m in modes]
with ThreadPoolExecutor(2) as ex:
    for s, mode, res, mid, ok in ex.map(run, jobs):
        print(json.dumps({'root': s, 'init': mode, 'result': res, 'mid_calls': mid, 'verified_correct': ok}, ensure_ascii=False), flush=True)
