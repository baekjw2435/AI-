#!/usr/bin/env python3
"""Ordering check with real time: for each root, --init 1 (current default) and --init 9 run AT THE SAME TIME
(one core each, same load). Records search seconds, certificate emission seconds, C++ verification seconds,
wall seconds, mid_calls, decided/correct. Resumable (skips roots already in the output).
usage: bench_order_time.py ROOTS_FILE OUT.jsonl NODE_CAP"""
import json, os, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, '/home/user/AI-/guopsaem_root/verifier_v3')
from verify_v3 import ModelV3
X = '/tmp/claude-0/-home-user-AI-/a577aae5-294a-5110-9336-05d763879814/scratchpad/order'
solved = json.load(open('/tmp/claude-0/-home-user-AI-/a577aae5-294a-5110-9336-05d763879814/scratchpad/v5cmp/b817/solved.json'))
roots_file, out_file, cap = sys.argv[1], sys.argv[2], sys.argv[3]
roots = open(roots_file, encoding='utf-8').read().split()
m = ModelV3(open('/home/user/AI-/basic_root/words_817.txt', 'rb').read(), 817)
done = set()
if os.path.exists(out_file):
    for l in open(out_file, encoding='utf-8'):
        d = json.loads(l); done.add((d['root'], d['init']))
os.makedirs(f'{X}/tm', exist_ok=True)

def run(s, mode):
    pos, inp, out = f'{X}/tm/{s}.json', f'{X}/tm/{s}.txt', f'{X}/tm/{s}_{mode}.jsonl.gz'
    t0 = time.time()
    r = subprocess.run([f'{X}/solver_v5_order', inp, '--seconds', '100000', '--nodes', cap, '--tt-mb', '512',
                        '--threads', '1', '--init', mode, '--proof', out, '--proof-format', 'v4'], capture_output=True, text=True)
    t1 = time.time()
    d = json.loads(r.stdout.strip().splitlines()[-1])
    rec = {'root': s, 'init': mode, 'result': d['result'], 'mid_calls': d['mid_calls'], 'search_s': round(d['seconds'], 2),
           'emit_s': round(d.get('emit_seconds', 0), 2), 'solver_wall_s': round(t1 - t0, 2), 'verify_s': 0.0, 'correct': None}
    if d['result'] in ('win', 'loss'):
        v = subprocess.run(['/home/user/AI-/.work/measure/verify_v4', '--dictionary', '/home/user/AI-/basic_root/words_817.txt',
                            '--expected-word-count', '817', '--position', pos, '--proof', out, '--input', inp],
                           capture_output=True, text=True)
        vd = json.loads(v.stdout)
        rec['verify_s'] = round(time.time() - t1, 2)
        rec['correct'] = v.returncode == 0 and vd.get('verified') is True and vd.get('state_storage') == 'deflate-exact' and \
            vd.get('result_for_player_to_move') == ('W' if d['result'] == 'win' else 'L') == solved[s][0]
        rec['proof_states'] = vd.get('checked_certificate_states')
    rec['total_s'] = round(rec['solver_wall_s'] + rec['verify_s'], 2)
    if os.path.exists(out):
        os.remove(out)
    return rec

for s in roots:
    if (s, '1') in done and (s, '9') in done:
        continue
    pos = {'initial_syllable': s, 'history': []}
    json.dump(pos, open(f'{X}/tm/{s}.json', 'w'), ensure_ascii=False)
    c, k, _ = m.position(pos)
    open(f'{X}/tm/{s}.txt', 'wb').write(m.numeric_input(c, k))
    with ThreadPoolExecutor(2) as ex:
        recs = list(ex.map(lambda md: run(s, md), ['1', '9']))
    with open(out_file, 'a', encoding='utf-8') as f:
        for rec in recs:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
