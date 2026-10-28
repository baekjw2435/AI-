#!/usr/bin/env python3
"""Merge per-child route-proof-v2 certificates into one certificate for a root.

usage: merge_root.py DICT ROOT_POSITION.json OUT.jsonl[.gz] CHILD_PROOF [CHILD_PROOF ...]

Each CHILD_PROOF must be a certificate whose root is a child position of ROOT
(one more history word).  If ROOT is to be shown L, give a W certificate for
EVERY legal reduced group; for W, give one L certificate.  Nodes are deduplicated
by (v, counts) and renumbered; the output must still be checked by verify_v2.py.
This is a convenience for root splitting across processes/sessions; it does not
trust anything (the verifier re-derives every edge, including the new root's).
"""
import gzip, hashlib, json, sys
sys.dont_write_bytecode = True
sys.path.insert(0, '/tmp/claude-0/-home-user-AI-/80ff9426-9f7b-5815-97c0-938f621a9f93/scratchpad/verifier/route-verifier-v2')
from verify_v2 import IndependentModelV2  # noqa: E402


def opener(p):
    with open(p, 'rb') as f:
        gz = f.read(2) == b'\x1f\x8b'
    return gzip.open(p, 'rt', encoding='utf-8') if gz else open(p, encoding='utf-8')


def main():
    dic, rootpos, out = sys.argv[1:4]
    children = sys.argv[4:]
    m = IndependentModelV2(open(dic, 'rb').read())
    cur, counts, _ = m.position(json.load(open(rootpos, encoding='utf-8')))
    root, static = m.normalize(cur, counts)
    if static != -1:
        sys.exit("root is static; no merge needed")
    legal = [g for g in m.outgoing[cur] if root[g]]
    want = {}
    for g in legal:
        tv, tc, _ = m.child_v2(cur, root, g)
        want[(tv, tc.hex())] = g
    w = gzip.open(out, 'wt', encoding='utf-8', compresslevel=6) if out.endswith('.gz') else open(out, 'w', encoding='utf-8')
    ids = {}
    nxt = 0
    found = {}
    tmp = out + '.body.tmp'
    bf = open(tmp, 'w', encoding='utf-8')
    for cp in children:
        local = {}
        with opener(cp) as f:
            head = json.loads(f.readline())
            assert head['format'] == 'route-proof-v2' and head['groups'] == len(m.edges)
            rid = head['root']
            for line in f:
                n = json.loads(line)
                orig = n['id']
                key = hashlib.sha1(f"{n['v']}:{n['c']}".encode()).digest()
                if key in ids:
                    local[orig] = ids[key][0]
                else:
                    n['m'] = [[g, local[c]] for g, c in n['m']]
                    n['id'] = nxt
                    ids[key] = (nxt, n['r'])
                    local[orig] = nxt
                    bf.write(json.dumps(n, separators=(',', ':')) + '\n')
                    nxt += 1
                if orig == rid:
                    k2 = (n['v'], n['c'])
                    if k2 not in want:
                        sys.exit(f"{cp}: its root is not a canonical child of ROOT")
                    found[want[k2]] = (local[orig], ids[key][1])
    bf.close()
    results = {r for _, r in found.values()}
    if any(r == 'L' for _, r in found.values()):
        g = next(g for g, (_, r) in found.items() if r == 'L')
        rootline = {"id": nxt, "v": cur, "c": root.hex(), "r": "W", "m": [[g, found[g][0]]]}
    else:
        missing = [g for g in legal if g not in found]
        if missing:
            sys.exit(f"cannot show L: no certificate for groups {missing}")
        rootline = {"id": nxt, "v": cur, "c": root.hex(), "r": "L", "m": [[g, found[g][0]] for g in legal]}
    w.write(json.dumps({"format": "route-proof-v2", "groups": len(m.edges), "vertices": len(m.syllables), "root": nxt}) + '\n')
    with open(tmp, encoding='utf-8') as f:
        for line in f:
            w.write(line)
    w.write(json.dumps(rootline, separators=(',', ':')) + '\n')
    w.close()
    import os
    os.remove(tmp)
    print(json.dumps({"root_result": rootline["r"], "nodes": nxt + 1, "children_used": len(rootline["m"]), "child_results": sorted(results)}))


if __name__ == '__main__':
    main()
