import sys, json
from collections import Counter, defaultdict
from pathlib import Path
REV = Path(sys.argv[1])
sys.path.insert(0, str(REV / 'guopsaem_root' / 'verifier_v3'))
from verify_v3 import ModelV3, VerificationError
m = ModelV3((REV / 'basic_root/words_817.txt').read_bytes(), 817)
doc = json.loads((REV / 'basic_root/alt_first_moves/targets.json').read_text(encoding='utf-8'))
summ = json.loads((REV / 'basic_root/alt_first_moves/results/summary.json').read_text(encoding='utf-8'))
cat = json.loads((REV / 'basic_root/route-site/catalog.json').read_text(encoding='utf-8'))
solved_roots = {e['id']: e['receiverWins'] for e in cat['entries'] if e['kind'] == 'fresh'}
root_canon = {}
def canon_root(t):
    if t not in root_canon:
        try:
            v, k, _ = m.position({'initial_syllable': t, 'history': []})
            root_canon[t] = (v,) + m.normalize(v, k)
        except VerificationError:
            root_canon[t] = None
    return root_canon[t]
kinds = Counter(); by_state = defaultdict(list); rows = []
for t in doc['targets']:
    s, w = t['syllable'], t['words'][0]
    v, k, _ = m.position({'initial_syllable': s, 'history': [w]})
    c, st = m.normalize(v, k)
    r = canon_root(w[-1])
    verified_old = t['existing']['evidence'] == 'verified'
    verified_new = any(e['decided'] for e in summ.get(t['id'], []))
    if st != -1:
        kind = 'static'
    elif r is None:
        kind = 'no_root'
    elif (v, c) == (r[0], r[1]):
        kind = 'identical_to_t_root'
    else:
        diff = sum(abs(a - b) for a, b in zip(c, r[1]))
        ngroups = sum(1 for a, b in zip(c, r[1]) if a != b)
        kind = 'differs_by_1_word' if diff == 1 else ('differs_2_3' if diff <= 3 else 'differs_more')
    kinds[(kind, 'verified' if (verified_old or verified_new) else 'open')] += 1
    by_state[(v, c)].append(t['id'])
    rows.append((t['id'], kind, verified_old or verified_new, w[-1], w[-1] in solved_roots))
for k, n in sorted(kinds.items()): print(k, n)
open_ident = [r for r in rows if r[1] == 'identical_to_t_root' and not r[2]]
print('open targets identical to the handed-over syllable root:', len(open_ident), '| of these, t root is one of the 94 solved:', sum(1 for r in open_ident if r[4]))
print('examples:', [r[0] for r in open_ident[:15]])
dup = {k: v for k, v in by_state.items() if len(v) > 1}
print('canonical states shared by 2+ targets:', len(dup), 'covering', sum(len(v) for v in dup.values()), 'targets; distinct canonical states among 497:', len(by_state))
vset = {r[0] for r in rows if r[2]}
gain = 0
for k, ids in dup.items():
    if any(i in vset for i in ids): gain += sum(1 for i in ids if i not in vset)
print('open targets whose canonical state equals an already verified target:', gain)
