#!/usr/bin/env python3
"""Record a run that a container restart cut off, so the next run continues with the right budget.

usage: record_interrupt.py WORKDIR NAME PHASE CARRIED_SECONDS LOST_NOTE [SPENT_SECONDS]

An interrupted run writes no phase<N>.json. Its search up to the last checkpoint of state.tt is carried into
the next run; the search after that checkpoint is lost. This writes WORKDIR/NAME/phase<PHASE>.json
(PHASE like '2a') with:
  search_seconds = CARRIED_SECONDS  (search time saved in state.tt; checkpoints come every
                                     max(60, 60 x tt_mb / 1024) seconds, so count the checkpoints
                                     from the run's start to the state.tt modification time)
  lost_search    = LOST_NOTE        (what was lost after the last checkpoint, in words)
  spent_seconds  = SPENT_SECONDS    (optional: search time the interrupted run really used, carried + lost;
                                     it stays in the position's total used time. Without it the total is
                                     marked as a lower bound.)
run_batch.py then counts CARRIED_SECONDS as earlier search. Run the remaining seconds under a new phase name,
e.g. run_batch.py ... 2b <600 - total so far> --only NAME. Example from the first batch: results/batch1/p05.phase2a.json.
"""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from phase_time import totals  # noqa: E402


def main():
    work, name, phase, carried, lost = sys.argv[1:6]
    spent = float(sys.argv[6]) if len(sys.argv) > 6 else None
    assert spent is None or spent >= float(carried), 'SPENT_SECONDS is carried + lost'
    d = Path(work) / name
    out = d / f'phase{phase}.json'
    assert not out.exists(), f'{out} already exists'
    earlier = [json.loads(f.read_text(encoding='utf-8')) for f in sorted(d.glob('phase*.json'))]
    assert not any(r.get('decided') for r in earlier), 'this position is already decided'
    first = earlier[0]
    before, spent_before, _ = totals(earlier)
    rec = {'name': name, 'id': first['id'], 'syllable': first['syllable'], 'word': first['word'], 'phase': phase,
           'search_seconds_before': before, 'search_seconds': float(carried), 'mid_calls': None,
           'search_seconds_total': round(before + float(carried), 3), 'solver_result': 'interrupted',
           'spent_seconds_before': spent_before, 'spent_seconds': spent,
           'spent_seconds_total': round(spent_before + (spent if spent is not None else float(carried)), 3),
           'reason': 'container_restart', 'decided': False, 'carried_into_state': float(carried) > 0,
           'lost_search': lost,
           'note': 'container restart: only the search up to the last state.tt checkpoint is carried and counted; '
                   'the node count of this part is unknown'}
    out.write_text(json.dumps(rec, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(out, rec['search_seconds_total'])


if __name__ == '__main__':
    main()
