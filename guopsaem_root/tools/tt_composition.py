#!/usr/bin/env python3
"""Composition of a solver_v5 --tt-save file: how many records came from the shared proven cache
(work >= PROVEN_BASE), how many are proven (pn == 0 or dn == 0) vs open, and the work distribution."""
import struct, sys
import numpy as np
PROVEN_BASE = 0x40000000
HDR = struct.Struct('<8sQQQQiiiiQQ')   # magic, graph0, graph1, root0, root1, init, init_div, wpn, reserved, count, created
for path in sys.argv[1:]:
    with open(path, 'rb') as f:
        h = HDR.unpack(f.read(HDR.size))
        count = h[9]
        a = np.fromfile(f, dtype='<u8', count=4 * count).reshape(-1, 4)
    C, D = a[:, 2], a[:, 3]
    pn = (C & 0xFFFFFFFF).astype(np.uint64); dn = (C >> 32)
    work = (D & 0xFFFFFFFF).astype(np.uint64)
    cache = work >= PROVEN_BASE
    proven = (pn == 0) | (dn == 0)
    own = ~cache
    print(f'{path.split("/")[-1]}: records {count:,}')
    print(f'   from shared cache (work >= PROVEN_BASE): {cache.sum():,} ({cache.mean()*100:.1f}%)')
    print(f'   own records: {own.sum():,}  of which proven {(own & proven).sum():,}, open (undecided) {(own & ~proven).sum():,}')
    if own.any():
        w = work[own]
        print(f'   own work: min {w.min()}, median {int(np.median(w))}, max {w.max()}')
