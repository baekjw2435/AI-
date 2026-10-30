#!/usr/bin/env python3
"""Build the route-book bundle (one winning-move table for every verified proof).

usage: build_book.py PROOF2TAB OUTDIR [START ...]

With START syllables (e.g. 격), only the proofs of those start syllables go into the bundle.

Every proof is checked against the sha256 that the unmodified verify_v2.py reported for it,
then proof2tab extracts its W-node moves. All records go into one table keyed by the engine's
canonical-state key, split into 256 buckets by the key's top byte (tables/bXX.bin, YSK1 format).
"""
import hashlib, json, os, subprocess, sys
import numpy as np

sys.dont_write_bytecode = True
S = '/tmp/claude-0/-home-user-AI-/80ff9426-9f7b-5815-97c0-938f621a9f93/scratchpad'
VDIR = os.environ.get('ROUTE_VERIFIER_DIR', S + '/verifier/route-verifier-v2')
DICT = os.environ.get('ROUTE_DICTIONARY', S + '/basic_root.txt')
sys.path.insert(0, VDIR)
from verify_v2 import IndependentModelV2  # noqa: E402

# id, start syllable, history at the proof root, verify_v2 result JSON (proof next to it)
PROOFS = [
    ('yeok', '역', [], 'improve/solver/proofs/root_yeok_W_via_yeokseup'),
    ('yeok.yeoksahak', '역', ['역사학'], 'improve/solver/proofs/idx10_yeoksahak_W'),
    ('yeok.yeokbanghyang', '역', ['역방향'], 'improve/solver/proofs/idx5_yeokbanghyang_W'),
    ('yeok.yeokpung', '역', ['역풍'], 'yeokpung_run/proofs/YP_yeokpung_opponent_W'),
    ('gyeok', '격', [], 'gyeok_run/proofs/R_gyeok_W_via_gyeokjeung'),
    ('gyeok.gyeoksik', '격', ['격식'], 'gyeok_run/proofs/R_3_gyeoksik_L'),
    ('gyeok.gyeokrang', '격', ['격랑'], 'gyeok_run/proofs/R_0_W'),
    ('gyeok.gyeokmyeol', '격', ['격멸'], 'gyeok_run/proofs/R_1_W'),
    ('gyeok.gyeokbyeon', '격', ['격변'], 'gyeok_run/proofs/R_2_W'),
    ('gyeok.gyeoksikjeok', '격', ['격식적'], 'gyeok_run/proofs/R_5_W'),
    ('gyeok.gyeoktoe', '격', ['격퇴'], 'gyeok_run/proofs/R_8_W'),
    ('gyeok.gyeokchan', '격', ['격찬'], 'gyeok_run/proofs/R_7_gyeokchan_W'),
    ('gyeok.gyeogeon', '격', ['격언'], 'gyeok_run/proofs/R_4_gyeogeon_W'),
]
# first moves decided only in Astra's earlier records (no certificate in this bundle)
ASTRA = {'역': {'역할': 'W', '역기능': 'W', '역세권': 'L', '역할극': 'L', '역병': 'L', '역순': 'L', '역전승': 'L',
               '역사적': 'L', '역설적': 'L', '역적': 'L', '역동적': 'L', '역행': 'L'}}
PENDING = {'격': {'격돌': '격돌과 돌격이 서로 맞물리는 짝(왕복 쌍)이라 따로 계산해야 해서 아직 판정하지 않음'}}
REC = np.dtype([('a', '<u4'), ('b', '<u4'), ('s', '<u8'), ('g', '<u2'), ('p', '<u2')])


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for blk in iter(lambda: f.read(1 << 22), b''):
            h.update(blk)
    return h.hexdigest()


