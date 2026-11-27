# How solve time grows with the core size: random sub-dictionaries of the 구없샘 core (measurement only, no certificates)
import sys, json, random, subprocess, re
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, '/home/user/AI-/guopsaem_root/verifier_v3')
from verify_v3 import ModelV3
G = '/home/user/AI-/guopsaem_root/'; D = sys.argv[1]; SEC = float(sys.argv[2])
m = ModelV3(open(G + 'words_3683.txt', 'rb').read(), 3683)
cur = m.vertex_of('객')
core, _ = m.normalize(cur, m.full_counts)
jobs = []
for p in (0.2, 0.3, 0.4, 0.5, 0.6, 0.7):
    for seed in range(4):
        rnd = random.Random(1000 * int(p * 10) + seed)
        cnt = bytes(sum(1 for _ in range(c) if rnd.random() < p) for c in core)
        red, st = m.normalize(cur, cnt)
        name = f'p{int(p*100)}_s{seed}'
        open(f'{D}/{name}.txt', 'wb').write(m.numeric_input(cur, cnt))
        jobs.append((name, p, sum(red), sum(1 for c in red if c), st))
def run(j):
    name, p, words, groups, st = j
    if st != -1:
        return dict(name=name, p=p, core_words=words, result='static', seconds=0.0)
    out = subprocess.run(['/home/user/AI-/.work/measure/solver_v5', f'{D}/{name}.txt', '--seconds', str(SEC), '--tt-mb', '1024', '--threads', '1'],
                         capture_output=True, text=True).stdout
    r = json.loads(out.strip().splitlines()[-1])
    return dict(name=name, p=p, core_words=words, core_groups=groups, result=r.get('result'), seconds=round(r.get('seconds', 0), 2),
                nodes=r.get('mid_calls'))
with ThreadPoolExecutor(3) as ex:
    res = list(ex.map(run, jobs))
json.dump(res, open(f'{D}/scale_result.json', 'w'), indent=1)
for r in res: print(r)
