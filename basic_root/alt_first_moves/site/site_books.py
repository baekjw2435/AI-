#!/usr/bin/env python3
"""Pack cert2site records into route-site tables: ONE book per position, so a lookup never uses another history.

usage: site_books.py OUT_DIR ITEMS.json
  ITEMS.json: [{"id", "start", "history", "syllable", "result", "nodes", "proof_sha256", "records", "source",
                "batch", "case", "certificate"}, ...]   (build_site_tables.py writes it)
Writes OUT_DIR/manifest.json (format route-site-1, the site engine's own) and OUT_DIR/t/<book>/NN.bin (RSB1).

A book holds the winning-move records of a single verified v4 certificate: the position 'w로 t 제시' (history [w]).
Within the book, records are split into files by canonical core size, keys are the engine's 48-bit FNV keys cut to the
shortest width that keeps the file's keys distinct, and a 64-bit hash of the state guards against key collisions.
The RSB1 encoder below is the one of basic_root/route-site/build/site_build.py, copied (that module needs verify_v2).
"""
import hashlib
import json
import os
from pathlib import Path
import sys

import numpy as np

REC = np.dtype([('a', '<u4'), ('b', '<u4'), ('s', '<u8'), ('g', '<u2'), ('p', '<u2')])
FILE_ENTRIES = int(os.environ.get('SITE_FILE_ENTRIES', '400000'))   # the existing site uses 220,000; larger files keep the file count under an artifact's limit


def bits_unary_rice(gaps, k):
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


def encode(keys, groups, width=48):
    n = len(keys)
    gaps = np.diff(keys)
    k = int(max(0, np.floor(np.log2(max(1.0, float(keys[-1] - keys[0]) / max(1, n - 1)))))) if n > 1 else 0
    first = fixed_bits(np.array([keys[0] >> np.uint64(24), keys[0] & np.uint64(0xFFFFFF)], dtype=np.uint64).astype(np.int64), 24)
    kb = np.packbits(np.concatenate([first, bits_unary_rice(gaps, k)]))
    mb = np.packbits(fixed_bits(groups.astype(np.int64), 10))
    head = b'RSB1' + np.uint32(n).tobytes() + bytes([k, width, 0, 0]) + np.uint32(len(kb)).tobytes() + np.uint32(0).tobytes()
    return head + kb.tobytes() + mb.tobytes(), k


def decode_keys(blob):
    """Independent decoder (numpy), used to check every written file in full."""
    assert blob[:4] == b'RSB1'
    n = int.from_bytes(blob[4:8], 'little'); k = blob[8]; width = blob[9] or 48; kbytes = int.from_bytes(blob[12:16], 'little')
    kb = np.unpackbits(np.frombuffer(blob[20:20 + kbytes], dtype=np.uint8))
    first = 0
    for bit in kb[:48]:
        first = first * 2 + int(bit)
    zeros = np.flatnonzero(kb[48:] == 0) + 48
    keys = np.empty(n, dtype=np.uint64); keys[0] = first
    pos = 48; zi = 0
    w = (1 << np.arange(k - 1, -1, -1)).astype(np.uint64) if k else None
    for i in range(1, n):
        zi = np.searchsorted(zeros, pos, side='left') if zeros[zi] < pos else zi
        z = int(zeros[zi]); q = z - pos
        r = int((kb[z + 1:z + 1 + k].astype(np.uint64) * w).sum()) if k else 0
        keys[i] = keys[i - 1] + np.uint64((q << k) + r)
        pos = z + 1 + k; zi += 1
    mb = np.unpackbits(np.frombuffer(blob[20 + kbytes:], dtype=np.uint8))
    g = mb[:10 * n].reshape(n, 10).astype(np.int64) @ (1 << np.arange(9, -1, -1))
    return keys, g, width


def book_id(start, history):
    return 'p' + hashlib.sha256((start + '|' + '|'.join(history)).encode('utf-8')).hexdigest()[:12]