def main():
    tool, out, only = sys.argv[1], sys.argv[2], set(sys.argv[3:])
    proof_list = [p for p in PROOFS if not only or p[1] in only]
    assert proof_list, 'no proof for the requested start syllables'
    os.makedirs(out + '/tables', exist_ok=True)
    m = IndependentModelV2(open(DICT, 'rb').read())
    by_group = [[] for _ in m.edges]
    for w in m.words:
        by_group[m.group[m.word_endpoints[w]]].append(w)
    parts, proofs = [], []
    for k, (pid, start, hist, base) in enumerate(proof_list):
        v = json.load(open(f'{S}/{base}.verify.json', encoding='utf-8'))
        assert v['verified'] is True and v['dictionary_sha256'] == sha256(DICT), pid
        assert v['history'] == hist and not v.get('initial_used_words'), pid
        pos = {'initial_syllable': start, 'history': hist}
        if os.path.exists(f'{S}/{base}.position.json'):  # the older 역 runs kept only the verifier output
            assert json.load(open(f'{S}/{base}.position.json', encoding='utf-8')) == pos, pid
        cur, _, _ = m.position(pos)
        assert m.syllables[cur] == v['current_syllable'], pid
        proof = f'{S}/{base}.jsonl.gz'
        assert sha256(proof) == v['proof_sha256'], f'{pid}: proof file differs from the verified one'
        tab = f'{out}/../_{pid}.bin'
        info = json.loads(subprocess.run([tool, proof, tab], check=True, capture_output=True, text=True).stdout)
        assert info['nodes'] == v['checked_certificate_states'] and info['root_result'] == v['result_for_player_to_move'], pid
        r = np.fromfile(tab, dtype=REC)
        os.remove(tab)
        parts.append((r, np.full(len(r), k, dtype=np.uint8)))
        proofs.append({'id': pid, 'start': start, 'history': hist,
                       'player_to_move': 'presenter' if len(hist) % 2 else 'receiver',
                       'result_for_player_to_move': v['result_for_player_to_move'],
                       'nodes': v['checked_certificate_states'], 'proof_sha256': v['proof_sha256'],
                       'verify_seconds': v.get('elapsed_seconds'), 'table_entries': len(r)})
        print(pid, info, flush=True)
    rec = np.concatenate([p[0] for p in parts]); src = np.concatenate([p[1] for p in parts])
    order = np.lexsort((src, rec['b'], rec['a']))
    rec, src = rec[order], src[order]
    same = (rec['a'][1:] == rec['a'][:-1]) & (rec['b'][1:] == rec['b'][:-1])
    clash = same & (rec['s'][1:] != rec['s'][:-1])
    if clash.any():
        sys.exit(f'{int(clash.sum())} key collisions between different states; widen the key')
    keep = np.ones(len(rec), dtype=bool); keep[1:] = ~same
    # states recorded by several proofs, and those where the proofs chose different winning groups
    sid = np.cumsum(keep) - 1
    multi = np.bincount(sid) > 1
    pairs = np.unique(np.stack([sid, rec['g'].astype(np.int64)]), axis=1)
    differ = np.bincount(pairs[0], minlength=len(multi)) > 1
    stats = {'records': int(len(rec)), 'unique_states': int(keep.sum()), 'duplicate_records_removed': int(same.sum()),
             'states_in_several_proofs': int(multi.sum()), 'states_with_different_moves': int(differ.sum())}
    print(stats)
    rec = rec[keep]
    bucket = (rec['a'] >> 24).astype(np.int64)
    sizes = np.bincount(bucket, minlength=256)
    starts = np.concatenate([[0], np.cumsum(sizes)])
    for bk in range(256):
        r = rec[starts[bk]:starts[bk + 1]]
        keys = np.empty(2 * len(r), dtype='<u4'); keys[0::2] = r['a']; keys[1::2] = r['b']
        with open(f'{out}/tables/b{bk:02x}.bin', 'wb') as f:
            f.write(b'YSK1' + np.uint32(len(r)).tobytes() + keys.tobytes() + r['g'].astype('<u2').tobytes())
    model = {'format': 'route-book-1', 'dictionary_sha256': sha256(DICT), 'syllables': m.syllables, 'edges': m.edges,
             'words': by_group, 'full': list(m.full_counts), 'pairs': m.pairs, 'loops': m.loops, 'outgoing': m.outgoing,
             'rev': [m.group.get((t, s), -1) for (s, t) in m.edges], 'buckets': 256, 'entries': int(len(rec)),
             'roots': [{'start': p['start'], 'history': p['history'], 'result_for_player_to_move': p['result_for_player_to_move']}
                       for p in proofs]}
    json.dump(model, open(f'{out}/model.json', 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    start_set = {p[1] for p in proof_list}
    json.dump({'proofs': proofs, 'stats': stats, 'astra_records': {k: v for k, v in ASTRA.items() if k in start_set},
               'pending': {k: v for k, v in PENDING.items() if k in start_set},
               'bucket_entries': [int(x) for x in sizes]},
              open(f'{out}/_proofs.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('entries', len(rec), 'largest bucket', int(sizes.max()), 'smallest', int(sizes.min()))


if __name__ == '__main__':
    main()
