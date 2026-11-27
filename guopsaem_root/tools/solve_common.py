#!/usr/bin/env python3
"""Shared pieces of the batch runners: one solver call with save/resume, and one verification
with every acceptance condition (Astra review 1-3 and 1-4, 2026-11-05).

Environment (defaults in brackets):
  SOLVER              solver binary [/home/user/AI-/.work/measure/solver_v5]
  PROOF_FORMAT        v4 or v3 [v4]
  VERIFY_V4           C++ verifier binary for v4 certificates [/home/user/AI-/.work/measure/verify_v4]
  CHECKPOINT_SECONDS  search-state checkpoint interval while a job runs [auto: 60 s per GB of table, at least 60 s]
  KEEP_UNKNOWN_TT     1 = keep the saved search state of a job that ended undecided, so a later
                      (longer) run of the same job continues from it [1]
  TT_SAVE_MAX         saved states keep only the N table entries with the most work [1000000 = 32 MB];
                      0 = keep everything (up to the whole table, e.g. 1 GB per job)
  MIN_FREE_GB         free disk that must remain after a job's saved state is written [4]. A job that cannot
                      keep this is NOT started (LowDisk) and an existing saved state is left untouched.
  VERIFY_LOCK         lock file so that only one big verification runs at a time
  BIG_PROOF_NODES     certificates at least this big take the lock [200000]
  PROVEN_DIR          if set: shared proven-state cache. Every job loads PROVEN_DIR/merged.pc and saves
                      its own proven entries, which are then merged into merged.pc (under a lock), keeping
                      at most PROVEN_MAX records with the largest work [half of the job's ACTUAL table entries].
                      Only search hints: certificates are still rebuilt and verified.
  PCMERGE             merge tool [/home/user/AI-/.work/measure/pcmerge]
  PROVEN_LOAD_FRACTION  a job loads at most this fraction of its table slots from the shared cache,
                      the records with the most work first [0.25]. The solver applies it to the ACTUAL
                      table (--proven-load-fraction): the bucket count is rounded down to a power of two,
                      so --tt-mb 3072 gives a 2 GB table (2026-11-07; before, 25% of the requested size
                      was 37.5% of a 3072 MB job's real table).

A certificate is accepted only if ALL hold: verifier exit code 0, "verified": true, the
expected result, "state_storage": "deflate-exact" (v4), and the dictionary, position, input
and certificate SHA-256 reported by the verifier equal the hashes of the files we hold.

Saved search states (2026-11-12, after the Fable review):
  * loading and saving are decided separately: an existing state is ALWAYS loaded (loading needs no disk);
  * if there is not enough disk to save a new state the job is not started (LowDisk) - the old file stays;
  * a state is deleted only by release_state(), i.e. after verify() ACCEPTED the certificate and the
    certificate file is still there. A solved position whose certificate could not be written or was not
    accepted keeps its state (solver_v5 now saves a solved root too), so the next run has the result at once;
  * a state file the solver refuses (damaged, other root) is renamed aside, never deleted;
  * a state file says how much search is inside it (state_carried_seconds): the solver adds each run's search
    time to the file's header at every checkpoint, so after an interrupted run the remaining budget and the
    carried time can be read from the file instead of being reconstructed by hand.
"""
import fcntl
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOLVER = os.environ.get('SOLVER', os.environ.get('SOLVER_V4', '/home/user/AI-/.work/measure/solver_v5'))
PROOF_FORMAT = os.environ.get('PROOF_FORMAT', 'v4')
VERIFY_V4 = os.environ.get('VERIFY_V4', '/home/user/AI-/.work/measure/verify_v4')
CHECKPOINT = os.environ.get('CHECKPOINT_SECONDS', 'auto')
KEEP_UNKNOWN_TT = os.environ.get('KEEP_UNKNOWN_TT', '1') == '1'
TT_SAVE_MAX = int(os.environ.get('TT_SAVE_MAX', '1000000'))
MIN_FREE_GB = float(os.environ.get('MIN_FREE_GB', '4'))
LOCK = Path(os.environ.get('VERIFY_LOCK', '/home/user/AI-/.work/verify.lock'))
BIG = int(os.environ.get('BIG_PROOF_NODES', '200000'))
PROVEN_DIR = os.environ.get('PROVEN_DIR')
PCMERGE = os.environ.get('PCMERGE', '/home/user/AI-/.work/measure/pcmerge')
PROVEN_LOAD_FRACTION = float(os.environ.get('PROVEN_LOAD_FRACTION', '0.25'))


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def free_gb(path):
    return shutil.disk_usage(path).free / 2**30


class LowDisk(RuntimeError):
    """Not enough free disk to save the search state. The job was not started; a saved state is untouched."""


def table_slots(ttmb):
    """Entries of the solver's table for --tt-mb ttmb, as TT::alloc computes them: buckets of four 32-byte
    entries, bucket count rounded DOWN to a power of two (so 3072 MB gives 67,108,864 entries = 2 GB)."""
    want = (int(ttmb) << 20) // (4 * 32)
    nb = 1
    while nb * 2 <= want:
        nb *= 2
    return nb * 4


def state_file_bytes(ttmb, keep_max):
    """Largest size of one saved state: 32 bytes per kept entry (all entries of the table if keep_max is 0),
    plus header and tail. While a checkpoint is written the old file is still there, so this much must be free."""
    slots = table_slots(ttmb)
    return 32 * (min(slots, int(keep_max)) if keep_max else slots) + 128


