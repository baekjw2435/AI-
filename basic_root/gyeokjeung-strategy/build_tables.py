import pickle, gzip, json, struct, sys, os
sys.path.insert(0, "/tmp/claude-0/-home-user-AI-/80ff9426-9f7b-5815-97c0-938f621a9f93/scratchpad/verifier/route-verifier-v2")
from verify_v2 import IndependentModelV2
m = IndependentModelV2(open("/tmp/claude-0/-home-user-AI-/80ff9426-9f7b-5815-97c0-938f621a9f93/scratchpad/basic_root.txt", "rb").read())
P = "/tmp/claude-0/-home-user-AI-/80ff9426-9f7b-5815-97c0-938f621a9f93/scratchpad/gyeok_run/proofs/R_gyeok_W_via_gyeokjeung.jsonl.gz"
OUT = "site_gj"; os.makedirs(OUT, exist_ok=True)
hdr, V, R, M, index = pickle.load(open("gyeok.pkl", "rb"))
root = hdr["root"]; first_g, start = M[root][0]
def fnv(data, basis):
    h = basis
    for b in data:
        h ^= b; h = (h * 16777619) & 0xFFFFFFFF
    return h
# per opponent reply group: W nodes (with a move) in that reply's subtree, skipping moves into static/terminal L children
need = {}
for g, ch in M[start]:
    seen = {ch}; st = [ch]; ids = {}
    while st:
        n = st.pop()
        if R[n] and M[n]:
            c = M[n][0][1]
            if M[c] or R[c]: ids[n] = M[n][0][0]     # keep unless child is a static/terminal L leaf
        for _, y in M[n]:
            if y not in seen: seen.add(y); st.append(y)
    need[g] = ids
    print("reply", m.syllables[m.edges[g][1]], "entries", len(ids), flush=True)
allids = set().union(*[set(d) for d in need.values()])
keys = {}
with gzip.open(P, "rt") as f:
    f.readline()
    for i, line in enumerate(f):
        if i in allids:
            n = json.loads(line); data = bytes([n["v"] & 255, n["v"] >> 8]) + bytes.fromhex(n["c"])
            keys[i] = (fnv(data, 2166136261), fnv(data[::-1], 0x9747b28c))
shards = {}
for g, ids in need.items():
    ent = {}
    for i, mv in ids.items():
        k = keys[i]
        if k in ent and ent[k] != mv: print("collision", k)
        ent[k] = mv
    ks = sorted(ent); name = f"shard_{g}.bin"
    with open(f"{OUT}/{name}", "wb") as fo:
        fo.write(b"YSK1" + struct.pack("<I", len(ks)))
        fo.write(b"".join(struct.pack("<II", a, b) for a, b in ks))
        fo.write(b"".join(struct.pack("<H", ent[k]) for k in ks))
    shards[str(g)] = {"file": name, "reply": m.syllables[m.edges[g][1]], "entries": len(ks)}
by_group = [[] for _ in m.edges]
for w in m.words: by_group[m.group[m.word_endpoints[w]]].append(w)
model = {"syllables": m.syllables, "edges": m.edges, "words": by_group, "full": list(m.full_counts),
         "pairs": m.pairs, "loops": m.loops, "outgoing": m.outgoing,
         "rev": [m.group.get((t, s), -1) for (s, t) in m.edges],
         "start": m.vertex["격"], "first": "격증", "shards": shards}
json.dump(model, open(f"{OUT}/model.json", "w"), ensure_ascii=False, separators=(",", ":"))
print(json.dumps(shards, ensure_ascii=False))
