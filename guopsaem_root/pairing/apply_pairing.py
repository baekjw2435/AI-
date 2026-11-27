#!/usr/bin/env python3
"""Limited-budget trial of pairing proofs on positions sampled from real searches (2026-11-07).

usage: apply_pairing.py DICT WORD_COUNT IN.txt SAMPLE.log OUT.jsonl [NODE_SECONDS] [CHILD_SECONDS] [WORKERS]

SAMPLE.log comes from solver_v5_isolog --sample-log (every K-th mid() call: the canonical state, the
solver's result for it at the end of the call, and its work). For each sampled state:
  * node: is there a pairing that proves the player to move loses?
  * children: for every move, is there a pairing that proves the child lost for ITS player to move? If so,
    the sampled state is a win (by that move).
Every pairing found is re-checked with verify_pairing.check_groups (the independent checker's core) and
compared with the solver's own result for the state: a pairing "proving" a loss where the solver proved
a win (or the reverse for children) would be a contradiction and is reported as such.
'none' (no pairing exists) and 'unknown' (time ran out) decide nothing.
"""
import json
from multiprocessing import Pool
from pathlib import Path
import struct
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[0] / 'verifier_v3'))
from verify_v3 import ModelV3, VerificationError  # noqa: E402
import find_pairing  # noqa: E402
import verify_pairing  # noqa: E402

REC = struct.Struct('<QQQQIHBBHH')
MODEL = None


def read_samples(path):
    data = open(path, 'rb').read()
    i, out = 0, []
    while i < len(data):
        entry, ex, h0, h1, work, cur, res, _pad, depth, ng = REC.unpack_from(data, i)
        i += REC.size
        groups = [(struct.unpack_from('<H', data, i + 3 * j)[0], data[i + 3 * j + 2]) for j in range(ng)]
        i += 3 * ng
        out.append(dict(entry=entry, work=work, cur=cur, res=res, depth=depth, groups=groups))
    return out


def init(dict_path, nwords):
    global MODEL
    MODEL = ModelV3(Path(dict_path).read_bytes(), int(nwords))


def checked(model, cur, counts, seconds):
    r = find_pairing.find(model, cur, counts, seconds=seconds)
    if r['status'] == 'found':
        try:
            verify_pairing.check_groups(model, cur, counts, r['S'], r['group_pairs'])
            r['verified'] = True
        except VerificationError as e:
            r['verified'] = False
            r['verify_error'] = str(e)
        r['S_size'] = len(r['S'])
        r['pairs'] = len(r['group_pairs'])
        r['S_names'] = sorted(model.names[v] for v in r['S'])
    r.pop('S', None)
    r.pop('group_pairs', None)
    return r


def one(args):
    s, node_seconds, child_seconds = args
    model = MODEL
    counts = bytearray(len(model.edges))
    for g, c in s['groups']:
        counts[g] = c
    counts = bytes(counts)
    canon, static = model.normalize(s['cur'], counts)
    rec = {k: s[k] for k in ('entry', 'work', 'cur', 'res', 'depth')}
    rec['live_groups'] = len(s['groups'])
    rec['canonical_matches_solver'] = static == -1 and canon == counts
    t0 = time.time()
    rec['node'] = checked(model, s['cur'], counts, node_seconds)
    kids = []
    for g in model.available[s['cur']]:
        if not counts[g]:
            continue
        t, ch, st = model.child(s['cur'], counts, g)
        k = {'group': g, 'static': st}
        if st == -1:
            k.update(checked(model, t, ch, child_seconds))
        kids.append(k)
    rec['children'] = kids
    rec['seconds'] = round(time.time() - t0, 2)
    return rec


def main():
    dict_path, nwords, inp, samp, out = sys.argv[1:6]
    node_seconds = float(sys.argv[6]) if len(sys.argv) > 6 else 10.0
    child_seconds = float(sys.argv[7]) if len(sys.argv) > 7 else 5.0
    workers = int(sys.argv[8]) if len(sys.argv) > 8 else 3
    init(dict_path, nwords)
    # the solver's group and vertex numbering must be verify_v3's
    tok = open(inp).read().split()
    n, g = int(tok[0]), int(tok[1])
    assert n == len(MODEL.keys) and g == len(MODEL.edges), 'input does not match the dictionary model'
    pos = 3
    for e in range(g):
        k = int(tok[pos]); pos += 1
        srcs = tuple(int(x) for x in tok[pos:pos + k]); pos += k
        assert (srcs, int(tok[pos])) == MODEL.edges[e], f'group {e} differs from the dictionary model'
        pos += 2
    samples = read_samples(samp)
    with Pool(workers, initializer=init, initargs=(dict_path, nwords)) as p, open(out, 'w', encoding='utf-8') as f:
        for rec in p.imap(one, [(s, node_seconds, child_seconds) for s in samples]):
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
            f.flush()


if __name__ == '__main__':
    main()
