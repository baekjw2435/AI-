#!/usr/bin/env python3
"""One solving pass over the target syllables (first presentation, empty history).

Syllables that land on the same model vertex are solved once; the proof is then
verified with verify_v3 for every one of them. Resumable: a syllable whose result
file already holds a verified result, or an unknown from a run at least as long,
is skipped. Run detached (setsid nohup) for long passes.

usage: run_pass.py DICT WORD_COUNT SYLLABLES WORKDIR SECONDS TT_MB JOBS [VERIFY_MAX_NODES]
"""
import fcntl
import json
import os
import shutil
import time
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'verifier_v3'))
from verify_v3 import ModelV3  # noqa: E402

SOLVER = os.environ.get('SOLVER_V4', '/home/user/AI-/.work/measure/solver_v4')
LOCK = Path(os.environ.get('VERIFY_LOCK', '/home/user/AI-/.work/verify.lock'))
MIN_FREE_GB = float(os.environ.get('MIN_FREE_GB', '4'))


def main():
    dic, nwords, sylfile, work, seconds, ttmb, jobs = sys.argv[1:8]
    verify_max = int(sys.argv[8]) if len(sys.argv) > 8 else 3_000_000
    seconds, jobs = float(seconds), int(jobs)
    work = Path(work)
    for d in ('pos', 'in', 'proof', 'log', 'res', 'claim'):
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
        while shutil.disk_usage(work).free < MIN_FREE_GB * 2**30:
            print(rep, 'waiting: low disk', flush=True)
            time.sleep(60)
        pos = {"initial_syllable": rep, "history": []}
        posf, inf = work / 'pos' / f'{rep}.json', work / 'in' / f'{rep}.txt'
        posf.write_text(json.dumps(pos, ensure_ascii=False), encoding='utf-8')
        cur, counts, _ = m.position(pos)
        inf.write_bytes(m.numeric_input(cur, counts))
        proof = work / 'proof' / f'{rep}.jsonl.gz'
        out = subprocess.run([SOLVER, str(inf), '--seconds', str(seconds), '--tt-mb', str(ttmb), '--threads', '1',
                              '--proof', str(proof)], capture_output=True, text=True)
        (work / 'log' / f'{rep}.out').write_text(out.stdout + out.stderr)
        try:
            sol = json.loads(out.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            sol = {'result': 'error', 'returncode': out.returncode}
        res = {'syllable': rep, 'members': members, 'vertex': m.names[cur], 'solver': sol, 'verified': False}
        if sol.get('result') in ('win', 'loss') and not sol.get('proof_error'):
            if sol.get('proof_nodes', 0) <= verify_max:
                res['verify'] = {}
                ok = True
                for s in members:
                    p2 = work / 'pos' / f'{s}.json'
                    p2.write_text(json.dumps({"initial_syllable": s, "history": []}, ensure_ascii=False), encoding='utf-8')
                    c2, k2, _ = m.position(json.loads(p2.read_text(encoding='utf-8')))
                    i2 = work / 'in' / f'{s}.txt'
                    i2.write_bytes(m.numeric_input(c2, k2))
                    with open(LOCK, 'w') as lk:  # one verification at a time across all runners
                        fcntl.flock(lk, fcntl.LOCK_EX)
                        v = subprocess.run([sys.executable, str(ROOT / 'verifier_v3' / 'verify_v3.py'), '--dictionary', dic,
                                            '--expected-word-count', str(nwords), '--position', str(p2),
                                            '--proof', str(proof), '--input', str(i2)], capture_output=True, text=True)
                    try:
                        vr = json.loads(v.stdout)
                    except ValueError:
                        vr = {'verified': False, 'error': v.stderr[-500:]}
                    vr['exit_code'] = v.returncode
                    res['verify'][s] = vr
                    want = 'W' if sol['result'] == 'win' else 'L'
                    ok = ok and v.returncode == 0 and vr.get('verified') is True and vr.get('result_for_player_to_move') == want
                res['verified'] = ok
            else:
                res['verify_pending'] = True
        elif proof.exists() and sol.get('result') not in ('win', 'loss'):
            proof.unlink()
        (work / 'res' / f'{rep}.json').write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
        return rep, sol.get('result'), res['verified']

    pending = [members for members in groups.values() if todo(members[0])]
    print(json.dumps({'vertices': len(groups), 'pending': len(pending)}), flush=True)
    with ThreadPoolExecutor(jobs) as ex:
        for rep, result, ok in ex.map(run, pending):
            if result != 'claimed':
                print(time.strftime('%H:%M:%S'), rep, {'win': '받으면 승', 'loss': '받으면 패'}.get(result, '결론 없음'),
                      '(검증 통과)' if ok else '', flush=True)
    (work / f'DONE_{int(seconds)}s').write_text('done\n')


if __name__ == '__main__':
    main()
