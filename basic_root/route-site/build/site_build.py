#!/usr/bin/env python3
"""Build the winning-move tables of the route site from every verified proof.

usage: site_build.py SITE2TAB OUTDIR

A book is the set of proofs behind one entry of the site (one start syllable, or a series such as 역, 격 or 칭존).
Every proof is checked against the sha256, state count and result that the unmodified verify_v2.py reported for it.
site2tab extracts each W node's winning group (the engine finds static and one-move wins itself). Within a book the
records are split into files by canonical core size, so moving down one line needs about one file at a time.

File format RSB1 (little-endian header, then MSB-first bit streams):
  'RSB1', u32 n, u8 k, u8 0, u16 0, u32 key_bytes, u32 0
  keys: the first 48-bit key raw, then n-1 gaps between sorted keys, Golomb-Rice coded with parameter k
  moves: n groups, 10 bits each, in key order
  key = (a << 16) | (b >> 16) where a, b are the engine's forward and backward FNV-1a values of the canonical state.
A lookup only searches the one file for its core size, so a 48-bit key is checked against at most a few hundred
thousand entries; the build stops if two different states share a key inside one file.
"""
import hashlib, json, os, subprocess, sys
import numpy as np

sys.dont_write_bytecode = True
S = '/tmp/claude-0/-home-user-AI-/80ff9426-9f7b-5815-97c0-938f621a9f93/scratchpad'
VDIR = os.environ.get('ROUTE_VERIFIER_DIR', S + '/verifier/route-verifier-v2')
DICT = os.environ.get('ROUTE_DICTIONARY', S + '/basic_root.txt')
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, VDIR)
sys.path.insert(0, os.path.join(HERE, '../../route-book/build'))
from verify_v2 import IndependentModelV2  # noqa: E402
import build_book  # noqa: E402  (its PROOFS list: 역, 격, 칭존 and the 25 scan syllables)

REC = np.dtype([('a', '<u4'), ('b', '<u4'), ('s', '<u8'), ('g', '<u2'), ('p', '<u2')])
FILE_ENTRIES = 220_000
SERIES_BOOK = {'역': '역', '격': '격', '칭존': '칭존'}
SKIP = {'easy.jon'}  # the same position as the 칭존 book's 존 root
# verified proofs not in route-book's list: the presenter's other replies after 역 → 역풍, all won by the 역풍 side
EXTRA = [('yeok.yeokpung.' + w, '역', ['역풍', w], base, 0, '역') for w, base in (
    ('풍랑', 'improve/solver/proofs/yeokpung_child1_W'), ('풍운', 'improve/solver/proofs/yeokpung_child4_W'),
    ('풍진', 'improve/solver/proofs/yeokpung_child6_W'), ('풍향', 'improve/solver/proofs/yeokpung_child7_W'),
    ('풍자적', 'yeokpung_run/proofs/C_pungjajeok_W'), ('풍습', 'yeokpung_run/proofs/B_pungseup_W'))]


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for blk in iter(lambda: f.read(1 << 22), b''):
            h.update(blk)
    return h.hexdigest()


def proof_list():
    """(pid, book, start, history, via, proof path, verified sha256, result, nodes, source)"""
    out = []
    for pid, start, hist, base, via, series in list(build_book.PROOFS) + EXTRA:
        if pid in SKIP:
            continue
        v = json.load(open(f'{S}/{base}.verify.json', encoding='utf-8'))
        assert v['verified'] is True and v['history'] == hist and not v.get('initial_used_words'), pid
        out.append((pid, SERIES_BOOK.get(series, start), start, hist, via, f'{S}/{base}.jsonl.gz', v['proof_sha256'],
                    v['result_for_player_to_move'], v['checked_certificate_states'], 'verify.json'))
    for s in ('탑', '맥'):
        v = json.load(open(f'{S}/tapmaek/logs/{s}.verify.json', encoding='utf-8'))
        assert v['verified'] is True and v['history'] == [] and v['current_syllable'] == s, s
        out.append((f'fresh.{s}', s, s, [], 0, f'{S}/tapmaek/logs/{s}_merged.jsonl.gz', v['proof_sha256'],
                    v['result_for_player_to_move'], v['checked_certificate_states'], 'verify.json'))
    for d, names in (('easy2', lambda s: ['logs/root_%s.jsonl.gz' % s]),
                     ('rest', lambda s: ['logs/%s.jsonl.gz' % s, 'logs/%s.B.jsonl.gz' % s, 'logs/%s.C.jsonl.gz' % s])):
        conf = f'{S}/{d}/confirmed.json'
        if not os.path.exists(conf):
            continue
        for s, v in json.load(open(conf, encoding='utf-8')).items():
            if not v['ok']:
                continue
            paths = [f'{S}/{d}/{n}' for n in names(s) if os.path.exists(f'{S}/{d}/{n}')]
            match = [p for p in paths if sha256(p) == v['sha']]
            assert match, f'{d}/{s}: no proof file with the verified sha256'
            out.append((f'fresh.{s}', s, s, [], 0, match[0], v['sha'], v['result'], v['nodes'], f'{d}/confirmed.json'))
    return out


