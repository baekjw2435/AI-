#!/usr/bin/env python3
"""Follow-up branches: prove positions with any history (e.g. 식생활 → 활극 → 극락) and verify each certificate.

usage: branch_run.py CASES.json WORK [--seconds 600] [--jobs 3] [--tt-mb 1024] [--stuck-nodes 200000] [--only b01,b02]
  CASES.json: {"cases": [{"name", "position": {"initial_syllable", "history": [...]}, "method": "replay"|"direct"|"table",
               "source": vertex name (replay: sources/<v>/proof.v4.gz), "guide": dir (table), "expect": "W"|"L" (table)}]}
  WORK/<name>/ gets pos.json, in.txt, proof.v4.gz, run.json.

The position is the case's own history, every word in it used; nothing is taken from another history.
--seconds is the whole search budget of a case (guided walk, local searches of stuck states, normal search).
Certificate writing and verification have no extra limit, as everywhere in this study. A case counts only if the
unchanged verify_v4 accepts its certificate with every acceptance condition of solve_common.verify; otherwise it
stays unknown. No saved state is written or read (each case starts fresh).
"""
from concurrent.futures import ThreadPoolExecutor
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
BASIC = HERE.parents[1]
sys.path.insert(0, str(BASIC.parent / 'guopsaem_root' / 'verifier_v3'))
sys.path.insert(0, str(BASIC.parent / 'guopsaem_root' / 'tools'))
from verify_v3 import ModelV3  # noqa: E402
import solve_common as sc  # noqa: E402

DICT = BASIC / 'words_817.txt'
SOURCES = Path(os.environ.get('SOURCES', '/home/user/AI-/.work/sources'))
REPLAY = os.environ.get('REPLAY_SOLVER', '/home/user/AI-/.work/measure/solver_v5_replay')
TABLE = os.environ.get('TABLE_SOLVER', '/home/user/AI-/.work/measure/solver_v5_table')


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def root_result(proof):
    with gzip.open(proof, 'rt', encoding='utf-8') as f:
        head = json.loads(f.readline())
        last = None
        for line in f:
            if line.strip():
                last = line
    node = json.loads(last)
    assert node['id'] == head['root']
    return node['r']


def main():
    cases_path, work = Path(sys.argv[1]), Path(sys.argv[2])
    rest = sys.argv[3:]
    o = {'--seconds': '600', '--jobs': '3', '--tt-mb': '1024', '--stuck-nodes': '200000', '--only': ''}
    o.update({rest[i]: rest[i + 1] for i in range(0, len(rest), 2)})
    cases = json.loads(cases_path.read_text(encoding='utf-8'))['cases']
    if o['--only']:
        cases = [c for c in cases if c['name'] in o['--only'].split(',')]
    m = ModelV3(DICT.read_bytes(), 817)

    def one(c):
        d = work / c['name']
        d.mkdir(parents=True, exist_ok=True)
        (d / 'pos.json').write_bytes(json.dumps(c['position'], ensure_ascii=False).encode('utf-8'))
        cur, k, _ = m.position(c['position'])
        (d / 'in.txt').write_bytes(m.numeric_input(cur, k))
        proof = d / 'proof.v4.gz'
        if proof.exists():
            proof.unlink()
        common = ['--seconds', o['--seconds'], '--tt-mb', o['--tt-mb'], '--threads', '1', '--proof-format', 'v4',
                  '--proof', str(proof), '--emit-check', '0']
        if c['method'] == 'replay':
            src = SOURCES / c['source'] / 'proof.v4.gz'
            cmd = [REPLAY, str(d / 'in.txt'), '--replay', str(src), '--replay-stuck-nodes', o['--stuck-nodes']] + common
            extra = {'source_proof_sha256': sha(src), 'solver_sha256': sha(REPLAY)}
        elif c['method'] == 'table':
            cmd = [TABLE, str(d / 'in.txt'), '--table-guide', c['guide'], '--table-root', c.get('expect', 'W'),
                   '--replay-stuck-nodes', o['--stuck-nodes']] + common
            extra = {'solver_sha256': sha(TABLE)}
        else:
            cmd = [sc.SOLVER, str(d / 'in.txt')] + common[:-2]
            extra = {'solver_sha256': sha(sc.SOLVER)}
        t0 = time.time()
        r = subprocess.run(cmd, capture_output=True, text=True)
        wall = time.time() - t0
        sol = sc.parse_solver_output(r.stdout, r.returncode)
        rec = {'name': c['name'], 'position': c['position'], 'method': c['method'], 'source': c.get('source'),
               'started': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(t0)), 'cmd': cmd[1:], 'solver_wall_seconds': round(wall, 2),
               'solver': sol, **extra}
        if proof.exists():
            want = root_result(proof)
            t1 = time.time()
            ok, v = sc.verify(DICT, 817, d / 'pos.json', proof, d / 'in.txt', want, sol.get('proof_nodes') or 0)
            rec.update(result_for_mover=want, verify_wall_seconds=round(time.time() - t1, 2), accepted=ok,
                       verify={x: v.get(x) for x in ('verified', 'result_for_player_to_move', 'proof_sha256', 'input_sha256',
                                                     'position_sha256', 'dictionary_sha256', 'state_storage', 'verifier',
                                                     'exit_code', 'elapsed_seconds', 'error')},
                       acceptance=v.get('acceptance'), proof_bytes=proof.stat().st_size)
        else:
            rec.update(accepted=False, note='no certificate: not solved within --seconds')
        (d / 'run.json').write_text(json.dumps(rec, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
        line = {'name': c['name'], 'word': c['word'], 'accepted': rec['accepted'], 'mover': rec.get('result_for_mover'),
                'search': sol.get('seconds'), 'proof_s': sol.get('emit_seconds'), 'verify_s': rec.get('verify_wall_seconds'),
                'proof_nodes': sol.get('proof_nodes')}
        print(time.strftime('%H:%M:%S'), json.dumps(line, ensure_ascii=False), flush=True)
        return line

    with ThreadPoolExecutor(int(o['--jobs'])) as ex:
        list(ex.map(one, cases))


if __name__ == '__main__':
    main()