def main():
    out, items_path = Path(sys.argv[1]), sys.argv[2]
    items = json.loads(Path(items_path).read_text(encoding='utf-8'))
    (out / 't').mkdir(parents=True, exist_ok=True)
    manifest = {'format': 'route-site-1', 'dictionary_sha256': 'aa37031019f1e2a95b422ffc2f8d8d1b76b03ca88163b03b17af16ff90c79273',
                'books': [], 'note': 'one book per position (w로 t 제시); every table comes from that position\'s own verified v4 certificate'}
    total_entries = total_bytes = 0
    for it in items:
        rec = np.fromfile(it['records'], dtype=REC)
        rec = rec[np.lexsort((rec['b'], rec['a']))]
        same = (rec['a'][1:] == rec['a'][:-1]) & (rec['b'][1:] == rec['b'][:-1])
        if (same & (rec['s'][1:] != rec['s'][:-1])).any():
            sys.exit(f'{it["id"]}: 64-bit key collision between different states')
        if (same & (rec['g'][1:] != rec['g'][:-1])).any():
            sys.exit(f'{it["id"]}: one state with two different winning groups inside one certificate')
        keep = np.ones(len(rec), dtype=bool); keep[1:] = ~same
        rec = rec[keep]
        key = (rec['a'].astype(np.uint64) << np.uint64(16)) | (rec['b'].astype(np.uint64) >> np.uint64(16))
        core = rec['p'].astype(np.int64)
        sizes = np.bincount(core) if len(core) else np.zeros(1, dtype=np.int64)
        files, lo, acc = [], 0, 0
        for c in range(len(sizes)):
            if acc and acc + sizes[c] > FILE_ENTRIES:
                files.append((lo, c - 1)); lo, acc = c, 0
            acc += sizes[c]
        files.append((lo, len(sizes) - 1))
        # a 48-bit key shared by two different states inside one file: split the file between their core sizes
        # (the engine picks the file by core size, so each state then finds its own record)
        changed = True
        while changed:
            changed = False
            for fi, (clo, chi) in enumerate(files):
                sel = (core >= clo) & (core <= chi)
                ks, cs = key[sel], core[sel]
                o = np.argsort(ks, kind='stable'); ks, cs = ks[o], cs[o]
                dup = np.flatnonzero(ks[1:] == ks[:-1])
                if not len(dup):
                    continue
                i = dup[0]
                c1, c2 = sorted((int(cs[i]), int(cs[i + 1])))
                if c1 == c2:
                    sys.exit(f'{it["id"]}: 48-bit key collision between two states of the same core size {c1}')
                files[fi:fi + 1] = [(clo, c2 - 1), (c2, chi)]
                print(f'{it["id"]}: key collision between core sizes {c1} and {c2}; file split at {c2}', flush=True)
                changed = True
                break
        bid = book_id(it['start'], it['history'])
        (out / 't' / bid).mkdir(exist_ok=True)
        entry = {'id': bid, 'name': f'{it["history"][-1]}로 {it["syllable"]} 제시', 'entries': int(len(rec)), 'files': [],
                 'proofs': [{'id': it['id'], 'start': it['start'], 'history': it['history'], 'via': 1, 'syllable': it['syllable'],
                             'result_for_player_to_move': it['result'], 'nodes': it['nodes'], 'proof_sha256': it['proof_sha256'],
                             'table_records': int(len(rec)), 'source': it['source'], 'verifier': 'verify_v4 (C++)',
                             'batch': it['batch'], 'case': it['case'], 'certificate': it['certificate']}]}
        for fi, (clo, chi) in enumerate(files):
            sel = (core >= clo) & (core <= chi)
            ks, gs = key[sel], rec['g'][sel]
            if not len(ks):
                continue
            o = np.argsort(ks, kind='stable'); ks, gs = ks[o], gs[o]
            if (ks[1:] == ks[:-1]).any():
                sys.exit(f'{it["id"]}: 48-bit key collision inside file {fi}')
            for width in (36, 40, 44, 48):
                kw = ks >> np.uint64(48 - width)
                if not (kw[1:] == kw[:-1]).any():
                    break
            blob, k = encode(kw, gs, width)
            if len(ks) <= 5000:     # every file is decoded in full by check_tables.js with the site's own decoder
                dk, dg, dw = decode_keys(blob)
                assert dw == width and np.array_equal(dk, kw) and np.array_equal(dg, gs.astype(np.int64)), f'{it["id"]}/{fi}: decode mismatch'
            p = f't/{bid}/{fi:02d}.bin'
            (out / p).write_bytes(blob)
            entry['files'].append({'path': p, 'core_lo': int(clo), 'core_hi': int(chi), 'n': int(len(ks)), 'bytes': len(blob),
                                   'k': k, 'width': width, 'sha256': hashlib.sha256(blob).hexdigest(),
                                   'content_sha256': hashlib.sha256(kw.astype('<u8').tobytes() + gs.astype('<u2').tobytes()).hexdigest()})
            total_entries += len(ks); total_bytes += len(blob)
        manifest['books'].append(entry)
        print(it['id'], bid, len(rec), len(entry['files']), sum(f['bytes'] for f in entry['files']), flush=True)
    manifest['total_entries'] = total_entries; manifest['total_bytes'] = total_bytes
    (out / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps({'books': len(manifest['books']), 'entries': total_entries, 'bytes': total_bytes}))


if __name__ == '__main__':
    main()
