#!/usr/bin/env python3
"""Solve a batch of 'other first move' positions of the 817-word study and verify what gets decided.

usage: run_batch.py PICKS.json WORKDIR PHASE SECONDS [--jobs 3] [--tt-mb 1024] [--only p01,p05]

PICKS.json: {"picks": [{"name": "p01", "id": "격/격돌", "syllable": "격", "word": "격돌", "input_sha256": ...}, ...]}
For each pick the position is {"initial_syllable": syllable, "history": [word]}: the position right after
the receiver's first word, the other side to move.

One phase = one solver run of SECONDS (search time only) per position, one core each, JOBS at a time.
The search state is kept in WORKDIR/<name>/state.tt, so a later phase of the same position continues from it.
A decided position gets its certificate (route-proof-v4) checked at once by the C++ verify_v4 with every
acceptance condition of guopsaem_root/tools/solve_common.verify; only a position whose certificate is accepted
counts as decided, and only then is state.tt deleted. A position that was solved but whose certificate could not
be written or was not accepted stays undecided and keeps its state: the next phase has the result at once and
writes the certificate again. If the disk cannot take a checkpoint, the position is not run at all.
Times (phase_time.py): search_seconds_total = search carried in the saved state; spent_seconds_total = all search
time used on the position, including runs whose state was lost.
Search time, certificate-writing time and verification time are recorded separately.
Result of each run: WORKDIR/<name>/phase<PHASE>.json. Re-running skips what is already done.

Solver result 'win' means the side to move (the opponent of the receiver) wins: the first word LOSES for
the receiver, and 'reply' is the opponent's winning answer. 'loss' means the first word WINS.
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
BASIC = HERE.parent
sys.path.insert(0, str(BASIC.parent / 'guopsaem_root' / 'verifier_v3'))
sys.path.insert(0, str(BASIC.parent / 'guopsaem_root' / 'tools'))
from verify_v3 import ModelV3  # noqa: E402
import solve_common as sc  # noqa: E402
from phase_time import phase_key, totals  # noqa: E402

DICT = BASIC / 'words_817.txt'
TT_SAVE_MAX = 2_000_000   # entries kept for an undecided position (64 MB)


def say(msg):
    print(time.strftime('%H:%M:%S'), msg, flush=True)


def main():
    picks_path, work, phase, seconds = sys.argv[1:5]
    rest = sys.argv[5:]
    opt = {'--jobs': 3, '--tt-mb': 1024, '--only': ''}
    for i in range(0, len(rest), 2):
        opt[rest[i]] = type(opt[rest[i]])(rest[i + 1])
    work = Path(work); work.mkdir(parents=True, exist_ok=True)
    seconds = float(seconds)
    picks = json.loads(Path(picks_path).read_text(encoding='utf-8'))['picks']
    if opt['--only']:
        only = set(opt['--only'].split(','))
        picks = [p for p in picks if p['name'] in only]
    model = ModelV3(DICT.read_bytes(), 817)
    words_of = {}
    for w in model.words:
        words_of.setdefault(model.word_group(w), []).append(w)

    def one(p):
        d = work / p['name']; d.mkdir(exist_ok=True)
        out = d / f'phase{phase}.json'
        if out.exists():
            return json.loads(out.read_text(encoding='utf-8'))
        earlier = [json.loads(f.read_text(encoding='utf-8')) for f in d.glob('phase*.json')]
        earlier.sort(key=lambda r: phase_key(r.get('phase')))
        if any(r.get('decided') for r in earlier):
            return next(r for r in earlier if r.get('decided'))
        carried_before, spent_before, spent_lower = totals(earlier)
        pos = {'initial_syllable': p['syllable'], 'history': [p['word']]}
        pos_bytes = json.dumps(pos, ensure_ascii=False).encode('utf-8')
        cur, counts, _ = model.position(pos)
        inp = model.numeric_input(cur, counts)
        assert hashlib.sha256(inp).hexdigest() == p['input_sha256'], f'{p["id"]}: position differs from the target list'
        (d / 'pos.json').write_bytes(pos_bytes)
        (d / 'in.txt').write_bytes(inp)
        proof = d / f'proof.phase{phase}.v4.gz'
        t0 = time.time()
        try:
            sol = sc.solve(d / 'in.txt', proof, seconds, opt['--tt-mb'], tt=d / 'state.tt', log=d / f'phase{phase}.log',
                           keep_unknown=True, tt_save_max=TT_SAVE_MAX)
        except sc.LowDisk as e:
            say(f'  {p["name"]} {p["id"]}: 시작하지 않음 (디스크 부족, 저장 상태는 그대로 둠): {e}')
            return {'name': p['name'], 'id': p['id'], 'decided': False, 'not_run': str(e)}
        solve_wall = time.time() - t0
        resumed = bool(sol.get('state_loaded'))
        recovered = None
        if not resumed:
            carried_before = 0.0      # nothing was loaded: this run starts the carried chain again
        elif (sol.get('carried_seconds') or 0) > 0:
            # The state file itself says how much search it holds. If that is more than the phase records add up
            # to, a run was cut off (container restart) after saving: its saved part is carried and counted now;
            # what it searched after its last checkpoint is unknown, so the spent total becomes a lower bound.
            in_state = round(sol['carried_seconds'], 3)
            if in_state > carried_before + 1:
                recovered = round(in_state - carried_before, 3)
                spent_before = round(spent_before + recovered, 3)
                spent_lower = True
            carried_before = in_state
        rec = {'name': p['name'], 'id': p['id'], 'syllable': p['syllable'], 'word': p['word'], 'phase': phase,
               'phase_seconds': seconds, 'tt_mb': opt['--tt-mb'],
               'search_seconds_before': carried_before, 'spent_seconds_before': spent_before, 'resumed': resumed,
               'search_seconds': sol.get('seconds'), 'mid_calls': sol.get('mid_calls'),
               'solver_result': sol.get('result'), 'reason': sol.get('reason'), 'pn': sol.get('pn'), 'dn': sol.get('dn'),
               'tt_loaded': sol.get('tt_loaded'), 'tt_saved': sol.get('tt_saved'),
               'proof_nodes': sol.get('proof_nodes'), 'proof_seconds': sol.get('emit_seconds'),
               'proof_error': sol.get('proof_error'), 'run_note': sol.get('run_note'),
               'tt_save_error': sol.get('tt_save_error') or None, 'state_set_aside': sol.get('state_set_aside'),
               'recovered_from_interrupted_run_seconds': recovered,
               'solve_wall_seconds': round(solve_wall, 1), 'decided': False}
        rec['search_seconds_total'] = round(carried_before + (rec['search_seconds'] or 0), 3)
        rec['spent_seconds_total'] = round(spent_before + (rec['search_seconds'] or 0), 3)
        if spent_lower:
            rec['spent_is_lower_bound'] = True
        if sol.get('result') in ('win', 'loss') and not sol.get('proof_error') and proof.exists():
            want = 'W' if sol['result'] == 'win' else 'L'
            t1 = time.time()
            ok, v = sc.verify(DICT, 817, d / 'pos.json', proof, d / 'in.txt', want, sol.get('proof_nodes', 0))
            rec['verify_wall_seconds'] = round(time.time() - t1, 2)
            rec['verify_seconds'] = v.get('elapsed_seconds')
            rec['verify'] = v
            rec['proof_bytes'] = proof.stat().st_size
            rec['decided'] = bool(ok)
            rec['state_released'] = sc.release_state(d / 'state.tt', ok, proof)   # only after acceptance
            if not ok:
                rec['problem'] = 'solved, but the certificate was not accepted; the saved state is kept'
            if ok:
                rec['first_move'] = 'lose' if sol['result'] == 'win' else 'win'
                if sol['result'] == 'win' and sol.get('best_group', -1) >= 0:
                    rec['reply'] = sorted(words_of[sol['best_group']])
        elif sol.get('result') in ('win', 'loss'):
            rec['problem'] = f'solved, but no certificate ({sol.get("proof_error") or "file missing"}); the saved state is kept'
        elif proof.exists():
            proof.unlink()
        rec['state_kept'] = (d / 'state.tt').exists()
        out.write_text(json.dumps(rec, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
        if rec['decided']:
            say(f'  {p["name"]} {p["id"]}: 첫 수 {"패" if rec["first_move"] == "lose" else "승"} (검증 통과) '
                f'탐색 {rec["search_seconds_total"]:.0f}초, 증명 {rec["proof_nodes"]:,}국면 생성 {rec["proof_seconds"]:.1f}초, 검증 {rec["verify_wall_seconds"]:.1f}초'
                + (f', 반박 {"·".join(rec["reply"])}' if rec.get('reply') else ''))
        else:
            say(f'  {p["name"]} {p["id"]}: 미확정 ({sol.get("reason", sol.get("result"))}, 이어받은 탐색 {rec["search_seconds_total"]:.0f}초, '
                f'총사용 {rec["spent_seconds_total"]:.0f}초)'
                + (f' 검증 실패: {rec["verify"].get("error") or rec["verify"].get("acceptance")}' if 'verify' in rec else '')
                + (f' [{rec["problem"]}]' if rec.get('problem') else ''))
        return rec

    say(f'[시작] {len(picks)}개 국면, 단계 {phase}, 국면당 탐색 {int(seconds)}초, 동시에 {opt["--jobs"]}개, 저장표 {opt["--tt-mb"]}MB')
    with ThreadPoolExecutor(opt['--jobs']) as ex:
        recs = list(ex.map(one, picks))
    dec = [r for r in recs if r.get('decided')]
    say(f'[끝] 확정(검증 통과) {len(dec)}개, 미확정 {len(recs) - len(dec)}개')


if __name__ == '__main__':
    main()
