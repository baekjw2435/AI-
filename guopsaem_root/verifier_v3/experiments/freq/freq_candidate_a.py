#!/usr/bin/env python3
"""How often would reviewer candidate (A) shrink canonical states? (measurement only)
(A): in a state, a shared group whose sources reachable from the current vertex reduce to ONE vertex is
treated as single-source for pair cancellation / loop parity in that state."""
import random, sys, collections
sys.path.insert(0, '/home/user/AI-/guopsaem_root/verifier_v3')
from verify_v3 import ModelV3
m = ModelV3(open('/home/user/AI-/guopsaem_root/words_3436.txt', 'rb').read(), 3436)
rng = random.Random(int(sys.argv[1]) if len(sys.argv) > 1 else 1)
roots = open('/home/user/AI-/guopsaem_root/syllables_470.txt', encoding='utf-8').read().split()
pair_of = {}
for i, (srcs, t) in enumerate(m.edges):
    pass

def reachable(cur, k):
    R = bytearray(len(m.keys)); R[cur] = 1; q = [cur]
    for s in q:
        for g in m.available[s]:
            if k[g]:
                t = m.edges[g][1]
                if not R[t]: R[t] = 1; q.append(t)
    return R

def extended(cur, k):
    """apply candidate (A) pairing to a fixed point on top of the v3 canonical counts, then v3 normalize again."""
    k = bytearray(k)
    changed = True
    while changed:
        changed = False
        R = reachable(cur, k)
        eff = {}
        for g in range(len(k)):
            if k[g]:
                es = [s for s in m.edges[g][0] if R[s]]
                if len(es) == 1 and len(m.edges[g][0]) > 1:
                    eff[g] = es[0]
        if not eff:
            break
        # effective single-source view of every positive group
        single = {}
        for g in range(len(k)):
            if k[g]:
                es = [s for s in m.edges[g][0] if R[s]]
                if len(es) == 1:
                    single.setdefault((es[0], m.edges[g][1]), []).append(g)
        for (u, v), gs in list(single.items()):
            if not any(g in eff for g in gs):
                continue
            if u == v:
                for g in gs:
                    if g in eff and k[g] >= 2:
                        k[g] %= 2; changed = True
                continue
            back = single.get((v, u), [])
            for g in gs:
                for h in back:
                    if (g in eff or h in eff) and k[g] and k[h]:
                        a = min(k[g], k[h]); k[g] -= a; k[h] -= a; changed = True
        if changed:
            canon, st = m.normalize(cur, bytes(k))
            if st != -1:
                return None, st
            k = bytearray(canon)
    return bytes(k), -1

stats = collections.defaultdict(lambda: [0, 0, 0, 0])   # depth bucket -> [states, states changed, words removed, eff groups]
samples = int(sys.argv[2]) if len(sys.argv) > 2 else 300
for _ in range(samples):
    root = rng.choice(roots)
    cur, k, _ = m.position({'initial_syllable': root, 'history': []})
    canon, st = m.normalize(cur, k)
    depth = 0
    while st == -1 and depth <= 120:
        ext, est = extended(cur, canon)
        b = min(depth // 10 * 10, 100)
        s = stats[b]; s[0] += 1
        R = reachable(cur, canon)
        s[3] += sum(1 for g in range(len(canon)) if canon[g] and len(m.edges[g][0]) > 1 and sum(1 for x in m.edges[g][0] if R[x]) == 1)
        if est != -1 or ext != canon:
            s[1] += 1
            s[2] += sum(canon) - (sum(ext) if ext is not None else 0)
        legal = [g for g in m.available[cur] if canon[g]]
        g = rng.choice(legal)
        cur, canon, st = m.child(cur, canon, g)
        depth += 1
print('depth  states  changed  mean_words_removed_when_changed  mean_eff_single_shared_groups')
for b in sorted(stats):
    n, c, w, e = stats[b]
    print(f'{b:>3}+  {n:6d}  {c:6d}  {(w / c if c else 0):8.2f}  {e / n:6.2f}')
