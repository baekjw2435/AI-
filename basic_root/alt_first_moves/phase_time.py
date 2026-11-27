#!/usr/bin/env python3
"""Time bookkeeping over the phase records of one position (run_batch.py, record_interrupt.py, report.py).

Two totals are kept apart (2026-11-12):
  spent    every second the solver searched this position, also in runs whose saved state was lost later.
           Time already used stays used.
  carried  the search that is inside the saved state the next run loads. A run that did not load the saved
           state ("resumed": false - no file, file refused, first phase) starts this chain again.
A record made by record_interrupt.py may say that more was spent than carried (search after the last checkpoint).
Older records have no "resumed" and no "spent_seconds"; every later phase of those really loaded the state
(tt_loaded was 2,000,000), so they count as resumed and spent = search_seconds.
"""
import re


def phase_key(phase):
    """Order of phases: 1 < 2 < 2a < 2b < 10 (plain string order would put 10 before 2)."""
    m = re.match(r'(\d+)(.*)$', str(phase))
    return (int(m.group(1)), m.group(2)) if m else (10**9, str(phase))


def totals(records):
    """(carried, spent, spent_is_lower_bound) over records of one position, in phase order."""
    carried = spent = 0.0
    lower = False
    for r in sorted(records, key=lambda r: phase_key(r.get('phase'))):
        own = r.get('search_seconds') or 0
        if r.get('resumed') is False:
            carried = 0.0
        carried += own
        spent += r['spent_seconds'] if r.get('spent_seconds') is not None else own
        if r.get('lost_search') and r.get('spent_seconds') is None:
            lower = True          # an interrupted run whose lost part was only described in words
    return round(carried, 3), round(spent, 3), lower
