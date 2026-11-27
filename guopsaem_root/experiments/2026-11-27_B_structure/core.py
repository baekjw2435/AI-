import sys, json
from collections import defaultdict, Counter
sys.path.insert(0, '/home/user/AI-/guopsaem_root/verifier_v3')
from verify_v3 import ModelV3
G = '/home/user/AI-/guopsaem_root/'
m = ModelV3(open(G + 'words_3683.txt', 'rb').read(), 3683)
s = sys.argv[1] if len(sys.argv) > 1 else '객'
cur = m.vertex_of(s)
core, st = m.normalize(cur, m.full_counts)
E = [(i, m.edges[i][0], m.edges[i][1], c) for i, c in enumerate(core) if c]
V = set()
for i, src, t, c in E: V.update(src); V.add(t)
print('start', s, m.names[cur], 'core groups', len(E), 'words', sum(c for *_, c in E), 'vertices', len(V), 'shared groups', sum(1 for e in E if len(e[1]) > 1))
# out/in word counts per vertex (shared group counted for every source)
out = Counter(); inn = Counter(); outg = Counter()
adj = defaultdict(set)
for i, src, t, c in E:
    inn[t] += c
    for u in src:
        out[u] += c; outg[u] += 1; adj[u].add(t)
# SCC (Tarjan iterative)
idx = {}; low = {}; onst = set(); st_ = []; comps = []; k = [0]
def strong(v0):
    stack = [(v0, iter(adj[v0]))]; idx[v0] = low[v0] = k[0]; k[0] += 1; st_.append(v0); onst.add(v0)
    while stack:
        v, it = stack[-1]
        for w in it:
            if w not in idx:
                idx[w] = low[w] = k[0]; k[0] += 1; st_.append(w); onst.add(w); stack.append((w, iter(adj[w]))); break
            elif w in onst: low[v] = min(low[v], idx[w])
        else:
            stack.pop()
            if stack: low[stack[-1][0]] = min(low[stack[-1][0]], low[v])
            if low[v] == idx[v]:
                comp = []
                while True:
                    w = st_.pop(); onst.discard(w); comp.append(w)
                    if w == v: break
                comps.append(comp)
for v in sorted(V):
    if v not in idx: strong(v)
sizes = sorted((len(c) for c in comps), reverse=True)
print('SCCs', len(comps), 'largest', sizes[:5], 'singletons', sum(1 for x in sizes if x == 1))
big = max(comps, key=len); B = set(big)
wb = sum(c for i, src, t, c in E if t in B and any(u in B for u in src))
print('words inside largest SCC', wb)
print('vertices by out-degree (words):', sorted(Counter(min(out[v], 10) for v in V).items()))
low_out = sorted(((out[v], inn[v], m.names[v]) for v in V if out[v] <= 3), key=lambda x: (x[0], -x[1]))
print('out<=3 vertices', len(low_out), low_out[:25])
print('top in-degree', sorted(((inn[v], out[v], m.names[v]) for v in V), reverse=True)[:12])
