#!/usr/bin/env python3
"""Saved-state rules of solve_common (2026-11-12): a state is never lost before its certificate is accepted.

usage: test_state_keeping.py [WORKDIR]     (needs SOLVER and VERIFY_V4, see solve_common.py; about 20 s)
Position: 817 words, 승 received, 승급 played (solved in about 1 s).
  A  solved, certificate cannot be written  -> state kept; the next run loads it, has the result at once,
     writes the certificate; the state is deleted only after verify() accepted it
  B  certificate not accepted               -> release_state() keeps the state
  C  low disk                               -> LowDisk before anything runs, the old state is untouched;
     the real checkpoint size is used (a 2,048 MB table with 2,000,000 kept entries needs 0.06 GB, not 2 GB)
  D  undecided run, low disk afterwards     -> state kept
  E  damaged state file                     -> renamed aside (kept), the next run starts fresh
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault('CHECKPOINT_SECONDS', '1')
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'verifier_v3'))
import solve_common as sc  # noqa: E402
from verify_v3 import ModelV3  # noqa: E402

DICT = ROOT.parent / 'basic_root' / 'words_817.txt'


def main():
    work = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix='state_keeping_'))
    work.mkdir(parents=True, exist_ok=True)
    m = ModelV3(DICT.read_bytes(), 817)
    pos = {'initial_syllable': '승', 'history': ['승급']}
    (work / 'pos.json').write_bytes(json.dumps(pos, ensure_ascii=False).encode('utf-8'))
    c, k, _ = m.position(pos)
    (work / 'in.txt').write_bytes(m.numeric_input(c, k))
    tt, proof = work / 'state.tt', work / 'p.v4.gz'
    for f in (tt, proof):
        if f.exists():
            f.unlink()
    out = {}

    # A: solved, but the certificate cannot be written
    sol = sc.solve(work / 'in.txt', work / 'no_such_dir' / 'p.v4.gz', 60, 256, tt=tt, keep_unknown=True, tt_save_max=2000000)
    assert sol['result'] == 'win' and sol['proof_error'], sol
    assert tt.exists() and sol['state_kept'], 'A: the state of a solved position without certificate must stay'
    first_nodes = sol['mid_calls']
    sol2 = sc.solve(work / 'in.txt', proof, 60, 256, tt=tt, keep_unknown=True, tt_save_max=2000000)
    assert sol2['result'] == 'win' and not sol2['proof_error'] and sol2['state_loaded'], sol2
    assert sol2['mid_calls'] <= 1024, f'A: the resumed run searched again ({sol2["mid_calls"]} nodes)'
    assert tt.exists(), 'A: solve() itself must not delete the state'
    out['A'] = {'first_run_nodes': first_nodes, 'resumed_run_nodes': sol2['mid_calls'], 'proof_nodes': sol2['proof_nodes']}

    # B: a rejected certificate keeps the state (here: the wrong expected result)
    bad, _ = sc.verify(DICT, 817, work / 'pos.json', proof, work / 'in.txt', 'L', sol2['proof_nodes'])
    assert bad is False and sc.release_state(tt, bad, proof) is False and tt.exists(), 'B'
    ok, v = sc.verify(DICT, 817, work / 'pos.json', proof, work / 'in.txt', 'W', sol2['proof_nodes'])
    assert ok is True, v
    assert sc.release_state(tt, ok, work / 'gone.gz') is False and tt.exists(), 'B: no certificate file, no release'
    assert sc.release_state(tt, ok, proof) is True and not tt.exists(), 'B: accepted -> released'
    out['B'] = 'kept until accepted, then released'

    # C: low disk
    tt.write_bytes(b'old state')
    real_free = sc.free_gb
    try:
        sc.MIN_FREE_GB = 4.0
        sc.free_gb = lambda p: 3.9
        try:
            sc.solver_cmd('in.txt', 'p.gz', 480, 2048, tt=tt, tt_save_max=2000000)
            raise AssertionError('C: LowDisk expected')
        except sc.LowDisk as e:
            out['C_message'] = str(e)
        assert tt.read_bytes() == b'old state', 'C: the old state must be untouched'
        sc.free_gb = lambda p: 5.0          # the old rule wanted 2 GB + 4 GB here and dropped --tt-load
        cmd, note = sc.solver_cmd('in.txt', 'p.gz', 480, 2048, tt=tt, tt_save_max=2000000)
        assert '--tt-load' in cmd and '--tt-save' in cmd, cmd
        try:                                 # keeping every entry of a 2 GB table really needs 2 GB
            sc.solver_cmd('in.txt', 'p.gz', 480, 2048, tt=tt, tt_save_max=0)
            raise AssertionError('C: LowDisk expected for a full-table state')
        except sc.LowDisk:
            pass
        # D: an undecided run is never dropped because the disk is low
        sc.free_gb = lambda p: 0.1
        sc.finish_tt(tt, {'result': 'unknown'}, True)
        assert tt.read_bytes() == b'old state', 'D'
        sc.finish_tt(tt, {'result': 'win'}, False)
        assert tt.exists(), 'D: a solved state is only released after acceptance'
    finally:
        sc.free_gb = real_free
        sc.MIN_FREE_GB = float(os.environ.get('MIN_FREE_GB', '4'))
    out['C'] = out['D'] = 'state untouched'

    # E: a damaged state file is set aside, not deleted, and the job can run again
    sol = sc.solve(work / 'in.txt', proof, 60, 256, tt=tt, keep_unknown=True, tt_save_max=2000000)
    assert sol['result'] == 'error' and sol.get('state_set_aside'), sol
    assert Path(sol['state_set_aside']).read_bytes() == b'old state' and not tt.exists(), 'E'
    sol = sc.solve(work / 'in.txt', proof, 60, 256, tt=tt, keep_unknown=True, tt_save_max=2000000)
    assert sol['result'] == 'win' and not sol['state_loaded'], sol
    out['E'] = 'set aside, next run solved from scratch'
    print(json.dumps({'ok': True, **out}, ensure_ascii=False))


if __name__ == '__main__':
    main()