def solver_cmd(inp, proof, seconds, ttmb, tt=None, tt_save_max=None):
    """Solver command line. With tt (a path), the search state is checkpointed there every
    CHECKPOINT seconds and loaded again if the file exists, so a job interrupted by a restart
    continues instead of starting over. Returns (cmd, note).
    An existing state is always loaded. If the disk cannot take a new checkpoint (its real size, not the
    table size) and still keep MIN_FREE_GB free, LowDisk is raised and nothing is run or deleted."""
    cmd = [SOLVER, str(inp), '--seconds', str(seconds), '--tt-mb', str(ttmb), '--threads', '1',
           '--proof', str(proof), '--proof-format', PROOF_FORMAT]
    note = ''
    if tt is not None:
        tt = Path(tt)
        if Path(str(tt) + '.tmp').exists():
            Path(str(tt) + '.tmp').unlink()          # a checkpoint cut short by a restart
        keep_max = TT_SAVE_MAX if tt_save_max is None else tt_save_max
        need_gb = state_file_bytes(ttmb, keep_max) / 2**30
        free = free_gb(tt.parent)
        if free - need_gb < MIN_FREE_GB:
            raise LowDisk(f'free disk {free:.2f} GB; a checkpoint needs {need_gb:.2f} GB and {MIN_FREE_GB:g} GB must stay free. '
                          f'Job not started' + (f', saved state kept: {tt}' if tt.exists() else ''))
        if tt.exists():
            cmd += ['--tt-load', str(tt)]
            note = 'resumed from saved state'
        every = max(60.0, 60.0 * int(ttmb) / 1024) if CHECKPOINT == 'auto' else float(CHECKPOINT)
        cmd += ['--tt-save', str(tt), '--checkpoint-seconds', str(every)]
        if keep_max:
            cmd += ['--tt-save-max', str(keep_max)]
    if PROVEN_DIR:
        pdir = Path(PROVEN_DIR); (pdir / 'jobs').mkdir(parents=True, exist_ok=True)
        if (pdir / 'merged.pc').exists():
            cmd += ['--proven-load', str(pdir / 'merged.pc'), '--proven-load-fraction', str(PROVEN_LOAD_FRACTION)]
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
    cap = int(os.environ.get('PROVEN_MAX', str(table_slots(ttmb) // 2)))
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
    """After a solver run: tidy up, but never delete the state of a solved position (see release_state) and
    never delete because the disk is low. Only an UNDECIDED state is dropped, and only if the caller does
    not keep undecided states (keep_unknown false)."""
    if tt is None:
        return
    tt = Path(tt)
    if Path(str(tt) + '.tmp').exists():
        Path(str(tt) + '.tmp').unlink()
    if tt.exists() and not keep_unknown and sol.get('result') == 'unknown':
        tt.unlink()


def release_state(tt, accepted, proof=None):
    """Delete a saved search state after its position is finished: `accepted` must be the first value
    verify() returned for this position's certificate (every acceptance condition, including that the
    certificate file on disk has the verified SHA-256), and the certificate file must still exist.
    Returns True if a state file was deleted."""
    if tt is None:
        return False
    tt = Path(tt)
    if accepted is not True or (proof is not None and not Path(proof).exists()):
        return False
    if Path(str(tt) + '.tmp').exists():
        Path(str(tt) + '.tmp').unlink()
    if tt.exists():
        tt.unlink()
        return True
    return False


def state_carried_seconds(tt):
    """Search seconds inside a saved state file, from its header (solver_v5 since 2026-11-12), or None when the
    file is missing, unreadable or was written by an older solver (which left the field 0)."""
    try:
        with open(tt, 'rb') as f:
            head = f.read(72)
        magic, _, _, _, _, _, _, _, carried_cs, _, _ = struct.unpack('<8sQQQQiiiiQQ', head)
    except (OSError, struct.error):
        return None
    if magic[:5] != b'YSTT1' or carried_cs <= 0:
        return None
    return carried_cs / 100.0


def set_aside_refused_state(tt, stderr_text):
    """If the solver refused the saved state (damaged file, other root or options), move it aside so that the
    next run can start; the file is kept for inspection. Returns the new path or None."""
    if tt is None or 'TT file refused' not in (stderr_text or '') and 'cannot open TT file' not in (stderr_text or ''):
        return None
    tt = Path(tt)
    if not tt.exists():
        return None
    aside = tt.with_name(tt.name + time.strftime('.refused-%Y%m%d-%H%M%S'))
    tt.rename(aside)
    return str(aside)


def parse_solver_output(text, returncode):
    try:
        return json.loads(text.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {'result': 'error', 'returncode': returncode, 'tail': text[-400:]}


def solve(inp, proof, seconds, ttmb, tt=None, log=None, keep_unknown=None, tt_save_max=None):
    """Run the solver once (blocking); see solver_cmd (which may raise LowDisk before anything runs).
    Returns the solver's JSON. A saved state is NOT deleted here when the position is solved: call
    release_state(tt, accepted, proof) after verify() accepted the certificate."""
    cmd, note = solver_cmd(inp, proof, seconds, ttmb, tt, tt_save_max)
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
    if sol.get('result') == 'error':
        aside = set_aside_refused_state(tt, out.stderr)
        if aside:
            sol['state_set_aside'] = aside
    finish_tt(tt, sol, KEEP_UNKNOWN_TT if keep_unknown is None else keep_unknown)
    if tt is not None:
        sol['state_loaded'] = '--tt-load' in cmd and (sol.get('tt_loaded') or 0) > 0
        sol['state_kept'] = Path(tt).exists()
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
