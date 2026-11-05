#!/usr/bin/env python3
"""Shared pieces of the batch runners: one solver call with save/resume, and one verification
with every acceptance condition (Astra review 1-3 and 1-4, 2026-11-05).

Environment (defaults in brackets):
  SOLVER              solver binary [/home/user/AI-/.work/measure/solver_v5]
  PROOF_FORMAT        v4 or v3 [v4]
  VERIFY_V4           C++ verifier binary for v4 certificates [/home/user/AI-/.work/measure/verify_v4]
  CHECKPOINT_SECONDS  search-state checkpoint interval while a job runs [auto: 60 s per GB of table, at least 60 s]
  KEEP_UNKNOWN_TT     1 = keep the saved search state of a job that ended undecided [0]
  MIN_FREE_GB         do not start a job (or do not save state) below this free disk [4]
  VERIFY_LOCK         lock file so that only one big verification runs at a time
  BIG_PROOF_NODES     certificates at least this big take the lock [200000]
  PROVEN_DIR          if set: shared proven-state cache. Every job loads PROVEN_DIR/merged.pc and saves
                      its own proven entries, which are then merged into merged.pc (under a lock), keeping
                      at most PROVEN_MAX records with the largest work [half of the job's table entries].
                      Only search hints: certificates are still rebuilt and verified.
  PCMERGE             merge tool [/home/user/AI-/.work/measure/pcmerge]

A certificate is accepted only if ALL hold: verifier exit code 0, "verified": true, the
expected result, "state_storage": "deflate-exact" (v4), and the dictionary, position, input
and certificate SHA-256 reported by the verifier equal the hashes of the files we hold.
"""
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOLVER = os.environ.get('SOLVER', os.environ.get('SOLVER_V4', '/home/user/AI-/.work/measure/solver_v5'))
PROOF_FORMAT = os.environ.get('PROOF_FORMAT', 'v4')
VERIFY_V4 = os.environ.get('VERIFY_V4', '/home/user/AI-/.work/measure/verify_v4')
CHECKPOINT = os.environ.get('CHECKPOINT_SECONDS', 'auto')
KEEP_UNKNOWN_TT = os.environ.get('KEEP_UNKNOWN_TT', '0') == '1'
MIN_FREE_GB = float(os.environ.get('MIN_FREE_GB', '4'))
LOCK = Path(os.environ.get('VERIFY_LOCK', '/home/user/AI-/.work/verify.lock'))
BIG = int(os.environ.get('BIG_PROOF_NODES', '200000'))
PROVEN_DIR = os.environ.get('PROVEN_DIR')
PCMERGE = os.environ.get('PCMERGE', '/home/user/AI-/.work/measure/pcmerge')


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def free_gb(path):
    return shutil.disk_usage(path).free / 2**30


def solver_cmd(inp, proof, seconds, ttmb, tt=None):
    """Solver command line. With tt (a path), the search state is checkpointed there every
    CHECKPOINT seconds and loaded again if the file exists, so a job interrupted by a restart
    continues instead of starting over. Returns (cmd, note)."""
    cmd = [SOLVER, str(inp), '--seconds', str(seconds), '--tt-mb', str(ttmb), '--threads', '1',
           '--proof', str(proof), '--proof-format', PROOF_FORMAT]
    note = ''
    if tt is not None:
        tt = Path(tt)
        if Path(str(tt) + '.tmp').exists():
            Path(str(tt) + '.tmp').unlink()          # a checkpoint cut short by a restart
        if free_gb(tt.parent) - int(ttmb) / 1024 >= MIN_FREE_GB:
            if tt.exists():
                cmd += ['--tt-load', str(tt)]
                note = 'resumed from saved state'
            every = max(60.0, 60.0 * int(ttmb) / 1024) if CHECKPOINT == 'auto' else float(CHECKPOINT)
            cmd += ['--tt-save', str(tt), '--checkpoint-seconds', str(every)]
        else:
            note = f'no state saving (free disk {free_gb(tt.parent):.1f} GB)'
    if PROVEN_DIR:
        pdir = Path(PROVEN_DIR); (pdir / 'jobs').mkdir(parents=True, exist_ok=True)
        if (pdir / 'merged.pc').exists():
            cmd += ['--proven-load', str(pdir / 'merged.pc')]
        cmd += ['--proven-save', str(pdir / 'jobs' / (Path(proof).name.split('.')[0] + '_' + str(os.getpid()) + '_'
                                                       + str(abs(hash(str(proof))) % 10**8) + '.pc'))]
    return cmd, note


