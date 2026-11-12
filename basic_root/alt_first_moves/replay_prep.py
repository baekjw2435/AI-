#!/usr/bin/env python3
"""Source certificate for strategy replay: solve 'syllable T received, no word used' and keep the certificate.

usage: replay_prep.py T WORKDIR SECONDS [TT_MB]        (one solver run per call; call again to continue)

WORKDIR/T/ gets pos.json, in.txt, proof.v4.gz, runs.jsonl and, once the certificate is accepted by verify_v4
(every acceptance condition of solve_common.verify), prep.json with the cost of preparing this source: all
search time used, certificate-writing time and verification time.
The source is only a hint for replay_test.py - a replayed position is decided by its OWN certificate - but it
is verified here anyway, so every file kept is a checked certificate.

Restarts (2026-11-12):
  * the search state is checkpointed in state.tt every 60 s and loaded by the next call; it is deleted only
    after the certificate is accepted;
  * a run that was cut off is noticed at the next call (a 'start' line without its 'end' line in runs.jsonl) and
    written down as 'interrupted' with the search seconds its last checkpoint saved (read from state.tt). What it
    searched after that checkpoint (at most the 60 s interval) is unknown: the spent time is then a lower bound;
  * leftovers of a certificate writer that was cut off (proof.v4.gz.tmp, .body.tmp) are removed;
  * a certificate that is not accepted (damaged, or a run log that does not match it) is moved aside as
    proof.v4.gz.rejected-<time> and the position is solved again from the saved state in the same call, so a
    bad file cannot block the source for good.
A run lost before this tool kept a log can be added by hand: {"event": "lost", "seconds": S or null, "note": ...}.
"""
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
BASIC = HERE.parent
sys.path.insert(0, str(BASIC.parent / 'guopsaem_root' / 'verifier_v3'))
sys.path.insert(0, str(BASIC.parent / 'guopsaem_root' / 'tools'))
from verify_v3 import ModelV3  # noqa: E402
import solve_common as sc  # noqa: E402

DICT = BASIC / 'words_817.txt'
CHECKPOINT = float(os.environ.get('REPLAY_CHECKPOINT_SECONDS', '60'))   # tests use a short interval
KEEP = 2000000


def now():
    return time.strftime('%Y-%m-%d %H:%M:%S')


def root_result(proof):
    """'W' or 'L' written in the certificate's last line (its root), or None if the file cannot be read."""
    try:
        last = None
        with gzip.open(proof, 'rb') as f:
            for last in f:
                pass
        return json.loads(last)['r']
    except (OSError, EOFError, ValueError, KeyError, TypeError):
        return None


