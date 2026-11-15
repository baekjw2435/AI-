#!/usr/bin/env python3
"""Source certificate of 'T received, no word used' from an existing route-map table (solver_v5_table --table-guide).

usage: run_guide.py T WORKDIR GUIDE_DIR [--seconds 600] [--tt-mb 1024] [--stuck-nodes 200000] [--root W|L]
  WORKDIR/T/ gets pos.json, in.txt, proof.v4.gz, state.tt (checkpoints of this run only), run.json.
  GUIDE_DIR is make_guide.py's output for the book of T.

--seconds is the whole search budget of the run: the guided walk, the local searches of stuck states and the normal
search after it. Certificate writing and verification have no extra limit, as for every other source here.
The certificate decides only if the unchanged verify_v4 accepts it with every acceptance condition of
solve_common.verify. The saved search state of the ordinary source run (sources/T/state.tt) is not read or touched.
"""
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
SOLVER = os.environ.get('TABLE_SOLVER', '/home/user/AI-/.work/measure/solver_v5_table')


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
    t, work, guide = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    rest = sys.argv[4:]
    o = {'--seconds': '600', '--tt-mb': '1024', '--stuck-nodes': '200000', '--root': 'W'}
    o.update({rest[i]: rest[i + 1] for i in range(0, len(rest), 2)})
    d = work / t
    d.mkdir(parents=True, exist_ok=True)
    m = ModelV3(DICT.read_bytes(), 817)
    pos = {'initial_syllable': t, 'history': []}
    (d / 'pos.json').write_bytes(json.dumps(pos, ensure_ascii=False).encode('utf-8'))
    c, k, _ = m.position(pos)
    (d / 'in.txt').write_bytes(m.numeric_input(c, k))
    proof = d / 'proof.v4.gz'
    if proof.exists():
        proof.unlink()
    cmd = [SOLVER, str(d / 'in.txt'), '--seconds', o['--seconds'], '--tt-mb', o['--tt-mb'], '--threads', '1',
           '--proof-format', 'v4', '--proof', str(proof), '--emit-check', '0',
           '--table-guide', str(guide), '--table-root', o['--root'], '--replay-stuck-nodes', o['--stuck-nodes'],
           '--tt-save', str(d / 'state.tt'), '--checkpoint-seconds', '60', '--tt-save-max', '2000000']
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True)
    wall = time.time() - t0
    sol = sc.parse_solver_output(r.stdout, r.returncode)
    rec = {'syllable': t, 'position': pos, 'started': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(t0)), 'cmd': cmd[1:],
           'solver_wall_seconds': round(wall, 2), 'solver': sol, 'solver_sha256': sha(SOLVER),
           'guide': json.loads((guide / 'guide.json').read_text(encoding='utf-8'))}
    if proof.exists():
        want = root_result(proof)
        t1 = time.time()
        ok, v = sc.verify(DICT, 817, d / 'pos.json', proof, d / 'in.txt', want, sol.get('proof_nodes') or 0)
        rec.update(result_for_receiver=want, verify_wall_seconds=round(time.time() - t1, 2), accepted=ok,
                   verify={x: v.get(x) for x in ('verified', 'result_for_player_to_move', 'states', 'proof_sha256', 'input_sha256',
                                                 'position_sha256', 'dictionary_sha256', 'state_storage', 'verifier', 'exit_code',
                                                 'elapsed_seconds', 'error')},
                   acceptance=v.get('acceptance'), proof_bytes=proof.stat().st_size)
    else:
        rec.update(accepted=False, note='no certificate: the root was not solved within --seconds')
    (d / 'run.json').write_text(json.dumps(rec, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(json.dumps({x: rec.get(x) for x in ('syllable', 'accepted', 'result_for_receiver', 'solver_wall_seconds', 'verify_wall_seconds')}
                     | {'search_seconds': sol.get('seconds'), 'proof_seconds': sol.get('emit_seconds'), 'proof_nodes': sol.get('proof_nodes'),
                        'replay_seconds': sol.get('replay_seconds'), 'local_calls': sol.get('replay_local_calls')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
