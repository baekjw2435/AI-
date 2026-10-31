import os, sys, json
sys.path.insert(0, os.environ.get('ROUTE_VERIFIER_DIR', '/home/user/AI-/.work/verifier/route-verifier-v2'))
from verify_v2 import IndependentModelV2
m = IndependentModelV2(open(sys.argv[1],'rb').read())
pos = json.load(open(sys.argv[2]))
cur, counts, used = m.position(pos)
core, st = m.normalize(cur, counts)
verts = {m.edges[g][0] for g in range(len(core)) if core[g]} | {m.edges[g][1] for g in range(len(core)) if core[g]}
moves = [g for g in m.outgoing[cur] if core[g]]
print("cur", m.syllables[cur], "static", st, "core words", sum(core), "core groups", sum(1 for c in core if c), "core verts", len(verts), "legal", len(moves))
