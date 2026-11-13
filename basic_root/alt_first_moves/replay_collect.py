#!/usr/bin/env python3
"""Copy replay_test.py results into results/NAME/ as phase records that report.py understands.

usage: replay_collect.py NAME WORKDIR [WORKDIR ...]
Each WORKDIR/<case>/result.json becomes results/NAME/<case>.phase1.json: the whole record (both runs, every
time) plus the top-level fields of a run_batch.py record, taken from the run whose certificate was ACCEPTED
(the replay run if it was accepted, else the direct run). A case with no accepted certificate stays undecided.
spent_seconds counts the search time of both runs: all time used on the position in this experiment.
"""
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent


def to_phase(rec):
    b, a = rec.get('replay'), rec.get('direct')      # a batch may have run only one kind
    runs = [x for x in (b, a) if x]
    dec = next((x for x in runs if x['decided']), None)
    shown = dec or runs[0]
    spent = round(sum(x.get('search_seconds') or 0 for x in runs), 3)
    out = dict(rec)
    out.update(phase='1', phase_seconds=rec['seconds_limit'], decided=bool(dec),
               method=None if dec is None else ('replay' if dec is b else 'direct'),
               solver_result=shown['solver_result'], reason=shown.get('reason'), mid_calls=shown.get('mid_calls'),
               search_seconds=shown.get('search_seconds'), search_seconds_before=0.0, resumed=False,
               search_seconds_total=round(shown.get('search_seconds') or 0, 3),
               spent_seconds=spent, spent_seconds_before=0.0, spent_seconds_total=spent)
    if dec:
        out.update(first_move=dec['first_move'], reply=dec.get('reply'), proof_nodes=dec['proof_nodes'],
                   proof_bytes=dec['proof_bytes'], proof_seconds=dec['proof_seconds'], verify_seconds=dec['verify_seconds'],
                   verify={'proof_sha256': dec['proof_sha256'], 'position_sha256': rec['position_sha256'],
                           'input_sha256': rec['input_sha256'], 'verifier': dec['verifier'], 'acceptance': dec['acceptance'],
                           'result_for_player_to_move': 'W' if dec['first_move'] == 'lose' else 'L'})
    return out


def main():
    dst = HERE / 'results' / sys.argv[1]
    dst.mkdir(parents=True, exist_ok=True)
    n = 0
    for work in sys.argv[2:]:
        for f in sorted(Path(work).glob('*/result.json')):
            rec = json.loads(f.read_text(encoding='utf-8'))
            (dst / f'{f.parent.name}.phase1.json').write_text(json.dumps(to_phase(rec), ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
            n += 1
    print(n, 'records ->', dst)


if __name__ == '__main__':
    main()
