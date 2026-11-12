#!/usr/bin/env python3
"""Restart behaviour of replay_test.py and replay_prep.py (2026-11-12).   usage: test_replay_restart.py [WORKDIR]

  A  replay_test.py is killed (with its solver) in the middle of the second run of a case. The same command is
     run again: the finished first run is not repeated, the cut-off run continues from its checkpoint with the
     budget that is left, and its record says that a run was interrupted.
  B  replay_prep.py finds a damaged certificate: it is moved aside, the position is solved again and accepted.
  C  replay_prep.py is killed during the search: the next call notes the interrupted run and goes on.
Needs SOLVER / VERIFY_V4 / REPLAY_SOLVER as the tools do, and the 역 source of results/replay1. About 1 minute.
"""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / 'guopsaem_root' / 'tools'))
import solve_common as sc  # noqa: E402

env = dict(os.environ, REPLAY_CHECKPOINT_SECONDS='2')


def killed_after(cmd, seconds):
    p = subprocess.Popen(cmd, env=env, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(seconds)
    os.killpg(p.pid, signal.SIGKILL)
    p.wait()


def events(path):
    return [json.loads(x) for x in Path(path).read_text(encoding='utf-8').splitlines() if x.strip()]


def main():
    work = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix='replay_restart_'))
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    out = {}
    # ---- A
    cases = work / 'cases.json'
    cases.write_text(json.dumps({'cases': [{'name': 't01', 'id': '순/순발력', 'syllable': '순', 'word': '순발력', 'source': '역'}]},
                                ensure_ascii=False), encoding='utf-8')
    cmd = [sys.executable, str(HERE / 'replay_test.py'), str(cases), str(HERE / 'results' / 'replay1' / 'sources'), str(work / 'run'),
           '--seconds', '10', '--tt-mb', '256']
    killed_after(cmd, 17)                       # direct: about 10 s (undecided); the replay run is cut off in its 7th second or so
    d = work / 'run' / 't01'
    assert (d / 'direct.json').exists() and not (d / 'replay.json').exists(), 'A: expected a finished direct run and an unfinished replay run'
    direct_before = (d / 'direct.json').read_bytes()
    saved = sc.state_carried_seconds(d / 'replay.state.tt')
    assert saved and 1.5 <= saved <= 9, f'A: the cut-off run left {saved} s in its state'
    r = subprocess.run(cmd, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-500:]
    assert (d / 'direct.json').read_bytes() == direct_before, 'A: the finished direct run was repeated'
    assert sum(e['event'] == 'start' for e in events(d / 'direct.runs.jsonl')) == 1
    rep = json.loads((d / 'replay.json').read_text(encoding='utf-8'))
    ev = [e['event'] for e in events(d / 'replay.runs.jsonl')]
    assert ev == ['start', 'interrupted', 'start', 'end'], ev
    assert rep['interrupted_runs'] == 1 and rep['spent_is_lower_bound'] and rep['solver_runs'] == 1, rep
    assert 9.5 <= rep['search_seconds'] <= 11.5, f'A: budget 10 s, search recorded {rep["search_seconds"]}'
    second = events(d / 'replay.runs.jsonl')[-1]['solver']
    assert abs(second['carried_seconds'] - saved) < 0.011 and second['seconds'] <= 10 - saved + 1, second
    res = json.loads((d / 'result.json').read_text(encoding='utf-8'))
    assert 'direct' in res and 'replay' in res
    out['A'] = {'saved_by_cut_off_run': saved, 'second_run_seconds': second['seconds'], 'recorded_search_seconds': rep['search_seconds']}
    # ---- B
    prep = [sys.executable, str(HERE / 'replay_prep.py'), '급', str(work / 'src'), '60', '256']
    r = subprocess.run(prep, env=env, capture_output=True, text=True)
    s = work / 'src' / '급'
    first = json.loads((s / 'prep.json').read_text(encoding='utf-8'))
    (s / 'prep.json').unlink()
    good = (s / 'proof.v4.gz').read_bytes()
    (s / 'proof.v4.gz').write_bytes(good[:len(good) // 2])            # a certificate cut in half
    (s / 'proof.v4.gz.body.tmp').write_bytes(b'left over')
    r = subprocess.run(prep, env=env, capture_output=True, text=True)
    again = json.loads((s / 'prep.json').read_text(encoding='utf-8'))
    assert again['rejected_certificates'] == 1 and again['proof_sha256'] == first['proof_sha256'], again
    assert len(list(s.glob('proof.v4.gz.rejected-*'))) == 1 and not (s / 'proof.v4.gz.body.tmp').exists()
    assert (s / 'proof.v4.gz').read_bytes() == good and not (s / 'state.tt').exists()
    out['B'] = 'damaged certificate set aside, solved again, same certificate as before'
    # ---- C
    prep = [sys.executable, str(HERE / 'replay_prep.py'), '역', str(work / 'src'), '8', '256']
    killed_after(prep, 6)
    r = subprocess.run(prep[:-2] + ['3', '256'], env=env, capture_output=True, text=True)
    ev = events(work / 'src' / '역' / 'runs.jsonl')
    assert [e['event'] for e in ev] == ['start', 'interrupted', 'start', 'end'], [e['event'] for e in ev]
    assert ev[1]['seconds_in_state'] and ev[3]['solver']['carried_seconds'] == ev[1]['seconds_in_state'], ev[1]
    assert json.loads(r.stdout.strip().splitlines()[-1])['prepared'] is False and (work / 'src' / '역' / 'state.tt').exists()
    out['C'] = {'saved_by_cut_off_run': ev[1]['seconds_in_state'], 'next_run_total': ev[3]['solver']['total_search_seconds']}
    print(json.dumps({'ok': True, **out}, ensure_ascii=False))


if __name__ == '__main__':
    main()
