#!/usr/bin/env python3
"""Composition of a solver_v5 --tt-save file: how many records came from the shared proven cache, how many
are the job's own (proven: pn == 0 or dn == 0, or open), and the work distribution of the own records.

usage: tt_composition.py FILE.tt ... [--cache CACHE.pc ...]

A cache record has work >= PROVEN_BASE (2^30) and is always proven. Files saved before 2026-11-06 may also
hold OPEN records with work >= 2^30: the job's own top nodes whose total work had passed 2^30 (the solver now
caps own work at 2^30 - 1, and --tt-load repairs such records). They are counted as own records here.
A PROVEN record with work >= 2^30 cannot be told apart by its work alone: with --cache, those found in the
cache files (same k0 and k1) are reported as cache records and the others separately (old cache records
dropped from the cache since, or the job's own proven records with a very large work).
"""
import struct
import sys

import numpy as np

PROVEN_BASE = 0x40000000
HDR = struct.Struct('<8sQQQQiiiiQQ')   # magic, graph0, graph1, root0, root1, init, init_div, wpn, reserved, count, created
PC_HDR = struct.Struct('<8sQQIIQQ')     # magic, graph0, graph1, min_work, reserved, count, created
PC_REC = np.dtype([('k0', '<u8'), ('k1', '<u8'), ('work', '<u4'), ('best', '<u2'), ('win', 'u1'), ('pad', 'u1')])


def load_cache(paths):
    keys = []
    for p in paths:
        with open(p, 'rb') as f:
            h = PC_HDR.unpack(f.read(PC_HDR.size))
            if h[0][:4] != b'YSPC':
                raise SystemExit(f'{p}: not a proven-cache file')
            r = np.fromfile(f, dtype=PC_REC, count=h[5])
        keys.append(np.stack([r['k1'], r['k0']], axis=1))
    k = np.concatenate(keys) if keys else np.zeros((0, 2), dtype='<u8')
    order = np.lexsort((k[:, 1], k[:, 0]))
    return k[order]


def in_cache(sorted_keys, k1, k0):
    pos = np.searchsorted(sorted_keys[:, 0], k1, side='left')
    hit = np.zeros(len(k1), dtype=bool)
    n = len(sorted_keys)
    # walk forward over equal k1 values (practically never more than one)
    for step in range(4):
        p = pos + step
        ok = p < n
        pp = np.where(ok, p, 0)
        same = ok & (sorted_keys[pp, 0] == k1)
        hit |= same & (sorted_keys[pp, 1] == k0)
    return hit


if __name__ == '__main__':
    args = sys.argv[1:]
    files = [a for a in args[:args.index('--cache')]] if '--cache' in args else args
    caches = args[args.index('--cache') + 1:] if '--cache' in args else []
    ck = load_cache(caches) if caches else None
    for path in files:
        with open(path, 'rb') as f:
            h = HDR.unpack(f.read(HDR.size))
            count = h[9]
            a = np.fromfile(f, dtype='<u8', count=4 * count).reshape(-1, 4)
        C, D = a[:, 2], a[:, 3]
        pn = C & 0xFFFFFFFF
        dn = C >> 32
        work = D & 0xFFFFFFFF
        proven = (pn == 0) | (dn == 0)
        big = work >= PROVEN_BASE
        cache = big & proven
        unknown_origin = np.zeros(count, dtype=bool)
        if ck is not None and cache.any():
            idx = np.nonzero(cache)[0]
            hit = in_cache(ck, a[idx, 1], a[idx, 0])
            unknown_origin[idx[~hit]] = True
            cache[idx[~hit]] = False
        own = ~cache & ~unknown_origin
        print(f'{path.split("/")[-1]}: records {count:,}')
        print(f'   from shared cache (work >= 2^30, proven{", found in the cache" if ck is not None else ""}): {cache.sum():,} ({cache.mean() * 100:.1f}%)')
        if ck is not None:
            print(f'   proven, work >= 2^30, NOT in the cache: {unknown_origin.sum():,} (old cache records dropped since, or own)')
        print(f'   own records: {own.sum():,}  of which proven {(own & proven).sum():,}, open (undecided) {(own & ~proven).sum():,}')
        if (big & ~proven).any():
            print(f'   (of the own records, {(big & ~proven).sum():,} open ones have work >= 2^30: saved before the 2026-11-06 cap)')
        if own.any():
            w = work[own]
            print(f'   own work: min {w.min()}, median {int(np.median(w))}, max {w.max()}')