def bits_unary_rice(gaps, k):
    """Golomb-Rice code of non-negative gaps (uint64) as a 0/1 uint8 array, MSB first."""
    q = (gaps >> np.uint64(k)).astype(np.int64)
    lens = q + 1 + k
    starts = np.concatenate([[0], np.cumsum(lens)[:-1]])
    bits = np.zeros(int(lens.sum()), dtype=np.uint8)
    if q.sum():
        rep = np.repeat(starts, q)
        within = np.arange(int(q.sum())) - np.repeat(np.concatenate([[0], np.cumsum(q)[:-1]]), q)
        bits[rep + within] = 1
    base = starts + q + 1
    for j in range(k):
        bits[base + j] = ((gaps >> np.uint64(k - 1 - j)) & np.uint64(1)).astype(np.uint8)
    return bits


def fixed_bits(values, width):
    out = np.zeros(len(values) * width, dtype=np.uint8)
    for j in range(width):
        out[j::width] = (values >> (width - 1 - j)) & 1
    return out


def encode(keys, groups):
    """keys: sorted unique uint64 (< 2**48); groups: uint16 (< 1024)"""
    n = len(keys)
    gaps = np.diff(keys)
    k = int(max(0, np.floor(np.log2(max(1.0, float(keys[-1] - keys[0]) / max(1, n - 1)))))) if n > 1 else 0
    first = fixed_bits(np.array([keys[0] >> np.uint64(24), keys[0] & np.uint64(0xFFFFFF)], dtype=np.uint64).astype(np.int64), 24)
    kb = np.packbits(np.concatenate([first, bits_unary_rice(gaps, k)]))
    mb = np.packbits(fixed_bits(groups.astype(np.int64), 10))
    head = b'RSB1' + np.uint32(n).tobytes() + bytes([k, 0, 0, 0]) + np.uint32(len(kb)).tobytes() + np.uint32(0).tobytes()
    return head + kb.tobytes() + mb.tobytes(), k


def decode(blob):  # reference decoder, used to check every file after writing it
    assert blob[:4] == b'RSB1'
    n = int.from_bytes(blob[4:8], 'little'); k = blob[8]; kbytes = int.from_bytes(blob[12:16], 'little')
    kb = np.unpackbits(np.frombuffer(blob[20:20 + kbytes], dtype=np.uint8))
    mb = np.unpackbits(np.frombuffer(blob[20 + kbytes:], dtype=np.uint8))
    first = 0
    for bit in kb[:48]:
        first = first * 2 + int(bit)
    keys = [first]
    pos = 48
    ones = np.flatnonzero(kb[48:] == 0) + 48  # terminating zero of each unary part
    for i in range(n - 1):
        z = ones[np.searchsorted(ones, pos)]
        q = z - pos
        r = 0
        for bit in kb[z + 1:z + 1 + k]:
            r = r * 2 + int(bit)
        keys.append(keys[-1] + (q << k) + r)
        pos = z + 1 + k
    g = mb[:10 * n].reshape(n, 10).astype(np.int64) @ (1 << np.arange(9, -1, -1))
    return keys, g


