#!/usr/bin/env python3
"""Prepare source certificates for several syllables, a few at a time (replay_prep.py for each).

usage: replay_sources.py WORKDIR SECONDS TT_MB JOBS SYLLABLE [SYLLABLE ...]
Each syllable is 'T received, no word used'. SECONDS is the search limit of THIS call (the solver's --seconds);
the search time already in a saved state is not counted against it. A syllable that is not solved within SECONDS
keeps its saved search state; calling again continues it for another SECONDS. Prints one line per syllable when it is done.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
os.environ.setdefault('BIG_PROOF_NODES', str(10**12))


def main():
    work, seconds, ttmb, jobs = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])

    def one(t):
        r = subprocess.run([sys.executable, str(HERE / 'replay_prep.py'), t, work, seconds, ttmb], capture_output=True, text=True)
        try:
            j = json.loads(r.stdout.strip().splitlines()[-1]) if '\n{' not in r.stdout.strip() else json.loads(r.stdout)
        except (ValueError, IndexError):
            j = {'syllable': t, 'prepared': False, 'error': (r.stdout + r.stderr)[-300:]}
        ok = 'proof_sha256' in j
        print(time.strftime('%H:%M:%S'), t, ('받으면 ' + ('승' if j['result_for_receiver'] == 'W' else '패')
              + f", 탐색 {j['search_seconds_spent']:.1f}초, 증명 {j['proof_nodes']:,}국면, 검증 {j['verify_seconds']:.1f}초") if ok
              else f"준비 안 됨: {j.get('result') or j.get('problem') or j.get('error')}", flush=True)
        return t, ok

    with ThreadPoolExecutor(jobs) as ex:
        done = list(ex.map(one, sys.argv[5:]))
    print(json.dumps({'prepared': [t for t, ok in done if ok], 'not_prepared': [t for t, ok in done if not ok]}, ensure_ascii=False))


if __name__ == '__main__':
    main()
