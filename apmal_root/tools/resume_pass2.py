#!/usr/bin/env python3
"""2차(합계 30분) 도중 컨테이너가 다시 켜졌을 때 남은 국면을 이어서 푼다.

계산기(solver_v5)는 탐색 상태(tt/)를 중간중간 저장하고, 그 머리에 그때까지 탐색한 초를 적습니다.
run_positions.py로 2차를 그대로 다시 돌리면 그 국면은 1200초를 통째로 더 받아서 합계가 30분을 넘습니다.
그래서 여기서는 남은 국면마다 '1800초 − 저장된 탐색 초'만 더 풉니다(합계 30분을 넘지 않음).

결과 파일 형식은 run_positions.py와 같습니다. limit_seconds는 2차 한도 1200(split_roots.py가 이것으로 2차를 마친
국면을 가림)이고, 'resumed' 칸에 이어 푼 내용(저장돼 있던 탐색 초, 이번에 준 초, 합계 한도)을 적습니다.
모두 끝나면 run_positions.py와 같은 끝 표시 DONE_roots_1200s를 씁니다. 다시 돌려도 안전합니다.

usage: resume_pass2.py   (환경 변수 SOLVER VERIFY_V4 VERIFY_LOCK TT_SAVE_MAX 는 run_roots_pass2.sh와 같게)
"""
import hashlib, json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parent
sys.path.insert(0, str(REPO / 'guopsaem_root' / 'verifier_v3'))
sys.path.insert(0, str(REPO / 'guopsaem_root' / 'tools'))
from verify_v3 import ModelV3  # noqa: E402
import solve_common as sc  # noqa: E402

DICT, NWORDS = HERE / 'words_534.txt', 534
PLAN, WORK = HERE / 'plans' / 'roots.jsonl', HERE / 'results' / 'roots'
PASS_LIMIT, TOTAL, TTMB, JOBS = 1200.0, 1800.0, 3072, 4


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    m = ModelV3(DICT.read_bytes(), NWORDS)
    items = [json.loads(x) for x in PLAN.read_text(encoding='utf-8').splitlines() if x.strip()]

    def todo(it):
        f = WORK / 'res' / f"{it['id']}.json"
        if not f.exists():
            return True
        r = json.loads(f.read_text(encoding='utf-8'))
        return not r.get('accepted') and r.get('limit_seconds') != PASS_LIMIT

    def run(it):
        pid = it['id']
        position = {'initial_syllable': it['initial_syllable'], 'history': it['history']}
        posf, inf = WORK / 'pos' / f'{pid}.json', WORK / 'in' / f'{pid}.txt'
        proof, tt, log = WORK / 'proof' / f'{pid}.v4.gz', WORK / 'tt' / f'{pid}.tt', WORK / 'log' / f'{pid}.out'
        posf.write_text(json.dumps(position, ensure_ascii=False), encoding='utf-8')
        cur, counts, _ = m.position(json.loads(posf.read_text(encoding='utf-8')))
        inf.write_bytes(m.numeric_input(cur, counts))
        carried = (sc.state_carried_seconds(tt) if tt.exists() else None) or 0.0
        seconds = round(max(TOTAL - carried, 0.0), 3)
        t0 = time.time()
        sol = sc.solve(inf, proof, seconds, TTMB, tt=tt, log=log) if seconds > 0 else {'result': 'unknown', 'seconds': 0}
        t1 = time.time()
        res = {'id': pid, 'position': position, 'to_move_vertex': m.names[cur],
               'limit_seconds': PASS_LIMIT, 'tt_mb': TTMB, 'solver': sol,
               'resumed': {'carried_seconds_before': carried, 'seconds_this_run': seconds, 'total_limit_seconds': TOTAL,
                           'note': '컨테이너 재시작 뒤 이어 풂: 합계 30분을 넘지 않게 남은 초만 줌 (tools/resume_pass2.py)'},
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
        tmp = WORK / 'res' / f'{pid}.json.tmp'
        tmp.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
        os.replace(tmp, WORK / 'res' / f'{pid}.json')
        return pid, res

    pending = [it for it in items if todo(it)]
    print(json.dumps({'tool': 'resume_pass2.py', 'pending': [it['id'] for it in pending], 'total_limit_seconds': TOTAL,
                      'tt_mb': TTMB, 'jobs': JOBS, 'solver': sc.SOLVER, 'verifier': sc.VERIFY_V4}, ensure_ascii=False),
          flush=True)
    t_start = time.time()
    with ThreadPoolExecutor(JOBS) as ex:
        for i, (pid, res) in enumerate(ex.map(run, pending), 1):
            tag = {'W': '둘 차례인 쪽 승', 'L': '둘 차례인 쪽 패'}.get(res['result_for_player_to_move'], '미확정')
            print(time.strftime('%H:%M:%S'), f'{i}/{len(pending)}', pid, tag,
                  f"저장 {res['resumed']['carried_seconds_before']}s + 이번 탐색 {res['solver'].get('seconds')}s", flush=True)
    (WORK / f'DONE_{PLAN.stem}_{int(PASS_LIMIT)}s').write_text(f'{time.time() - t_start:.1f}\n')


if __name__ == '__main__':
    main()
