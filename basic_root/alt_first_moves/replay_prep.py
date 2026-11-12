#!/usr/bin/env python3
"""Source certificate for strategy replay: solve 'syllable T received, no word used' and keep the certificate.

usage: replay_prep.py T WORKDIR SECONDS [TT_MB]        (one solver run per call; call again to continue)

WORKDIR/T/ gets pos.json, in.txt, proof.v4.gz, runs.jsonl and, once the certificate is accepted by verify_v4
(every acceptance condition of solve_common.verify), prep.json with the cost of preparing this source:
all search time used (also runs that a restart cut off: add a line {"event": "lost", "seconds": S, "note": ...}
to runs.jsonl by hand, as record_interrupt.py does for batches), certificate-writing time and verification time.
The search state is checkpointed in state.tt every 60 s and loaded by the next call; it is deleted only after
the certificate is accepted. The source is only a hint for replay_test.py - a replayed position is decided by
its OWN certificate - but it is verified here anyway, so every file kept is a checked certificate.
"""
import hashlib
import json
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


def main():
    t, work, seconds = sys.argv[1:4]
    ttmb = sys.argv[4] if len(sys.argv) > 4 else '1024'
    d = Path(work) / t
    d.mkdir(parents=True, exist_ok=True)
    m = ModelV3(DICT.read_bytes(), 817)
    pos = {'initial_syllable': t, 'history': []}
    (d / 'pos.json').write_bytes(json.dumps(pos, ensure_ascii=False).encode('utf-8'))
    c, k, _ = m.position(pos)
    (d / 'in.txt').write_bytes(m.numeric_input(c, k))
    proof, state, log = d / 'proof.v4.gz', d / 'state.tt', d / 'runs.jsonl'
    if (d / 'prep.json').exists():
        print((d / 'prep.json').read_text(encoding='utf-8'))
        return
    if not proof.exists():
        cmd = [sc.SOLVER, str(d / 'in.txt'), '--seconds', seconds, '--tt-mb', ttmb, '--threads', '1', '--proof', str(proof),
               '--proof-format', 'v4', '--tt-save', str(state), '--checkpoint-seconds', '60', '--tt-save-max', '2000000']
        if state.exists():
            cmd += ['--tt-load', str(state)]
        with open(log, 'a') as f:
            f.write(json.dumps({'event': 'start', 'time': time.strftime('%Y-%m-%d %H:%M:%S'), 'cmd': cmd[1:]}) + '\n')
            f.flush()
            t0 = time.time()
            r = subprocess.run(cmd, capture_output=True, text=True)
            f.write(json.dumps({'event': 'end', 'time': time.strftime('%Y-%m-%d %H:%M:%S'), 'returncode': r.returncode,
                                'wall_seconds': round(time.time() - t0, 2),
                                'solver': sc.parse_solver_output(r.stdout, r.returncode)}) + '\n')
    if not proof.exists():
        print(json.dumps({'syllable': t, 'prepared': False}, ensure_ascii=False))
        return
    events = [json.loads(x) for x in log.read_text(encoding='utf-8').splitlines() if x.strip()]
    ends = [e for e in events if e['event'] == 'end']
    last = ends[-1]['solver']
    want = 'W' if last['result'] == 'win' else 'L'
    t1 = time.time()
    ok, v = sc.verify(DICT, 817, d / 'pos.json', proof, d / 'in.txt', want, last.get('proof_nodes', 0))
    verify_wall = round(time.time() - t1, 2)
    if not ok:
        print(json.dumps({'syllable': t, 'prepared': False, 'verify': v}, ensure_ascii=False))
        return
    sc.release_state(state, ok, proof)
    lost = [e for e in events if e['event'] == 'lost']
    starts = [e for e in events if e['event'] == 'start']
    prep = {'syllable': t, 'vertex': m.names[c], 'result_for_receiver': want, 'runs': len(ends),
            'search_seconds_spent': round(sum(e['solver'].get('seconds') or 0 for e in ends) + sum(e.get('seconds') or 0 for e in lost), 3),
            'lost_runs': [{'seconds': e.get('seconds'), 'note': e.get('note')} for e in lost],
            'spent_is_lower_bound': any(e.get('seconds') is None for e in lost),   # a lost run of unknown length
            'unfinished_starts': len(starts) - len(ends),
            'mid_calls': sum(e['solver'].get('mid_calls') or 0 for e in ends),
            'proof_nodes': last.get('proof_nodes'), 'proof_seconds': last.get('emit_seconds'),
            'solver_wall_seconds': round(sum(e.get('wall_seconds') or 0 for e in ends), 2) or None,
            'verify_seconds': v.get('elapsed_seconds'), 'verify_wall_seconds': verify_wall,
            'proof_bytes': proof.stat().st_size, 'proof_sha256': v['proof_sha256'], 'position_sha256': v['position_sha256'],
            'input_sha256': v['input_sha256'], 'tt_mb': int(ttmb), 'acceptance': v['acceptance'], 'verifier': v['verifier'],
            'solver_sha256': hashlib.sha256(Path(sc.SOLVER).read_bytes()).hexdigest()}
    (d / 'prep.json').write_text(json.dumps(prep, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(json.dumps(prep, ensure_ascii=False))


if __name__ == '__main__':
    main()
