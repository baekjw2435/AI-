#!/usr/bin/env python3
"""Focus a few representative positions over several rounds, carrying the saved search state over.

usage: run_focus.py DICT WORD_COUNT FOCUS.json WORKDIR ROUND_SECONDS ROUNDS
FOCUS.json: [{"name": ..., "pos": POS.json, "input": IN.txt, "tt": STATE.tt, "tt_mb": 1024,
              "tt_save_max": 1000000}, ...]   (all positions run at the same time, one core each)
Each round runs every undecided position for ROUND_SECONDS, resuming from its saved state; a decided
position is verified (solve_common.verify, all acceptance conditions) and leaves the focus set.
Results per round: WORKDIR/<name>.round<k>.json; summary: WORKDIR/summary.json. Restart-safe: rounds
already written are skipped, and an interrupted round resumes from the last checkpoint.
"""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import solve_common as sc  # noqa: E402


def say(msg):
    print(time.strftime('%H:%M:%S'), msg, flush=True)


def main():
    dic, nwords, focus_file, work, secs, rounds = sys.argv[1:7]
    work = Path(work); work.mkdir(parents=True, exist_ok=True)
    focus = json.load(open(focus_file, encoding='utf-8'))
    secs, rounds = float(secs), int(rounds)
    summary = {f['name']: {'result': None, 'rounds': []} for f in focus}

    def one(f, k):
        out = work / f'{f["name"]}.round{k}.json'
        if out.exists():
            return json.loads(out.read_text(encoding='utf-8'))
        proof = work / f'{f["name"]}.cert.jsonl.gz'
        t0 = time.time()
        sol = sc.solve(f['input'], proof, secs, f.get('tt_mb', 1024), tt=f['tt'], log=work / f'{f["name"]}.round{k}.log',
                       keep_unknown=True, tt_save_max=f.get('tt_save_max'))
        rec = {'name': f['name'], 'round': k, 'solver': sol, 'wall_s': round(time.time() - t0, 1), 'verified': False}
        if sol.get('result') in ('win', 'loss') and not sol.get('proof_error'):
            want = 'W' if sol['result'] == 'win' else 'L'
            ok, v = sc.verify(dic, nwords, f['pos'], proof, f['input'], want, sol.get('proof_nodes', 0))
            rec['verify'] = v
            rec['verified'] = ok
            rec['state_released'] = sc.release_state(f['tt'], ok, proof)     # only after acceptance
        out.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding='utf-8')
        return rec

    active = list(focus)
    for k in range(1, rounds + 1):
        if not active:
            break
        say(f'[라운드 {k}] {len(active)}개 국면을 {int(secs)}초씩 (저장 상태 이어 쓰기)')
        with ThreadPoolExecutor(len(active)) as ex:
            recs = list(ex.map(lambda f: one(f, k), active))
        still = []
        for f, r in zip(active, recs):
            s = r['solver']
            summary[f['name']]['rounds'].append({'round': k, 'result': s.get('result'), 'mid_calls': s.get('mid_calls'),
                                                 'pn': s.get('pn'), 'dn': s.get('dn'), 'tt_loaded': s.get('tt_loaded'),
                                                 'wall_s': r['wall_s'], 'verified': r['verified']})
            tag = {'win': '둘 차례가 이김', 'loss': '둘 차례가 짐'}.get(s.get('result'), '결론 없음')
            say(f'  {f["name"]}: {tag}' + (' (검증 통과)' if r['verified'] else '') +
                f' / 불러온 상태 {s.get("tt_loaded", 0):,}개, 탐색 {s.get("mid_calls", 0):,}국면, pn {s.get("pn")} dn {s.get("dn")}')
            if r['verified']:
                summary[f['name']]['result'] = 'W' if s['result'] == 'win' else 'L'
            else:
                still.append(f)       # undecided, or solved without an accepted certificate (state kept): try again
        active = still
        (work / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding='utf-8')
    say('[끝] ' + ', '.join(f'{n}: {v["result"] or "미정"}' for n, v in summary.items()))


if __name__ == '__main__':
    main()
