import json, sys
from multiprocessing import Pool
sys.path.insert(0, '/home/user/AI-/guopsaem_root/pairing'); sys.path.insert(0, '/home/user/AI-/guopsaem_root/verifier_v3')
from verify_v3 import ModelV3, VerificationError
import find_pairing, verify_pairing
M = None
def init():
    global M
    M = ModelV3(open('/home/user/AI-/guopsaem_root/words_3436.txt', 'rb').read(), 3436)
def one(x):
    try:
        cur, raw, used = M.position({'initial_syllable': x, 'history': []})
    except VerificationError as e:
        return {'syllable': x, 'error': str(e)}
    canon, st = M.normalize(cur, raw)
    rec = {'syllable': x, 'static': st}
    for mode, counts in (('canonical', canon), ('raw', raw)):
        if mode == 'canonical' and st != -1:
            continue
        r = find_pairing.find(M, cur, counts, seconds=10)
        if r['status'] == 'found':
            verify_pairing.check_groups(M, cur, counts, r['S'], r['group_pairs'])
            r['S'] = sorted(M.names[v] for v in r['S']); r['pairs'] = len(r.pop('group_pairs'))
        rec[mode] = {k: r[k] for k in ('status', 'seconds') if k in r} | ({'S': r['S'], 'pairs': r['pairs']} if r['status'] == 'found' else {})
    return rec
if __name__ == '__main__':
    syl = open('/home/user/AI-/guopsaem_root/syllables_470.txt', encoding='utf-8').read().split()
    with Pool(2, initializer=init) as p, open(sys.argv[1], 'w', encoding='utf-8') as f:
        for rec in p.imap(one, syl):
            f.write(json.dumps(rec, ensure_ascii=False) + '\n'); f.flush()
