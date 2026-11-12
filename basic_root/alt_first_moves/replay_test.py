#!/usr/bin/env python3
"""Strategy replay against direct search, same machine, same limits, same load, everything timed.

usage: replay_test.py CASES.json SOURCES WORKDIR [--seconds 120] [--tt-mb 1024] [--stuck-nodes 200000]
                      [--jobs 1] [--kinds direct,replay] [--only r01,r02]

CASES.json: {"cases": [{"name": "r01", "id": "승/승급", "syllable": "승", "word": "승급", "source": "급"}, ...]}
SOURCES/<source>/ is made by replay_prep.py: the certificate of 'source syllable received, nothing used'.
The position of a case is {"initial_syllable": syllable, "history": [word]}: the receiver has played `word`,
the other side is to move. The source must be the same vertex as the syllable the word hands over.

Two kinds of run per case:
  direct  solver_v5 from scratch                                   -> certificate -> verify_v4
  replay  solver_v5_replay --replay SOURCE (old strategy walked on the new position, stuck states searched with
          a node budget, then the normal search for whatever is left)   -> certificate -> verify_v4
Both write an ordinary route-proof-v4 certificate of the case's own position and both are accepted only by
solve_common.verify (exit code 0, verified, expected result, deflate-exact, four SHA-256). A run that ends
undecided, cannot write its certificate or is not accepted stays undecided; its time is recorded all the same.

Load. --jobs N runs N jobs at a time; a job is one run of one kind with its verification. The jobs of all cases
are queued in case order, direct then replay, so both kinds meet the same load (N busy processes).

Restarts (2026-11-12). Every run saves its own record as soon as it is finished - WORKDIR/<case>/direct.json and
replay.json - and a finished run is never repeated. A run in progress checkpoints its search state every 60 s
(<kind>.state.tt); after a restart the same command continues it with the budget that is left: the search time
inside the state file is read from the file (solve_common.state_carried_seconds). What an interrupted run
searched after its last checkpoint is unknown; the record then says spent_is_lower_bound. The state is deleted
only after the certificate was accepted. A run that was solved but has no accepted certificate is tried once
more at the next call (its state is still there). WORKDIR/<case>/result.json is put together from the two records.
Recorded per run, kept apart: reading the source, replay (with its local searches), remaining search,
certificate writing, verification, and the wall time of the solver process(es). The cost of preparing the
source is copied from SOURCES/<source>/prep.json so that a first use and a reuse can be told apart.
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

HERE = Path(__file__).resolve().parent
BASIC = HERE.parent
os.environ.setdefault('BIG_PROOF_NODES', str(10**12))     # no shared verification lock: --jobs bounds the load
sys.path.insert(0, str(BASIC.parent / 'guopsaem_root' / 'verifier_v3'))
sys.path.insert(0, str(BASIC.parent / 'guopsaem_root' / 'tools'))
from verify_v3 import ModelV3  # noqa: E402
import solve_common as sc  # noqa: E402

DICT = BASIC / 'words_817.txt'
REPLAY_SOLVER = os.environ.get('REPLAY_SOLVER', '/home/user/AI-/.work/measure/solver_v5_replay')
CHECKPOINT = float(os.environ.get('REPLAY_CHECKPOINT_SECONDS', '60'))   # tests use a short interval
KEEP = 2000000
LOCK = threading.Lock()


def say(msg):
    print(time.strftime('%H:%M:%S'), msg, flush=True)


def now():
    return time.strftime('%Y-%m-%d %H:%M:%S')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, obj):
    tmp = Path(str(path) + '.part')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    os.replace(tmp, path)


def run_kind(kind, base, d, limit, ttmb, words_of):
    """One kind of run for the case in directory d, resumable. Returns its record (also written to <kind>.json)."""
    out, proof, state, log = d / f'{kind}.json', d / f'{kind}.v4.gz', d / f'{kind}.state.tt', d / f'{kind}.runs.jsonl'
    attempts = 0
    if out.exists():
        rec = json.loads(out.read_text(encoding='utf-8'))
        if not rec.get('problem') or rec.get('attempts', 1) >= 2:
            return rec
        attempts = rec.get('attempts', 1)          # solved without an accepted certificate: once more, from the state

    def events():
        return [json.loads(x) for x in log.read_text(encoding='utf-8').splitlines() if x.strip()] if log.exists() else []

    def add(ev):
        with open(log, 'a') as f:
            f.write(json.dumps(ev, ensure_ascii=False) + '\n')

    ev = events()
    if ev and ev[-1]['event'] == 'start':
        add({'event': 'interrupted', 'time': now(), 'started': ev[-1]['time'], 'seconds_in_state': sc.state_carried_seconds(state),
             'note': f'cut off by a restart; the search after its last checkpoint (at most {CHECKPOINT:g} s) is lost and not counted'})
    for suffix in ('.tmp', '.body.tmp', '.tmp.body.tmp'):
        if Path(str(proof) + suffix).exists():
            Path(str(proof) + suffix).unlink()
    if Path(str(state) + '.tmp').exists():
        Path(str(state) + '.tmp').unlink()
    carried = (sc.state_carried_seconds(state) or 0.0) if state.exists() else 0.0
    remaining = round(limit - carried, 3)
    if state.exists() and remaining < 1 and not attempts:
        sol = {'result': 'unknown', 'reason': 'time_limit', 'seconds': 0.0, 'carried_seconds': carried, 'total_search_seconds': carried,
               'note': 'the whole budget is inside the saved state of interrupted runs'}
    else:
        need_gb = sc.state_file_bytes(ttmb, KEEP) / 2**30
        if sc.free_gb(d) - need_gb < sc.MIN_FREE_GB:
            raise sc.LowDisk(f'free disk {sc.free_gb(d):.2f} GB: {d.name} {kind} not started, nothing deleted')
        if proof.exists():
            proof.unlink()
        cmd = base + ['--seconds', str(max(remaining, 1.0)), '--tt-mb', str(ttmb), '--threads', '1', '--proof-format', 'v4', '--proof', str(proof),
                      '--tt-save', str(state), '--checkpoint-seconds', str(CHECKPOINT), '--tt-save-max', str(KEEP)]
        if state.exists():
            cmd += ['--tt-load', str(state)]
        add({'event': 'start', 'time': now(), 'cmd': cmd[1:]})
        t0 = time.time()
        r = subprocess.run(cmd, capture_output=True, text=True)
        sol = sc.parse_solver_output(r.stdout, r.returncode)
        with open(d / f'{kind}.log', 'a') as f:
            f.write(' '.join(cmd) + '\n' + r.stdout + r.stderr)
        aside = sc.set_aside_refused_state(state, r.stderr) if sol.get('result') == 'error' else None
        add({'event': 'end', 'time': now(), 'returncode': r.returncode, 'wall_seconds': round(time.time() - t0, 2), 'solver': sol,
             **({'state_set_aside': aside} if aside else {})})
    ev = events()
    ends = [e for e in ev if e['event'] == 'end']
    cut = [e for e in ev if e['event'] == 'interrupted']
    total = sol.get('total_search_seconds')
    rec = {'solver_result': sol.get('result'), 'reason': sol.get('reason'),
           'search_seconds': round(total, 3) if total is not None else sol.get('seconds'),
           'mid_calls': sum(e['solver'].get('mid_calls') or 0 for e in ends), 'proof_nodes': sol.get('proof_nodes'),
           'proof_seconds': sol.get('emit_seconds'), 'emit_resolves': sol.get('emit_resolves'), 'proof_error': sol.get('proof_error') or None,
           'solver_wall_seconds': round(sum(e.get('wall_seconds') or 0 for e in ends), 2), 'solver_runs': len(ends),
           'interrupted_runs': len(cut), 'spent_is_lower_bound': bool(cut), 'decided': False}
    if cut:
        rec['mid_calls_is_lower_bound'] = True
    if kind == 'replay':
        rec['replay'] = {k[7:]: v for k, v in sol.items() if k.startswith('replay_')}       # of the last solver run
        rec['search_after_replay_seconds'] = round((sol.get('seconds') or 0) - (sol.get('replay_seconds') or 0), 3)
    if sol.get('result') in ('win', 'loss') and not sol.get('proof_error') and proof.exists():
        want = 'W' if sol['result'] == 'win' else 'L'
        t1 = time.time()
        ok, v = sc.verify(DICT, 817, d / 'pos.json', proof, d / 'in.txt', want, sol.get('proof_nodes', 0))
        rec.update(verify_wall_seconds=round(time.time() - t1, 2), verify_seconds=v.get('elapsed_seconds'), decided=bool(ok),
                   proof_bytes=proof.stat().st_size, proof_sha256=v.get('proof_sha256'), acceptance=v.get('acceptance'),
                   verify_error=v.get('error'), verifier=v.get('verifier'))
        rec['state_released'] = sc.release_state(state, ok, proof)       # only after acceptance
        if ok:
            rec['first_move'] = 'lose' if sol['result'] == 'win' else 'win'
            if sol['result'] == 'win' and sol.get('best_group', -1) >= 0:
                rec['reply'] = sorted(words_of[sol['best_group']])
        else:
            rec['problem'] = 'solved, but the certificate was not accepted; the saved state is kept'
    elif sol.get('result') in ('win', 'loss'):
        rec['problem'] = f'solved, but no certificate ({sol.get("proof_error") or "file missing"}); the saved state is kept'
    elif sol.get('result') == 'error':
        rec['problem'] = 'solver error: ' + str(sol.get('tail', ''))[-200:]
    if rec.get('problem'):
        rec['attempts'] = attempts + 1
    rec['total_wall_seconds'] = round(rec['solver_wall_seconds'] + (rec.get('verify_wall_seconds') or 0), 2)
    write_json(out, rec)
    return rec


def line(r):
    if r is None:
        return '안 돌림'
    if not r['decided']:
        return f'미확정 ({r.get("problem") or r.get("reason") or r["solver_result"]}, {r["solver_wall_seconds"]:.0f}초)'
    return (f'첫 수 {"패" if r["first_move"] == "lose" else "승"} (검증 통과), 전체 {r["solver_wall_seconds"] + r["verify_seconds"]:.1f}초 '
            f'[탐색 {r["search_seconds"]:.1f} · 증명 {r["proof_seconds"]:.1f} · 검증 {r["verify_seconds"]:.1f}], '
            f'탐색 {r["mid_calls"]:,}국면, 증명 {r["proof_nodes"]:,}국면')


def main():
    cases_path, sources, work = sys.argv[1:4]
    rest = sys.argv[4:]
    opt = {'--seconds': 120.0, '--tt-mb': 1024, '--stuck-nodes': 200000, '--only': '', '--jobs': 1, '--kinds': 'direct,replay'}
    for i in range(0, len(rest), 2):
        opt[rest[i]] = type(opt[rest[i]])(rest[i + 1])
    kinds = [k for k in ('direct', 'replay') if k in opt['--kinds'].split(',')]
    sources, work = Path(sources), Path(work)
    work.mkdir(parents=True, exist_ok=True)
    cases = json.loads(Path(cases_path).read_text(encoding='utf-8'))['cases']
    if opt['--only']:
        only = set(opt['--only'].split(','))
        cases = [c for c in cases if c['name'] in only]
    model = ModelV3(DICT.read_bytes(), 817)
    words_of = {}
    for w in model.words:
        words_of.setdefault(model.word_group(w), []).append(w)
    head = {}
    for c in cases:
        d = work / c['name']
        d.mkdir(exist_ok=True)
        pos = {'initial_syllable': c['syllable'], 'history': [c['word']]}
        cur, counts, _ = model.position(pos)
        src = sources / c['source']
        prep = json.loads((src / 'prep.json').read_text(encoding='utf-8'))
        assert model.vertex_of(c['source']) == cur, f'{c["name"]}: the source is not the handed-over vertex'
        assert sha(src / 'proof.v4.gz') == prep['proof_sha256'], f'{c["name"]}: the source certificate changed'
        (d / 'pos.json').write_bytes(json.dumps(pos, ensure_ascii=False).encode('utf-8'))
        (d / 'in.txt').write_bytes(model.numeric_input(cur, counts))
        head[c['name']] = {
            'name': c['name'], 'id': c['id'], 'syllable': c['syllable'], 'word': c['word'], 'hands_over': model.names[cur],
            'seconds_limit': opt['--seconds'], 'tt_mb': opt['--tt-mb'], 'stuck_nodes': opt['--stuck-nodes'], 'jobs': opt['--jobs'],
            'input_sha256': sha(d / 'in.txt'), 'position_sha256': sha(d / 'pos.json'),
            'source': {'syllable': c['source'], 'proof_sha256': prep['proof_sha256'], 'proof_nodes': prep['proof_nodes'],
                       'prep_search_seconds_spent': prep['search_seconds_spent'], 'prep_proof_seconds': prep['proof_seconds'],
                       'prep_verify_seconds': prep['verify_seconds'], 'prep_solver_wall_seconds': prep['solver_wall_seconds'],
                       'prep_verify_wall_seconds': prep['verify_wall_seconds'], 'prep_spent_is_lower_bound': prep.get('spent_is_lower_bound')},
            'solver_sha256': sha(sc.SOLVER), 'replay_solver_sha256': sha(REPLAY_SOLVER), 'verifier_sha256': sha(sc.VERIFY_V4)}

    def assemble(c):
        d = work / c['name']
        parts = {k: json.loads((d / f'{k}.json').read_text(encoding='utf-8')) for k in ('direct', 'replay') if (d / f'{k}.json').exists()}
        if any(k not in parts for k in kinds):
            return
        old = json.loads((d / 'result.json').read_text(encoding='utf-8')) if (d / 'result.json').exists() else {}
        rec = {**head[c['name']], **{k: old[k] for k in ('direct', 'replay') if k in old}, **parts}
        a, b = rec.get('direct'), rec.get('replay')
        if a and b and a['decided'] and b['decided']:
            assert a['first_move'] == b['first_move'], f'{c["name"]}: two accepted certificates with different verdicts'
        write_json(d / 'result.json', rec)
        say(f'{c["name"]} {c["id"]} (넘겨준 음절 {c["source"]})')
        say('   직접: ' + line(a))
        say('   재생: ' + line(b) + (f', 재생 {b["replay"].get("nodes", 0):,}국면, 막힌 곳 탐색 {b["replay"].get("local_calls", 0):,}번'
                                    if b and b.get('replay') else ''))

    def job(c, kind):
        d = work / c['name']
        old = json.loads((d / 'result.json').read_text(encoding='utf-8')) if (d / 'result.json').exists() else {}
        if kind in old and not (d / f'{kind}.json').exists():
            return                                     # done by an earlier version of this tool
        base = [sc.SOLVER, str(d / 'in.txt')] if kind == 'direct' else \
            [REPLAY_SOLVER, str(d / 'in.txt'), '--replay', str(sources / c['source'] / 'proof.v4.gz'), '--replay-stuck-nodes', str(opt['--stuck-nodes'])]
        try:
            run_kind(kind, base, d, opt['--seconds'], opt['--tt-mb'], words_of)
        except sc.LowDisk as e:
            say(f'{c["name"]} {kind}: 시작하지 않음 (디스크 부족, 저장 상태는 그대로 둠): {e}')
            return
        with LOCK:
            assemble(c)

    with ThreadPoolExecutor(opt['--jobs']) as ex:
        list(ex.map(lambda ck: job(*ck), [(c, k) for c in cases for k in kinds]))


if __name__ == '__main__':
    main()
