#!/usr/bin/env python3
"""One solving pass over the target syllables (first presentation, empty history).

Syllables that land on the same model vertex are solved once; the certificate is then
verified for every one of them (see solve_common.verify for the acceptance conditions).
Defaults: solver_v5, route-proof-v4 certificates, C++ verify_v4 (see solve_common).

Restart-safe in two ways:
 * a syllable whose result file holds a verified result, or an unknown from a run at least
   as long, is skipped;
 * a job that was running when the container restarted continues from its search-state
   checkpoint (WORKDIR/tt/<syllable>.tt, written every CHECKPOINT_SECONDS) instead of
   starting over. The checkpoint is deleted when the job ends (kept for an undecided job only
   with KEEP_UNKNOWN_TT=1).
Several runner instances can share one WORKDIR (claims). Run detached (setsid nohup).

usage: run_pass.py DICT WORD_COUNT SYLLABLES WORKDIR SECONDS TT_MB JOBS
"""
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'verifier_v3'))
sys.path.insert(0, str(ROOT / 'tools'))
from verify_v3 import ModelV3  # noqa: E402
import solve_common as sc  # noqa: E402


def main():
    dic, nwords, sylfile, work, seconds, ttmb, jobs = sys.argv[1:8]
    seconds, jobs = float(seconds), int(jobs)
    work = Path(work)
    for d in ('pos', 'in', 'proof', 'log', 'res', 'claim', 'tt'):
        (work / d).mkdir(parents=True, exist_ok=True)
    m = ModelV3(open(dic, 'rb').read(), int(nwords))
    groups = {}
    for s in open(sylfile, encoding='utf-8').read().split():
        groups.setdefault(m.vertex_of(s), []).append(s)

    def todo(rep):
        f = work / 'res' / f'{rep}.json'
        if not f.exists():
            return True
        r = json.loads(f.read_text(encoding='utf-8'))
        if r.get('verified'):
            return False
        return r['solver'].get('result') not in ('win', 'loss') and r['solver'].get('seconds', 0) < seconds - 1

    def write_position(s):
        pos = {"initial_syllable": s, "history": []}
        posf, inf = work / 'pos' / f'{s}.json', work / 'in' / f'{s}.txt'
        posf.write_text(json.dumps(pos, ensure_ascii=False), encoding='utf-8')
        cur, counts, _ = m.position(pos)
        inf.write_bytes(m.numeric_input(cur, counts))
        return posf, inf, cur

    def run(members):
        rep = members[0]
        claim = work / 'claim' / f'{rep}.{int(seconds)}'
        try:  # another live runner instance may already have taken it
            claim.mkdir()
        except FileExistsError:
            try:
                os.kill(int((claim / 'pid').read_text()), 0)
                return rep, 'claimed', False
            except (OSError, ValueError):
                pass  # its runner is gone (e.g. container restart): take it over
        (claim / 'pid').write_text(str(os.getpid()))
        sc.wait_for_disk(work, rep)
        posf, inf, cur = write_position(rep)
        proof = work / 'proof' / f'{rep}.jsonl.gz'
        sol = sc.solve(inf, proof, seconds, ttmb, tt=work / 'tt' / f'{rep}.tt', log=work / 'log' / f'{rep}.out')
        res = {'syllable': rep, 'members': members, 'vertex': m.names[cur], 'solver': sol,
               'solver_binary': sc.SOLVER, 'proof_format': sc.PROOF_FORMAT, 'verified': False}
        if sol.get('result') in ('win', 'loss') and not sol.get('proof_error'):
            want = 'W' if sol['result'] == 'win' else 'L'
            res['verify'] = {}
            ok = True
            for s in members:
                p2, i2, _ = write_position(s)
                good, vr = sc.verify(dic, nwords, p2, proof, i2, want, sol.get('proof_nodes', 0))
                res['verify'][s] = vr
                ok = ok and good
            res['verified'] = ok
        elif proof.exists() and sol.get('result') not in ('win', 'loss'):
            proof.unlink()
        (work / 'res' / f'{rep}.json').write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
        return rep, sol.get('result'), res['verified']

    pending = [members for members in groups.values() if todo(members[0])]
    print(json.dumps({'vertices': len(groups), 'pending': len(pending), 'solver': sc.SOLVER,
                      'proof_format': sc.PROOF_FORMAT}, ensure_ascii=False), flush=True)
    with ThreadPoolExecutor(jobs) as ex:
        for rep, result, ok in ex.map(run, pending):
            if result != 'claimed':
                print(time.strftime('%H:%M:%S'), rep, {'win': '받으면 승', 'loss': '받으면 패'}.get(result, '결론 없음'),
                      '(검증 통과)' if ok else ('(검증 실패!)' if result in ('win', 'loss') else ''), flush=True)
    (work / f'DONE_{int(seconds)}s').write_text('done\n')


if __name__ == '__main__':
    main()
