#!/usr/bin/env python3
"""gen3436.py OUTDIR N SEED [DMIN DMAX]: random deeper 3,436-word positions below 면's first moves (c_0..c_14 json):
from a randomly chosen c_k, play DMIN..DMAX (default 6..14) random words (each from a group in the canonical core, so the
game stays non-trivial), stop if the position becomes static. Writes OUTDIR/g<i>.json and g<i>.txt."""
import json, random, sys, os
sys.path.insert(0, '/home/user/AI-/guopsaem_root/verifier_v3')
from verify_v3 import ModelV3
out, n, seed = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
DMIN, DMAX = (int(sys.argv[4]), int(sys.argv[5])) if len(sys.argv) > 5 else (6, 14)
os.makedirs(out, exist_ok=True)
m = ModelV3(open('/home/user/AI-/guopsaem_root/words_3436.txt', 'rb').read(), 3436)
rng = random.Random(seed)
bygroup = {}
for w in m.words: bygroup.setdefault(m.word_group(w), []).append(w)
made = 0; tries = 0
while made < n and tries < 50 * n:
    tries += 1
    k = rng.randrange(15)
    if k == 3: continue  # 면플란넬: static
    pos = json.load(open(f'/home/user/AI-/.work/g/myeon/c_{k}.json'))
    depth = rng.randint(DMIN, DMAX); ok = True
    for _ in range(depth):
        cur, counts, used = m.position(pos)
        norm, st = m.normalize(cur, counts)
        if st != -1: ok = False; break
        cand = [g for g in m.available[cur] if norm[g]]
        g = rng.choice(cand)
        words = [w for w in bygroup[g] if w not in used and w[0] in m.keys[cur]]
        pos = {'initial_syllable': pos['initial_syllable'], 'history': pos['history'] + [rng.choice(words)]}
    if not ok: continue
    cur, counts, used = m.position(pos)
    if m.normalize(cur, counts)[1] != -1: continue
    json.dump(pos, open(f'{out}/g{made}.json', 'w'), ensure_ascii=False)
    open(f'{out}/g{made}.txt', 'wb').write(m.numeric_input(cur, counts))
    made += 1
print(made, 'positions')
