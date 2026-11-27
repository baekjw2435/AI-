#!/usr/bin/env python3
"""A/B test of the --tt-load repair against the shared cache's load cap (2026-11-07, Astra review).

An old-format state file holds two proven records A and B whose work is >= PROVEN_BASE (2^30). That is how
cache records looked in state files saved before 2026-11-06. A cache file holds the same two records, A
with more work than B. With --proven-load-max 1 the cache load inserts only A. B must then be kept from the
state file as the job's own record. Otherwise it is in neither load and is missing for the run (it would
stay only in the cache file).

usage: test_tt_load_cache_select.py SOLVER IN.txt [OLD_SOLVER]
  IN.txt: any position input (the test first runs the solver briefly to get a real cache file and state header).
"""
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

PB = 0x40000000
INF = 0xFFFFFFFF
M64 = (1 << 64) - 1
TT_HDR = struct.Struct('<8sQQQQiiiiQQ')   # 72 bytes
PC_HDR = struct.Struct('<8sQQIIQQ')       # 48 bytes
PC_REC = struct.Struct('<QQIHBB')         # 24 bytes


def ck_add(h, w):
    h = ((h ^ w) * 0x100000001b3) & M64
    return h ^ (h >> 31)


def read_pc(path):
    data = Path(path).read_bytes()
    h = PC_HDR.unpack_from(data, 0)
    recs = [PC_REC.unpack_from(data, PC_HDR.size + 24 * i) for i in range(h[5])]
    return h, recs


def write_pc(path, header, recs):
    ck = 0x5eedcac4e
    body = b''
    for k0, k1, work, best, win, pad in recs:
        body += PC_REC.pack(k0, k1, work, best, win, pad)
        for w in (k0, k1, work | best << 32 | win << 48):
            ck = ck_add(ck, w)
    h = list(header); h[5] = len(recs)
    Path(path).write_bytes(PC_HDR.pack(*h) + body + struct.pack('<QQ', len(recs), ck) + b'YSPCEND\0')


def write_tt(path, header, recs):
    ck = 0x5eedc0de
    body = b''
    for r in recs:
        body += struct.pack('<4Q', *r)
        for w in r:
            ck = ck_add(ck, w)
    h = list(header); h[9] = len(recs)
    Path(path).write_bytes(TT_HDR.pack(*h) + body + struct.pack('<QQ', len(recs), ck) + b'YSTTEND\0')


def read_tt_keys(path):
    data = Path(path).read_bytes()
    h = TT_HDR.unpack_from(data, 0)
    out = {}
    for i in range(h[9]):
        k0, k1, C, D = struct.unpack_from('<4Q', data, TT_HDR.size + 32 * i)
        out[(k0, k1)] = D & 0xFFFFFFFF
    return out


def run(solver, inp, args):
    r = subprocess.run([solver, inp, '--threads', '1', '--tt-mb', '64', '--seconds', '60'] + args, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f'solver failed: {r.stderr[-400:]}')
    return json.loads(r.stdout.strip().splitlines()[-1])


def main():
    solver, inp = sys.argv[1], sys.argv[2]
    old = sys.argv[3] if len(sys.argv) > 3 else None
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        run(solver, inp, ['--nodes', '30000', '--proven-save', str(d / 'x.pc'), '--tt-save', str(d / 'x.tt')])
        ph, recs = read_pc(d / 'x.pc')
        bucket = lambda w: w.bit_length()
        recs = sorted(recs, key=lambda r: -r[2])
        a = recs[0]
        b = next(r for r in recs if bucket(r[2]) < bucket(a[2]))      # B: a lower work bucket than A
        write_pc(d / 'ab.pc', ph, [b, a])                               # file order B, A: the cap must pick A by work
        th = TT_HDR.unpack_from((d / 'x.tt').read_bytes(), 0)
        def as_state(r):
            k0, k1, work, best, win, _ = r
            C = (0 | INF << 32) if win else (INF | 0 << 32)
            return (k0, k1, C, (PB + work) | best << 32)
        write_tt(d / 'ab.tt', th, [as_state(a), as_state(b)])
        A, B = (a[0], a[1]), (b[0], b[1])
        print(f'A work {a[2]}, B work {b[2]}')
        cases = [('cap 1', ['--proven-load', str(d / 'ab.pc'), '--proven-load-max', '1'], 1, 1),
                 ('cap 2', ['--proven-load', str(d / 'ab.pc'), '--proven-load-max', '2'], 2, 0),
                 ('no cap', ['--proven-load', str(d / 'ab.pc')], 2, 0),
                 ('no cache', [], 0, 2)]
        ok = True
        for name, extra, want_in, want_kept in cases:
            for label, bin_ in (('new', solver), ('old', old)):
                if bin_ is None:
                    continue
                out = d / f'out_{label}.tt'
                r = run(bin_, inp, ['--nodes', '1', '--tt-load', str(d / 'ab.tt'), '--tt-save', str(out), '--tt-save-max', '0'] + extra)
                keys = read_tt_keys(out)
                cnt = (r.get('tt_load_proven_in_cache'), r.get('tt_load_proven_kept'))
                saved = {'A': keys.get(A), 'B': keys.get(B)}
                good = cnt == (want_in, want_kept)
                if name == 'cap 1':
                    good = good and saved['B'] == b[2] and saved['A'] is None   # B kept as own (original work); A stays a cache record
                print(f'{label:3} {name:8}: in_cache/kept {cnt} (expected {(want_in, want_kept)}), saved work A {saved["A"]}, B {saved["B"]}'
                      + ('' if label == 'old' else ('  ok' if good else '  FAILED')))
                if label == 'new':
                    ok = ok and good
        print('all checks passed' if ok else 'FAILED')
        sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
