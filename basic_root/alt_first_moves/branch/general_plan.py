#!/usr/bin/env python3
"""Fix the order of one general1 round before it runs (the same rule as run 6, written down as a tool).

usage: general_plan.py RUN TAG SCRATCH_DIR
  writes results/general1/plan_run<RUN>.json and SCRATCH_DIR/g1_r<RUN>_resume.txt, g1_r<RUN>_untried.txt

Resumes: tried and unconfirmed, cumulative search under the 600 s cap (at least 5 s left), the longest waiting first
  (the end of the last attempt, oldest first); each gets at most 120 s more this round. Items at the cap are held.
Untried: the syllables in the queue's order, one item of each in turn (the queue's order inside a syllable), so the
  round does not pile on one syllable. A first attempt gets at most 120 s.
The order depends only on the records of earlier runs, never on pn/dn.
"""
from collections import OrderedDict
import json
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
RES = HERE.parent / 'results' / 'general1'
WORK = Path('/home/user/AI-/.work/general1')


def main():
    run, tag, scratch = int(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    q = json.loads((HERE / 'general1_queue.json').read_text(encoding='utf-8'))
    idx = {c['case']: c for c in json.loads((RES / 'INDEX.json').read_text(encoding='utf-8'))['cases']}
    cases = {c['name']: c for c in q['cases']}
    res, held = [], []
    for n, c in idx.items():
        if c['status'] != 'tried_unconfirmed':
            continue
        r = json.loads((WORK / n / 'run.json').read_text(encoding='utf-8'))
        end = time.mktime(time.strptime(r['started'], '%Y-%m-%d %H:%M:%S')) + r['solver_wall_seconds']
        cum = float(r['solver'].get('total_search_seconds') or r['solver']['seconds'])
        item = {'name': n, 'line': cases[n]['position']['initial_syllable'] + ': ' + ' → '.join(cases[n]['position']['history']),
                'cumulative': round(cum, 6), 'last_end': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(end)),
                'this_round_max': round(min(120, 600 - cum), 6)}
        (res if 600 - cum >= 5 else held).append(item)
    res.sort(key=lambda x: x['last_end'])
    by = OrderedDict()
    for c in q['cases']:
        if idx[c['name']]['status'] == 'untried':
            by.setdefault(c['position']['initial_syllable'], []).append(c['name'])
    rr, k = [], 0
    while any(k < len(v) for v in by.values()):
        for v in by.values():
            if k < len(v):
                rr.append(v[k])
        k += 1
    plan = {'run': run, 'created': time.strftime('%Y-%m-%d'), 'tag': tag,
            'rule': 'search 1,800 s in all: resumes 600 s (each at most 120 s more, cumulative cap 600 s, longest waiting first), '
                    'untried 1,200 s (first attempt at most 120 s each, syllables in turn). Unused time of one pool goes to the other, recorded.',
            'resume_order': res, 'held_at_cap': held, 'untried_order': rr, 'untried_by_syllable': {s: len(v) for s, v in by.items()}}
    (RES / f'plan_run{run}.json').write_text(json.dumps(plan, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    (scratch / f'g1_r{run}_resume.txt').write_text(','.join(x['name'] for x in res))
    (scratch / f'g1_r{run}_untried.txt').write_text(','.join(rr))
    print('resume', [(x['name'], x['line'], x['cumulative'], x['last_end'], x['this_round_max']) for x in res])
    print('held', [(x['name'], x['line']) for x in held])
    print('untried', len(rr), plan['untried_by_syllable'], rr[:12])


if __name__ == '__main__':
    main()
