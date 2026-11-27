# Same, but every vertex keeps at least one non-loop word out (like the real core: no dead ends), so the sub-cores stay hard-type.
import sys, json, random, subprocess
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, '/home/user/AI-/guopsaem_root/verifier_v3')
from verify_v3 import ModelV3
G = '/home/user/AI-/guopsaem_root/'; D = sys.argv[1]; SEC = float(sys.argv[2])
m = ModelV3(open(G + 'words_3683.txt', 'rb').read(), 3683)
cur = m.vertex_of('객')
core, _ = m.normalize(cur, m.full_counts)
V = {u for g, c in enumerate(core) if c for u in m.edges[g][0]}
jobs = []
for p in (0.15, 0.2, 0.25, 0.3, 0.4, 0.5):
    for seed in range(4):
        rnd = random.Random(7000 + int(p * 100) * 10 + seed)
        cnt = bytearray(sum(1 for _ in range(c) if rnd.random() < p) for c in core)
        for v in sorted(V):
            outs = [g for g, c in enumerate(core) if c and v in m.edges[g][0] and m.edges[g][1] != v]
            if outs and not any(cnt[g] for g in outs):
                cnt[rnd.choice(outs)] += 1
        red, st = m.normalize(cur, bytes(cnt))
        name = f'q{int(p*100)}_s{seed}'
        open(f'{D}/{name}.txt', 'wb').write(m.numeric_input(cur, bytes(cnt)))
        jobs.append((name, p, sum(red), sum(1 for c in red if c), st))
def run(j):
    name, p, words, groups, st = j
    if st != -1:
        return dict(name=name, p=p, result='static')
    out = subprocess.run(['/home/user/AI-/.work/measure/solver_v5', f'{D}/{name}.txt', '--seconds', str(SEC), '--tt-mb', '1024', '--threads', '1'],
                         capture_output=True, text=True).stdout
    r = json.loads(out.strip().splitlines()[-1])
    return dict(name=name, p=p, core_words=words, core_groups=groups, result=r.get('result'), seconds=round(r.get('seconds', 0), 2), nodes=r.get('mid_calls'))
with ThreadPoolExecutor(3) as ex:
    res = list(ex.map(run, jobs))
json.dump(res, open(f'{D}/scale2_result.json', 'w'), indent=1)
for r in res: print(r)
