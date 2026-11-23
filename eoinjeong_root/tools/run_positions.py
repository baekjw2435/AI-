#!/usr/bin/env python3
"""Solve and verify a list of positions of the 어인정 621-word dictionary.

usage: run_positions.py PLAN.jsonl WORKDIR SECONDS TT_MB JOBS

PLAN.jsonl: one position per line, {"id": "R001", "initial_syllable": "갑", "history": [...]}.
Every position is solved by itself from its full history (no result is copied from another position).

For each position:
  pos/<id>.json    the exact position file given to the verifier
  in/<id>.txt      numeric solver input (ModelV3.position + numeric_input)
  proof/<id>.v4.gz certificate (route-proof-v4), only for a decided position
  tt/<id>.tt       saved search state; deleted only after the certificate was ACCEPTED
  log/<id>.out     solver command and output
  res/<id>.json    solver JSON, verifier JSON, the eight acceptance checks, wall times

A certificate is accepted (확정) only if verify_v4 passes every condition of solve_common.verify:
exit code 0, "verified": true, the expected result, "state_storage": "deflate-exact", and the
dictionary, position, input and certificate SHA-256 equal those of the files we hold.
SECONDS is the search limit of one run; it is never raised here. A position whose result file holds
an accepted result, or an undecided result from a run with the same limit, is skipped (restart-safe).

Environment: SOLVER, VERIFY_V4 (built binaries), see guopsaem_root/tools/solve_common.py.
"""
import hashlib
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parent
sys.path.insert(0, str(REPO / 'guopsaem_root' / 'verifier_v3'))
sys.path.insert(0, str(REPO / 'guopsaem_root' / 'tools'))
from verify_v3 import ModelV3  # noqa: E402
import solve_common as sc  # noqa: E402

DICT = HERE / 'words_621.txt'
NWORDS = 621


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    plan, work, seconds, ttmb, jobs = sys.argv[1:6]
    seconds, ttmb, jobs = float(seconds), int(ttmb), int(jobs)
    work = Path(work)
    for d in ('pos', 'in', 'proof', 'log', 'res', 'tt'):
        (work / d).mkdir(parents=True, exist_ok=True)
    m = ModelV3(DICT.read_bytes(), NWORDS)
    items = [json.loads(x) for x in Path(plan).read_text(encoding='utf-8').splitlines() if x.strip()]

    def todo(it):
        f = work / 'res' / f"{it['id']}.json"
        if not f.exists():
            return True
        r = json.loads(f.read_text(encoding='utf-8'))
        if r.get('accepted'):
            return False
        return r.get('limit_seconds') != seconds

    def run(it):
        pid = it['id']
        position = {'initial_syllable': it['initial_syllable'], 'history': it['history']}
        posf, inf = work / 'pos' / f'{pid}.json', work / 'in' / f'{pid}.txt'
        proof, tt, log = work / 'proof' / f'{pid}.v4.gz', work / 'tt' / f'{pid}.tt', work / 'log' / f'{pid}.out'
        posf.write_text(json.dumps(position, ensure_ascii=False), encoding='utf-8')
        cur, counts, _ = m.position(json.loads(posf.read_text(encoding='utf-8')))
        inf.write_bytes(m.numeric_input(cur, counts))
        t0 = time.time()
        sol = sc.solve(inf, proof, seconds, ttmb, tt=tt, log=log)
        t1 = time.time()
        res = {'id': pid, 'position': position, 'to_move_vertex': m.names[cur],
               'limit_seconds': seconds, 'tt_mb': ttmb, 'solver': sol,
               'solver_binary_sha256': sha(sc.SOLVER), 'verifier_binary_sha256': sha(sc.VERIFY_V4),
               'dictionary_sha256': sha(DICT), 'position_sha256': sha(posf), 'input_sha256': sha(inf),
               'accepted': False, 'wall_solve_seconds': round(t1 - t0, 3)}
        if sol.get('result') in ('win', 'loss') and not sol.get('proof_error') and proof.exists():
            want = 'W' if sol['result'] == 'win' else 'L'
            ok, vr = sc.verify(DICT, NWORDS, posf, proof, inf, want, sol.get('proof_nodes', 0))
            res['wall_verify_seconds'] = round(time.time() - t1, 3)
            res['verify'] = vr
            res['accepted'] = ok
            res['result_for_player_to_move'] = want if ok else None
            res['proof_sha256'] = sha(proof)
            res['proof_bytes'] = proof.stat().st_size
            res['state_released'] = sc.release_state(tt, ok, proof)
        else:
            res['result_for_player_to_move'] = None
            if proof.exists():
                proof.unlink()
        res['state_kept'] = tt.exists()
        tmp = work / 'res' / f'{pid}.json.tmp'
        tmp.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
        os.replace(tmp, work / 'res' / f'{pid}.json')
        return pid, res

    pending = [it for it in items if todo(it)]
    print(json.dumps({'plan': str(plan), 'positions': len(items), 'pending': len(pending), 'limit_seconds': seconds,
                      'tt_mb': ttmb, 'jobs': jobs, 'solver': sc.SOLVER, 'verifier': sc.VERIFY_V4}, ensure_ascii=False),
          flush=True)
    t_start = time.time()
    done = 0
    with ThreadPoolExecutor(jobs) as ex:
        for pid, res in ex.map(run, pending):
            done += 1
            r = res['result_for_player_to_move']
            tag = {'W': '둘 차례인 쪽 승', 'L': '둘 차례인 쪽 패'}.get(r, '미확정')
            if done % 50 == 0 or r is None or res['solver'].get('seconds', 0) > 5:
                print(time.strftime('%H:%M:%S'), f'{done}/{len(pending)}', pid, tag,
                      f"탐색 {res['solver'].get('seconds')}s", flush=True)
    (work / f'DONE_{Path(plan).stem}_{int(seconds)}s').write_text(f'{time.time() - t_start:.1f}\n')


if __name__ == '__main__':
    main()
