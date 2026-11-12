#!/usr/bin/env python3
"""Strategy replay against direct search, same machine, same limits, everything timed (2026-11-12).

usage: replay_test.py CASES.json SOURCES WORKDIR [--seconds 120] [--tt-mb 1024] [--stuck-nodes 200000]
                      [--only r01,r02] [--direct 1] [--add-direct 0]

CASES.json: {"cases": [{"name": "r01", "id": "승/승급", "syllable": "승", "word": "승급", "source": "급"}, ...]}
SOURCES/<source>/ is made by replay_prep.py: the certificate of 'source syllable received, nothing used'.
The position of a case is {"initial_syllable": syllable, "history": [word]}: the receiver has played `word`,
the other side is to move. The source must be the same vertex as the syllable the word hands over.

For each case, one after the other (one core each):
  direct  solver_v5 from scratch                                   -> certificate -> verify_v4
  replay  solver_v5_replay --replay SOURCE (old strategy walked on the new position, stuck states searched with
          a node budget, then the normal search for whatever is left)   -> certificate -> verify_v4
Both write an ordinary route-proof-v4 certificate of the case's own position and both are accepted only by
solve_common.verify (exit code 0, verified, expected result, deflate-exact, four SHA-256). A run that ends
undecided, cannot write its certificate or is not accepted stays undecided; its time is recorded all the same.
Recorded per run, kept apart: reading the source, replay (with its local searches), remaining search,
certificate writing, verification, and the wall time of the whole solver process. The cost of preparing the
source is copied from SOURCES/<source>/prep.json so that a first use and a reuse can be told apart.
Result: WORKDIR/<name>/result.json. Re-running skips what is done. --direct 0 leaves the direct run out;
--add-direct 1 adds it later to a case that has only its replay run (same limits as recorded in the case).
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
BASIC = HERE.parent
sys.path.insert(0, str(BASIC.parent / 'guopsaem_root' / 'verifier_v3'))
sys.path.insert(0, str(BASIC.parent / 'guopsaem_root' / 'tools'))
from verify_v3 import ModelV3  # noqa: E402
import solve_common as sc  # noqa: E402

DICT = BASIC / 'words_817.txt'
REPLAY_SOLVER = os.environ.get('REPLAY_SOLVER', '/home/user/AI-/.work/measure/solver_v5_replay')


def say(msg):
    print(time.strftime('%H:%M:%S'), msg, flush=True)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(kind, cmd, d, words_of, verify_args):
    """One solver process and, if it produced a certificate, one verification. Returns the record."""
    proof = Path(cmd[cmd.index('--proof') + 1])
    if proof.exists():
        proof.unlink()
    t0 = time.time()
    out = subprocess.run(cmd, capture_output=True, text=True)
    wall = time.time() - t0
    (d / f'{kind}.log').write_text(' '.join(cmd) + '\n' + out.stdout + out.stderr)
    sol = sc.parse_solver_output(out.stdout, out.returncode)
    rec = {'solver_result': sol.get('result'), 'reason': sol.get('reason'), 'search_seconds': sol.get('seconds'),
           'mid_calls': sol.get('mid_calls'), 'proof_nodes': sol.get('proof_nodes'), 'proof_seconds': sol.get('emit_seconds'),
           'emit_resolves': sol.get('emit_resolves'), 'proof_error': sol.get('proof_error') or None,
           'solver_wall_seconds': round(wall, 2), 'decided': False}
    if kind == 'replay':
        rec['replay'] = {k[7:]: v for k, v in sol.items() if k.startswith('replay_')}
        rs = sol.get('replay_seconds') or 0
        rec['search_after_replay_seconds'] = round((sol.get('seconds') or 0) - rs, 3)
    if sol.get('result') in ('win', 'loss') and not sol.get('proof_error') and proof.exists():
        want = 'W' if sol['result'] == 'win' else 'L'
        t1 = time.time()
        ok, v = sc.verify(DICT, 817, *verify_args, want, sol.get('proof_nodes', 0))
        rec.update(verify_wall_seconds=round(time.time() - t1, 2), verify_seconds=v.get('elapsed_seconds'), decided=bool(ok),
                   proof_bytes=proof.stat().st_size, proof_sha256=v.get('proof_sha256'), acceptance=v.get('acceptance'),
                   verify_error=v.get('error'), verifier=v.get('verifier'))
        if ok:
            rec['first_move'] = 'lose' if sol['result'] == 'win' else 'win'
            if sol['result'] == 'win' and sol.get('best_group', -1) >= 0:
                rec['reply'] = sorted(words_of[sol['best_group']])
    elif proof.exists():
        proof.unlink()
    rec['total_wall_seconds'] = round(rec['solver_wall_seconds'] + (rec.get('verify_wall_seconds') or 0), 2)
    return rec


def main():
    cases_path, sources, work = sys.argv[1:4]
    rest = sys.argv[4:]
    opt = {'--seconds': 120.0, '--tt-mb': 1024, '--stuck-nodes': 200000, '--only': '', '--direct': 1, '--add-direct': 0}
    for i in range(0, len(rest), 2):
        opt[rest[i]] = type(opt[rest[i]])(rest[i + 1])
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
    for c in cases:
        d = work / c['name']
        d.mkdir(exist_ok=True)
        out = d / 'result.json'
        if out.exists():
            rec = json.loads(out.read_text(encoding='utf-8'))
            if opt['--add-direct'] and 'direct' not in rec:
                rec['direct'] = run('direct', [sc.SOLVER, str(d / 'in.txt'), '--seconds', str(rec['seconds_limit']), '--tt-mb',
                                               str(rec['tt_mb']), '--threads', '1', '--proof-format', 'v4', '--proof',
                                               str(d / 'direct.v4.gz')], d, words_of, (d / 'pos.json', d / 'direct.v4.gz', d / 'in.txt'))
                a, b = rec['direct'], rec['replay']
                if a['decided'] and b['decided']:
                    assert a['first_move'] == b['first_move'], f'{c["name"]}: two accepted certificates with different verdicts'
                out.write_text(json.dumps(rec, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
                say(f'{c["name"]} {c["id"]} 직접 탐색 추가: ' + ('확정 ' + a['first_move'] if a['decided'] else '미확정')
                    + f' ({a["solver_wall_seconds"]:.0f}초)')
            continue
        pos = {'initial_syllable': c['syllable'], 'history': [c['word']]}
        cur, counts, _ = model.position(pos)
        src = sources / c['source']
        prep = json.loads((src / 'prep.json').read_text(encoding='utf-8'))
        assert model.vertex_of(c['source']) == cur, f'{c["name"]}: the source is not the handed-over vertex'
        (d / 'pos.json').write_bytes(json.dumps(pos, ensure_ascii=False).encode('utf-8'))
        (d / 'in.txt').write_bytes(model.numeric_input(cur, counts))
        rec = {'name': c['name'], 'id': c['id'], 'syllable': c['syllable'], 'word': c['word'], 'hands_over': model.names[cur],
               'seconds_limit': opt['--seconds'], 'tt_mb': opt['--tt-mb'], 'stuck_nodes': opt['--stuck-nodes'],
               'input_sha256': sha(d / 'in.txt'), 'position_sha256': sha(d / 'pos.json'),
               'source': {'syllable': c['source'], 'proof_sha256': prep['proof_sha256'], 'proof_nodes': prep['proof_nodes'],
                          'prep_search_seconds_spent': prep['search_seconds_spent'], 'prep_proof_seconds': prep['proof_seconds'],
                          'prep_verify_seconds': prep['verify_seconds'], 'prep_solver_wall_seconds': prep['solver_wall_seconds'],
                          'prep_verify_wall_seconds': prep['verify_wall_seconds']},
               'solver_sha256': sha(sc.SOLVER), 'replay_solver_sha256': sha(REPLAY_SOLVER), 'verifier_sha256': sha(sc.VERIFY_V4)}
        assert sha(src / 'proof.v4.gz') == prep['proof_sha256'], f'{c["name"]}: the source certificate changed'
        common = ['--seconds', str(opt['--seconds']), '--tt-mb', str(opt['--tt-mb']), '--threads', '1', '--proof-format', 'v4']
        if opt['--direct']:
            rec['direct'] = run('direct', [sc.SOLVER, str(d / 'in.txt')] + common + ['--proof', str(d / 'direct.v4.gz')], d, words_of,
                                (d / 'pos.json', d / 'direct.v4.gz', d / 'in.txt'))
        rec['replay'] = run('replay', [REPLAY_SOLVER, str(d / 'in.txt')] + common +
                            ['--proof', str(d / 'replay.v4.gz'), '--replay', str(src / 'proof.v4.gz'),
                             '--replay-stuck-nodes', str(opt['--stuck-nodes'])], d, words_of,
                            (d / 'pos.json', d / 'replay.v4.gz', d / 'in.txt'))
        a, b = rec.get('direct'), rec['replay']
        if a and a['decided'] and b['decided']:
            assert a['first_move'] == b['first_move'], f'{c["name"]}: two accepted certificates with different verdicts'
        out.write_text(json.dumps(rec, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')

        def line(r):
            if r is None:
                return '안 돌림'
            if not r['decided']:
                return f'미확정 ({r.get("reason") or r["solver_result"]}, {r["solver_wall_seconds"]:.0f}초)'
            return (f'첫 수 {"패" if r["first_move"] == "lose" else "승"} (검증 통과), 전체 {r["total_wall_seconds"]:.1f}초 '
                    f'[탐색 {r["search_seconds"]:.1f} · 증명 {r["proof_seconds"]:.1f} · 검증 {r["verify_wall_seconds"]:.1f}], '
                    f'탐색 {r["mid_calls"]:,}국면, 증명 {r["proof_nodes"]:,}국면')
        say(f'{c["name"]} {c["id"]} (넘겨준 음절 {c["source"]})')
        say('   직접: ' + line(a))
        say('   재생: ' + line(b) + (f', 재생 {b["replay"]["nodes"]:,}국면, 막힌 곳 탐색 {b["replay"]["local_calls"]:,}번' if b.get('replay') else ''))


if __name__ == '__main__':
    main()