def main():
    t, work, seconds = sys.argv[1:4]
    ttmb = sys.argv[4] if len(sys.argv) > 4 else '1024'
    d = Path(work) / t
    d.mkdir(parents=True, exist_ok=True)
    if (d / 'prep.json').exists():
        print((d / 'prep.json').read_text(encoding='utf-8'))
        return
    m = ModelV3(DICT.read_bytes(), 817)
    pos = {'initial_syllable': t, 'history': []}
    (d / 'pos.json').write_bytes(json.dumps(pos, ensure_ascii=False).encode('utf-8'))
    c, k, _ = m.position(pos)
    (d / 'in.txt').write_bytes(m.numeric_input(c, k))
    proof, state, log = d / 'proof.v4.gz', d / 'state.tt', d / 'runs.jsonl'

    def events():
        return [json.loads(x) for x in log.read_text(encoding='utf-8').splitlines() if x.strip()] if log.exists() else []

    def add(ev):
        with open(log, 'a') as f:
            f.write(json.dumps(ev, ensure_ascii=False) + '\n')

    ev = events()
    if ev and ev[-1]['event'] == 'start':
        add({'event': 'interrupted', 'time': now(), 'started': ev[-1]['time'], 'seconds_in_state': sc.state_carried_seconds(state),
             'note': f'this run did not finish (restart). Its checkpoints are in state.tt; the search after the last one '
                     f'(at most {CHECKPOINT:g} s) is lost and not counted'})
    for suffix in ('.tmp', '.body.tmp', '.tmp.body.tmp'):
        if Path(str(proof) + suffix).exists():
            Path(str(proof) + suffix).unlink()
    v = None
    for attempt in (1, 2):
        if not proof.exists():
            need_gb = sc.state_file_bytes(ttmb, KEEP) / 2**30
            if sc.free_gb(d) - need_gb < sc.MIN_FREE_GB:
                raise sc.LowDisk(f'free disk {sc.free_gb(d):.2f} GB: not started, nothing deleted')
            cmd = [sc.SOLVER, str(d / 'in.txt'), '--seconds', seconds, '--tt-mb', ttmb, '--threads', '1', '--proof', str(proof),
                   '--proof-format', 'v4', '--tt-save', str(state), '--checkpoint-seconds', str(CHECKPOINT), '--tt-save-max', str(KEEP)]
            if state.exists():
                cmd += ['--tt-load', str(state)]
            add({'event': 'start', 'time': now(), 'cmd': cmd[1:]})
            t0 = time.time()
            r = subprocess.run(cmd, capture_output=True, text=True)
            sol = sc.parse_solver_output(r.stdout, r.returncode)
            aside = sc.set_aside_refused_state(state, r.stderr) if sol.get('result') == 'error' else None
            add({'event': 'end', 'time': now(), 'returncode': r.returncode, 'wall_seconds': round(time.time() - t0, 2), 'solver': sol,
                 **({'state_set_aside': aside} if aside else {})})
            if not proof.exists():
                print(json.dumps({'syllable': t, 'prepared': False, 'result': sol.get('result'), 'reason': sol.get('reason'),
                                  'proof_error': sol.get('proof_error')}, ensure_ascii=False))
                return
        want = root_result(proof)
        nodes = max((e['solver'].get('proof_nodes') or 0 for e in events() if e['event'] == 'end'), default=0)
        t1 = time.time()
        ok, v = (False, {'error': 'the certificate cannot be read'}) if want is None else \
            sc.verify(DICT, 817, d / 'pos.json', proof, d / 'in.txt', want, nodes)
        verify_wall = round(time.time() - t1, 2)
        if ok:
            break
        aside = proof.with_name(proof.name + time.strftime('.rejected-%Y%m%d-%H%M%S'))
        proof.rename(aside)
        add({'event': 'rejected', 'time': now(), 'moved_to': aside.name, 'error': v.get('error'), 'acceptance': v.get('acceptance')})
    else:
        print(json.dumps({'syllable': t, 'prepared': False, 'problem': 'the certificate was rejected twice; see runs.jsonl'}, ensure_ascii=False))
        return
    sc.release_state(state, ok, proof)
    ev = events()
    ends = [e for e in ev if e['event'] == 'end']
    last = ends[-1]['solver'] if ends else {}
    lost = [e for e in ev if e['event'] in ('lost', 'interrupted')]
    counted = sum(e['solver'].get('seconds') or 0 for e in ends) + sum(e.get('seconds') or 0 for e in ev if e['event'] == 'lost')
    in_state = last.get('total_search_seconds') or 0          # includes what interrupted runs saved
    prep = {'syllable': t, 'vertex': m.names[c], 'result_for_receiver': want, 'runs': len(ends),
            'search_seconds_spent': round(max(counted, in_state), 3),
            'spent_is_lower_bound': any(e['event'] == 'interrupted' or e.get('seconds') is None for e in lost),
            'lost_runs': [{'event': e['event'], 'seconds': e.get('seconds'), 'note': e.get('note')} for e in lost],
            'rejected_certificates': sum(1 for e in ev if e['event'] == 'rejected'),
            'mid_calls': sum(e['solver'].get('mid_calls') or 0 for e in ends),
            'proof_nodes': v.get('certificate_nodes'), 'proof_seconds': last.get('emit_seconds'),
            'solver_wall_seconds': round(sum(e.get('wall_seconds') or 0 for e in ends), 2) or None,
            'verify_seconds': v.get('elapsed_seconds'), 'verify_wall_seconds': verify_wall,
            'proof_bytes': proof.stat().st_size, 'proof_sha256': v['proof_sha256'], 'position_sha256': v['position_sha256'],
            'input_sha256': v['input_sha256'], 'tt_mb': int(ttmb), 'acceptance': v['acceptance'], 'verifier': v['verifier'],
            'solver_sha256': hashlib.sha256(Path(sc.SOLVER).read_bytes()).hexdigest()}
    (d / 'prep.json').write_text(json.dumps(prep, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(json.dumps(prep, ensure_ascii=False))


if __name__ == '__main__':
    main()