def merge_proven(cmd, ttmb):
    """After a job: fold its proven entries into PROVEN_DIR/merged.pc (one merge at a time)."""
    if not PROVEN_DIR or '--proven-save' not in cmd:
        return None
    pdir = Path(PROVEN_DIR)
    job = Path(cmd[cmd.index('--proven-save') + 1])
    if not job.exists():
        return {'merge': 'no job file'}
    cap = int(os.environ.get('PROVEN_MAX', str((int(ttmb) << 20) // 32 // 2)))
    with open(pdir / 'merge.lock', 'w') as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        ins = ([str(pdir / 'merged.pc')] if (pdir / 'merged.pc').exists() else []) + [str(job)]
        r = subprocess.run([PCMERGE, str(pdir / 'merged.pc'), str(cap)] + ins, capture_output=True, text=True)
    if r.returncode == 0:
        job.unlink()
        try:
            return json.loads(r.stdout)
        except ValueError:
            return {'merge': r.stdout[-200:]}
    return {'merge_error': r.stderr[-300:]}


def finish_tt(tt, sol, keep_unknown):
    """After a job: drop the saved state if decided (or if undecided states are not kept)."""
    if tt is None:
        return
    tt = Path(tt)
    if Path(str(tt) + '.tmp').exists():
        Path(str(tt) + '.tmp').unlink()
    if tt.exists() and (sol.get('result') in ('win', 'loss') or not keep_unknown):
        tt.unlink()


def parse_solver_output(text, returncode):
    try:
        return json.loads(text.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {'result': 'error', 'returncode': returncode, 'tail': text[-400:]}


def solve(inp, proof, seconds, ttmb, tt=None, log=None, keep_unknown=None):
    """Run the solver once (blocking); see solver_cmd. Returns the solver's JSON."""
    cmd, note = solver_cmd(inp, proof, seconds, ttmb, tt)
    out = subprocess.run(cmd, capture_output=True, text=True)
    if log is not None:
        Path(log).write_text(' '.join(cmd) + '\n' + out.stdout + out.stderr)
    sol = parse_solver_output(out.stdout, out.returncode)
    if note:
        sol['run_note'] = note
    for line in out.stderr.splitlines():
        if line.startswith('{"proven'):
            try:
                sol['proven'] = json.loads(line)
            except ValueError:
                pass
    pm = merge_proven(cmd, ttmb)
    if pm is not None:
        sol['proven_merge'] = pm
    finish_tt(tt, sol, KEEP_UNKNOWN_TT if keep_unknown is None else keep_unknown)
    return sol


def verify(dic, nwords, pos, proof, inp, want, nodes=0):
    """Verify one certificate; returns (accepted, record)."""
    fmt = 'v4' if PROOF_FORMAT == 'v4' else 'v3'
    if fmt == 'v4':
        cmd = [VERIFY_V4]
    else:
        cmd = [sys.executable, str(ROOT / 'verifier_v3' / 'verify_v3.py')]
    cmd += ['--dictionary', str(dic), '--expected-word-count', str(nwords), '--position', str(pos),
            '--proof', str(proof), '--input', str(inp)]

    def run():
        return subprocess.run(cmd, capture_output=True, text=True)
    if nodes >= BIG:
        with open(LOCK, 'w') as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            v = run()
    else:
        v = run()
    try:
        r = json.loads(v.stdout)
    except ValueError:
        r = {'verified': False, 'error': (v.stderr or v.stdout)[-400:]}
    r['exit_code'] = v.returncode
    r['verifier'] = 'verify_v4 (C++)' if fmt == 'v4' else 'verify_v3.py'
    checks = {
        'exit_code_0': v.returncode == 0,
        'verified_true': r.get('verified') is True,
        'result': r.get('result_for_player_to_move') == want,
        'state_storage': fmt != 'v4' or r.get('state_storage') == 'deflate-exact',
        'dictionary_sha256': r.get('dictionary_sha256') == sha256_file(dic),
        'position_sha256': r.get('position_sha256') == sha256_file(pos),
        'input_sha256': r.get('input_sha256') == sha256_file(inp),
        'proof_sha256': r.get('proof_sha256') == sha256_file(proof),
    }
    r['acceptance'] = checks
    return all(checks.values()), r


def wait_for_disk(path, label):
    while free_gb(path) < MIN_FREE_GB:
        print(time.strftime('%H:%M:%S'), label, f'waiting: free disk {free_gb(path):.1f} GB', flush=True)
        time.sleep(60)
