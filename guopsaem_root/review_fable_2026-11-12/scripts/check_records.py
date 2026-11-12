#!/usr/bin/env python3
"""Consistency check of the stored run records of the 817 'other first moves' study.   usage: check_records.py REPO"""
import glob
import json
import sys
from pathlib import Path

res = Path(sys.argv[1]) / 'basic_root/alt_first_moves/results'
rows = flagged = decided = 0
for f in sorted(glob.glob(str(res / '*/*.phase*.json'))):
    r = json.load(open(f, encoding='utf-8'))
    v = r.get('verify') or {}
    acc = v.get('acceptance')
    sr, dec = r.get('solver_result'), r.get('decided')
    flag = ''
    if r.get('search_seconds_before') and r.get('tt_loaded') in (0, None) and r.get('search_seconds'):
        flag += ' NOT-RESUMED?'
    if dec and not (acc and all(acc.values())):
        flag += ' DECIDED-WITHOUT-ACCEPT'
    if dec and ((sr == 'win') != (v.get('result_for_player_to_move') == 'W') or (r.get('first_move') == 'lose') != (sr == 'win')):
        flag += ' INCONSISTENT'
    if sr in ('win', 'loss') and not dec:
        flag += ' SOLVED-NOT-DECIDED'
    if flag or r.get('run_note') or r.get('proof_error'):
        print(Path(f).parent.name + '/' + Path(f).name, r.get('phase'), sr, dec, r.get('search_seconds_before'),
              r.get('search_seconds'), r.get('tt_loaded'), r.get('tt_saved'), r.get('run_note'), r.get('proof_error'), flag)
    rows += 1
    flagged += bool(flag)
    decided += bool(dec)
print(rows, 'records; flagged', flagged)
print(decided, 'decided records')
