#!/usr/bin/env python3
"""Hint test: solve the position after a predicted answer first, then the first-move position itself.

usage: hint_test.py TESTS.json WORKDIR SECONDS [--jobs 3] [--tt-mb 1024] [--only a05,b05]

Idea. A first word w hands over its last syllable t. The 94 start-syllable results (SOLVED_KO.md) say who
wins when t is received with no word used. After w only w is missing, so the answer known for t (its winning
first move, or for a losing t the refutation of each reply) is a likely answer here too. The solver is not
changed: the hint only decides which position is solved first.
  stage a: the position after [w, r] (or [w, r, q]), r = known answer for t.
  stage b: the position [w] itself, with the shared proven cache (PROVEN_DIR) that stage a filled.
Only a stage-b certificate of [w], accepted by verify_v4 with the target list's input sha256, decides w.
A stage-a result alone is a verified result for the deeper position, not a decision for [w].

TESTS.json: {"tests": [{"name": "a05", "of": "p05", "stage": "a", "syllable": "순", "history": ["순발력", "역습"],
                        "input_sha256": null}, ...]}   (input_sha256: checked when given, e.g. for stage b)
Each test runs once, SECONDS of search, fresh state (no state.tt), one core, JOBS at a time.
Result: WORKDIR/<name>/run.json with search, certificate-writing and verification times kept apart.
'mover' is the verified result for the side to move after the history: W or L.
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
BASIC = HERE.parent
sys.path.insert(0, str(BASIC.parent / 'guopsaem_root' / 'verifier_v3'))
sys.path.insert(0, str(BASIC.parent / 'guopsaem_root' / 'tools'))
from verify_v3 import ModelV3  # noqa: E402
import solve_common as sc  # noqa: E402

DICT = BASIC / 'words_817.txt'


def say(msg):
    print(time.strftime('%H:%M:%S'), msg, flush=True)


def main():
    tests_path, work, seconds = sys.argv[1:4]
    rest = sys.argv[4:]
    opt = {'--jobs': 3, '--tt-mb': 1024, '--only': ''}
    for i in range(0, len(rest), 2):
        opt[rest[i]] = type(opt[rest[i]])(rest[i + 1])
    work = Path(work); work.mkdir(parents=True, exist_ok=True)
    seconds = float(seconds)
    tests = json.loads(Path(tests_path).read_text(encoding='utf-8'))['tests']
    if opt['--only']:
        only = set(opt['--only'].split(','))
        tests = [t for t in tests if t['name'] in only]
    model = ModelV3(DICT.read_bytes(), 817)

    def one(t):
        d = work / t['name']; d.mkdir(exist_ok=True)
        out = d / 'run.json'
        if out.exists():
            return json.loads(out.read_text(encoding='utf-8'))
        pos = {'initial_syllable': t['syllable'], 'history': t['history']}
        (d / 'pos.json').write_bytes(json.dumps(pos, ensure_ascii=False).encode('utf-8'))
        cur, counts, _ = model.position(pos)
        inp = model.numeric_input(cur, counts)
        if t.get('input_sha256'):
            assert hashlib.sha256(inp).hexdigest() == t['input_sha256'], f'{t["name"]}: position differs from the target list'
        (d / 'in.txt').write_bytes(inp)
        proof = d / 'proof.v4.gz'
        t0 = time.time()
        sol = sc.solve(d / 'in.txt', proof, seconds, opt['--tt-mb'], tt=None, log=d / 'run.log')
        rec = {'name': t['name'], 'of': t.get('of'), 'stage': t.get('stage'), 'syllable': t['syllable'],
               'history': t['history'], 'seconds_limit': seconds, 'tt_mb': opt['--tt-mb'],
               'proven_dir': os.environ.get('PROVEN_DIR'), 'search_seconds': sol.get('seconds'),
               'mid_calls': sol.get('mid_calls'), 'solver_result': sol.get('result'), 'reason': sol.get('reason'),
               'proof_nodes': sol.get('proof_nodes'), 'proof_seconds': sol.get('emit_seconds'),
               'proof_error': sol.get('proof_error'), 'proven': sol.get('proven'),
               'solve_wall_seconds': round(time.time() - t0, 1), 'decided': False}
        if sol.get('result') in ('win', 'loss') and not sol.get('proof_error') and proof.exists():
            want = 'W' if sol['result'] == 'win' else 'L'
            t1 = time.time()
            ok, v = sc.verify(DICT, 817, d / 'pos.json', proof, d / 'in.txt', want, sol.get('proof_nodes', 0))
            rec.update(verify_wall_seconds=round(time.time() - t1, 2), verify_seconds=v.get('elapsed_seconds'),
                       verify=v, proof_bytes=proof.stat().st_size, decided=bool(ok))
            if ok:
                rec['mover'] = want
        elif proof.exists():
            proof.unlink()
        out.write_text(json.dumps(rec, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
        h = ' '.join(t['history'])
        if rec['decided']:
            say(f'  {t["name"]} [{h}]: 둘 차례인 쪽 {"승" if rec["mover"] == "W" else "패"} (검증 통과) 탐색 {rec["search_seconds"]:.1f}초, '
                f'증명 {rec["proof_nodes"]:,}국면 생성 {rec["proof_seconds"]:.1f}초, 검증 {rec["verify_wall_seconds"]:.1f}초')
        else:
            say(f'  {t["name"]} [{h}]: 미확정 ({sol.get("reason", sol.get("result"))}, 탐색 {rec["search_seconds"] or 0:.0f}초)')
        return rec

    say(f'[시작] {len(tests)}개, 국면당 탐색 {int(seconds)}초, 동시에 {opt["--jobs"]}개, 공유 캐시 {os.environ.get("PROVEN_DIR")}')
    with ThreadPoolExecutor(opt['--jobs']) as ex:
        recs = list(ex.map(one, tests))
    say(f'[끝] 검증 통과 {sum(1 for r in recs if r.get("decided"))}개 / {len(recs)}개')


if __name__ == '__main__':
    main()
