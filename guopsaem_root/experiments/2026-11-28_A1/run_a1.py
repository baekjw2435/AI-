#!/usr/bin/env python3
"""A1 (2026-11-28): basic presentation of given syllables of the 3,683-word list (no word used), one solver each, in parallel.

usage: run_a1.py WORK SECONDS SYL:TT_MB:KEEP [SYL:TT_MB:KEEP ...]
Search limit SECONDS per syllable (solver_v5, certificates v4); proof writing (solver emit) and verify_v4 are timed
separately. A solved position is verified with verify_v4 (all acceptance conditions of solve_common.verify). An
unsolved one keeps its search state WORK/<syl>/state.tt (KEEP table entries with the most work) for a later resume.
Writes WORK/<syl>/result.json.
"""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

G = Path('/home/user/AI-/guopsaem_root')
sys.path.insert(0, str(G / 'verifier_v3')); sys.path.insert(0, str(G / 'tools'))
from verify_v3 import ModelV3  # noqa: E402
import solve_common as sc  # noqa: E402

DIC = G / 'words_3683.txt'


def main():
    work, seconds = Path(sys.argv[1]), float(sys.argv[2])
    jobs = [a.split(':') for a in sys.argv[3:]]
    m = ModelV3(DIC.read_bytes(), 3683)

    def one(job):
        syl, ttmb, keep = job[0], int(job[1]), int(job[2])
        d = work / syl; d.mkdir(parents=True, exist_ok=True)
        pos = {'initial_syllable': syl, 'history': []}
        (d / 'pos.json').write_bytes(json.dumps(pos, ensure_ascii=False).encode('utf-8'))
        cur, k, _ = m.position(pos)
        (d / 'in.txt').write_bytes(m.numeric_input(cur, k))
        t0 = time.time()
        sol = sc.solve(d / 'in.txt', d / 'proof.v4.gz', seconds, ttmb, tt=d / 'state.tt', log=d / 'solver.log',
                       keep_unknown=True, tt_save_max=keep)
        wall = time.time() - t0
        rec = {'syllable': syl, 'vertex': m.names[cur], 'position': pos, 'dictionary': str(DIC), 'search_limit_seconds': seconds,
               'tt_mb': ttmb, 'tt_save_max': keep, 'started': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(t0)),
               'solver_wall_seconds': round(wall, 2), 'solver': sol, 'solver_binary': sc.SOLVER, 'solver_sha256': sc.sha256_file(sc.SOLVER)}
        if sol.get('result') in ('win', 'loss') and not sol.get('proof_error'):
            want = 'W' if sol['result'] == 'win' else 'L'
            t1 = time.time()
            ok, vr = sc.verify(str(DIC), 3683, d / 'pos.json', d / 'proof.v4.gz', d / 'in.txt', want, sol.get('proof_nodes', 0))
            rec.update(verify=vr, verify_wall_seconds=round(time.time() - t1, 2), accepted=ok,
                       proof_sha256=sc.sha256_file(d / 'proof.v4.gz'))
        else:
            rec['accepted'] = False
        (d / 'result.json').write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding='utf-8')
        s = rec['solver']
        return syl, s.get('result'), round(s.get('seconds', 0), 1), s.get('emit_seconds'), rec.get('verify_wall_seconds'), rec['accepted']

    with ThreadPoolExecutor(len(jobs)) as ex:
        for r in ex.map(one, jobs):
            print(r, flush=True)


if __name__ == '__main__':
    main()