def main():
    tool, out = sys.argv[1], sys.argv[2]
    os.makedirs(f'{out}/t', exist_ok=True)
    m = IndependentModelV2(open(DICT, 'rb').read())
    dsha = sha256(DICT)
    by_group = [[] for _ in m.edges]
    for w in m.words:
        by_group[m.group[m.word_endpoints[w]]].append(w)
    proofs = proof_list()
    books = {}
    for pid, book, start, hist, via, path, vsha, result, nodes, source in proofs:
        assert sha256(path) == vsha, f'{pid}: proof file differs from the verified one'
        cur, _, _ = m.position({'initial_syllable': start, 'history': hist})
        tab = f'{out}/_{pid}.bin'
        info = json.loads(subprocess.run([tool, path, tab], check=True, capture_output=True, text=True).stdout)
        assert info['nodes'] == nodes and info['root_result'] == result, (pid, info, nodes, result)
        r = np.fromfile(tab, dtype=REC)
        os.remove(tab)
        b = books.setdefault(book, {'recs': [], 'proofs': []})
        b['recs'].append(r)
        b['proofs'].append({'id': pid, 'start': start, 'history': hist, 'via': via, 'syllable': m.syllables[cur],
                            'result_for_player_to_move': result, 'nodes': nodes, 'proof_sha256': vsha,
                            'table_records': int(len(r)), 'source': source})
        print(pid, book, info['records'], flush=True)
    manifest = {'format': 'route-site-1', 'dictionary_sha256': dsha, 'books': []}
    total_bytes = total_entries = 0
    for bi, (book, b) in enumerate(sorted(books.items())):
        rec = np.concatenate(b['recs'])
        rec = rec[np.lexsort((rec['b'], rec['a']))]
        same = (rec['a'][1:] == rec['a'][:-1]) & (rec['b'][1:] == rec['b'][:-1])
        if (same & (rec['s'][1:] != rec['s'][:-1])).any():
            sys.exit(f'{book}: 64-bit key collision between different states')
        keep = np.ones(len(rec), dtype=bool); keep[1:] = ~same
        rec = rec[keep]
        key = (rec['a'].astype(np.uint64) << np.uint64(16)) | (rec['b'].astype(np.uint64) >> np.uint64(16))
        core = rec['p'].astype(np.int64)
        sizes = np.bincount(core)
        files, lo, acc = [], 0, 0
        for c in range(len(sizes)):
            if acc and acc + sizes[c] > FILE_ENTRIES:
                files.append((lo, c - 1)); lo, acc = c, 0
            acc += sizes[c]
        files.append((lo, len(sizes) - 1))
        bid = 'k' + ''.join('%04x' % ord(ch) for ch in book)  # stable across rebuilds, so unchanged books keep their files
        os.makedirs(f'{out}/t/{bid}', exist_ok=True)
        entry = {'id': bid, 'name': book, 'proofs': b['proofs'], 'entries': int(len(rec)), 'files': []}
        for fi, (clo, chi) in enumerate(files):
            sel = (core >= clo) & (core <= chi)
            ks, gs = key[sel], rec['g'][sel]
            o = np.argsort(ks, kind='stable'); ks, gs = ks[o], gs[o]
            dup = ks[1:] == ks[:-1]
            if dup.any():
                sys.exit(f'{book}: 48-bit key collision inside file {fi}; widen the key')
            blob, k = encode(ks, gs)
            dk, dg = decode(blob) if len(ks) <= 5000 else (None, None)
            if dk is not None:
                assert dk == [int(x) for x in ks] and list(dg) == [int(x) for x in gs], f'{book}/{fi}: decode mismatch'
            p = f't/{bid}/{fi:02d}.bin'
            open(f'{out}/{p}', 'wb').write(blob)
            entry['files'].append({'path': p, 'core_lo': int(clo), 'core_hi': int(chi), 'n': int(len(ks)), 'bytes': len(blob),
                                   'k': k, 'sha256': hashlib.sha256(blob).hexdigest()})
            total_bytes += len(blob); total_entries += len(ks)
        manifest['books'].append(entry)
        print(book, bid, 'entries', len(rec), 'files', len(files), 'bytes', sum(f['bytes'] for f in entry['files']), flush=True)
    model = {'format': 'route-site-1', 'dictionary_sha256': dsha, 'syllables': m.syllables, 'edges': m.edges,
             'words': by_group, 'full': list(m.full_counts), 'pairs': m.pairs, 'loops': m.loops, 'outgoing': m.outgoing,
             'rev': [m.group.get((t, s), -1) for (s, t) in m.edges]}
    json.dump(model, open(f'{out}/model.json', 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    manifest['total_entries'] = total_entries; manifest['total_bytes'] = total_bytes
    json.dump(manifest, open(f'{out}/manifest.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('total entries', total_entries, 'bytes', total_bytes)


if __name__ == '__main__':
    main()
