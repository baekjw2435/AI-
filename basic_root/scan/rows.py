# rows.py CONFIRMED.json LOGDIR POSDIR : for each verified syllable, the receiver's first moves and the proof's answer to each
import gzip, json, sys, os
S = '/tmp/claude-0/-home-user-AI-/80ff9426-9f7b-5815-97c0-938f621a9f93/scratchpad'
sys.path.insert(0, S + '/verifier/route-verifier-v2')
from verify_v2 import IndependentModelV2
m = IndependentModelV2(open(S + '/basic_root.txt', 'rb').read())
byg = {}
for w in m.words: byg.setdefault(m.group[m.word_endpoints[w]], []).append(w)
conf = json.load(open(sys.argv[1], encoding='utf-8')); logdir = sys.argv[2]; rootname = sys.argv[3]
out = {}
for s, v in conf.items():
    if not v['ok']: continue
    proof = os.path.join(logdir, rootname.format(s=s))
    pos = {'initial_syllable': s, 'history': []}
    cur, counts, used = m.position(pos)
    firsts = {}
    for g in m.outgoing[cur]:
        if counts[g]: firsts[g] = [w for w in byg[g] if w not in used]
    want = {}
    for g, ws in firsts.items():
        c2, k2, u2 = m.position({'initial_syllable': s, 'history': [ws[0]]})
        core, st = m.normalize(c2, k2)
        want[(c2, core.hex())] = (g, st)
    found = {}
    with gzip.open(proof, 'rt', encoding='utf-8') as f:
        f.readline()
        for line in f:
            n = json.loads(line)
            k = (n['v'], n['c'])
            if k in want: found[want[k][0]] = n
    rows = []
    for g, ws in firsts.items():
        st = [x for x in want.values() if x[0] == g][0][1]
        n = found.get(g)
        if n is None: rows.append((ws, 'static' if st != -1 else None, None, st)); continue
        reply = [w for w in byg[n['m'][0][0]] if w not in set(ws)] if n['r'] == 'W' and n['m'] else []
        rows.append((ws, n['r'], reply, st))
    out[s] = {'result': v['result'], 'nodes': v['nodes'], 'sha': v['sha'], 'rows': rows}
json.dump(out, sys.stdout, ensure_ascii=False)
