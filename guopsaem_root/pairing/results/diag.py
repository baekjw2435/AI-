"""Diagnostic only: how far sampled positions are from a pairing (smallest number of uncovered words)."""
import json, sys
from multiprocessing import Pool
sys.path.insert(0, '/home/user/AI-/guopsaem_root/pairing'); sys.path.insert(0, '/home/user/AI-/guopsaem_root/verifier_v3')
from verify_v3 import ModelV3
import find_pairing, apply_pairing
M = None
def init():
    global M
    M = ModelV3(open('/home/user/AI-/guopsaem_root/words_3436.txt', 'rb').read(), 3436)
def one(s):
    counts = bytearray(len(M.edges))
    for g, c in s['groups']:
        counts[g] = c
    counts = bytes(counts)
    moves = sum(counts[g] for g in M.available[s['cur']])
    r = find_pairing.find(M, s['cur'], counts, seconds=20, relaxed=True)
    return {'entry': s['entry'], 'depth': s['depth'], 'live_groups': len(s['groups']), 'words_at_current': moves,
            'status': r['status'], 'uncovered': r.get('uncovered'), 'uncovered_bound': r.get('uncovered_bound'),
            'S_size': len(r['S']) if 'S' in r else None, 'seconds': r['seconds']}
if __name__ == '__main__':
    out = sys.argv[1]
    samples = []
    for f in sys.argv[2:]:
        ss = apply_pairing.read_samples(f)
        samples += ss[::10]          # every 10th sample: 20 per file
    with Pool(3, initializer=init) as p, open(out, 'w') as fo:
        for rec in p.imap(one, samples):
            fo.write(json.dumps(rec) + '\n'); fo.flush()
