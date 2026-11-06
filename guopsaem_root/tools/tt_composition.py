#!/usr/bin/env python3
"""Composition of a solver_v5 --tt-save file: how many records came from the shared proven cache, how many
are the job's own (proven: pn == 0 or dn == 0, or open), and the work distribution of the own records.

A cache record has work >= PROVEN_BASE (2^30) and is always proven. Files saved before 2026-11-06 may also
hold a few OPEN records with work >= 2^30: the job's own top nodes (root, main line) whose total work had
passed 2^30; they are counted as own records here (the solver now caps own work at 2^30 - 1).
usage: tt_composition.py FILE.tt ...
"""
import struct
import sys

import numpy as np

PROVEN_BASE = 0x40000000
HDR = struct.Struct('<8sQQQQiiiiQQ')   # magic, graph0, graph1, root0, root1, init, init_div, wpn, reserved, count, created
for path in sys.argv[1:]:
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
    own = ~cache
    print(f'{path.split("/")[-1]}: records {count:,}')
    print(f'   from shared cache (work >= 2^30, proven): {cache.sum():,} ({cache.mean() * 100:.1f}%)')
    print(f'   own records: {own.sum():,}  of which proven {(own & proven).sum():,}, open (undecided) {(own & ~proven).sum():,}')
    if (big & ~proven).any():
        print(f'   (of the own records, {(big & ~proven).sum():,} open ones have work >= 2^30: saved before the 2026-11-06 cap)')
    if own.any():
        w = work[own]
        print(f'   own work: min {w.min()}, median {int(np.median(w))}, max {w.max()}')
