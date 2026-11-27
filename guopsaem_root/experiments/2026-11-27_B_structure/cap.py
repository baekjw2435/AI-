import sys
from collections import Counter, defaultdict
sys.path.insert(0, '/home/user/AI-/guopsaem_root/verifier_v3')
from verify_v3 import ModelV3
G = '/home/user/AI-/guopsaem_root/'
m = ModelV3(open(G + 'words_3683.txt', 'rb').read(), 3683)
s = sys.argv[1] if len(sys.argv) > 1 else '객'
cur = m.vertex_of(s)
core, st = m.normalize(cur, m.full_counts)
cnt = bytearray(core)
print('groups with count:', sorted(Counter(c for c in cnt if c).items()))
def caps(cnt):
    outw = Counter(); inw = Counter()
    for g, c in enumerate(cnt):
        if not c: continue
        S, t = m.edges[g]
        inw[t] += c
        for u in S: outw[u] += c
    new = bytearray(cnt); cut = 0
    for g, c in enumerate(cnt):
        if not c: continue
        S, t = m.edges[g]
        if len(S) == 1 and S[0] == t: continue          # loops: left to the mod-2 rule
        cap = min(c, outw[t] + 1, sum(inw[u] + (u == cur) for u in S))
        if cap < c: cut += c - cap; new[g] = cap
    return new, cut
total = 0
while True:
    cnt, cut = caps(cnt)
    if not cut: break
    total += cut
    cnt = bytearray(m.normalize(cur, bytes(cnt))[0])
print('words removed by caps:', total, 'core words after', sum(cnt), 'groups', sum(1 for c in cnt if c))
