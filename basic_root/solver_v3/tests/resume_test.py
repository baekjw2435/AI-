#!/usr/bin/env python3
"""TT save/load (resume) test for solver_v3 on real positions.

usage: resume_test.py SOLVER POSDIR NAME [NAME ...]

For each POSDIR/NAME.txt (+ NAME.json history file):
  fresh   one uninterrupted run with a proof
  staged  short run that saves the TT -> load, run, save again -> load and finish with a proof
          (stage 1 uses 2 threads, the others 1, so a table may move between thread counts)
Both results must agree and both certificates must pass the UNMODIFIED verify_v2.py.
Then, on the first position: refusal cases (other root, other graph, other options, damaged
files), periodic checkpoints, and a run killed with SIGKILL and resumed from its checkpoint.
"""
import json, os, signal, subprocess, sys, tempfile, time
from pathlib import Path

sys.dont_write_bytecode = True
VDIR = os.environ.get('ROUTE_VERIFIER_DIR', '/home/user/AI-/.work/verifier/route-verifier-v2')
DICT = os.environ.get('ROUTE_DICTIONARY', '/home/user/AI-/.work/basic_root.txt')
sys.path.insert(0, VDIR)
from verify_v2 import verify_v2  # noqa: E402

fails = 0


def check(cond, what):
    global fails
    print(('ok    ' if cond else 'FAIL  ') + what, flush=True)
    fails += not cond


def run(solver, inp, *args):
    r = subprocess.run([solver, str(inp), '--tt-mb', '256', *map(str, args)], capture_output=True, text=True)
    out = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else None
    return r.returncode, out, r.stderr.strip()


def verified(pos_json, proof, result):
    v = verify_v2(DICT, pos_json, proof)
    return v['verified'] and v['result_for_player_to_move'] == ('W' if result == 'win' else 'L'), v['checked_certificate_states']


def main():
    solver, posdir, names = sys.argv[1], Path(sys.argv[2]), sys.argv[3:]
    with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as td:
        td = Path(td)
        for n in names:
            inp, pj = posdir / f'{n}.txt', posdir / f'{n}.json'
            t = time.time()
            rc, fresh, _ = run(solver, inp, '--seconds', 600, '--proof', td / 'fresh.jsonl')
            fresh_s = time.time() - t
            ok, nodes = verified(pj, td / 'fresh.jsonl', fresh['result'])
            check(rc == 0 and fresh['result'] != 'unknown' and ok, f'{n}: fresh {fresh["result"]} in {fresh_s:.1f}s, proof {nodes} verified')
            f = td / 'tt.bin'
            s1 = max(1.0, fresh_s * 0.15)
            rc, o1, _ = run(solver, inp, '--seconds', s1, '--threads', 2, '--tt-save', f)
            if o1['result'] != 'unknown':
                print(f'skip  {n}: solved inside stage 1 ({s1:.1f}s)'); continue
            check(rc == 0 and o1['tt_saves'] == 1 and o1['tt_saved'] > 0 and f.exists(), f'{n}: stage 1 saved {o1["tt_saved"]} entries in {o1["tt_save_seconds"]}s')
            rc, o2, _ = run(solver, inp, '--seconds', s1, '--tt-load', f, '--tt-save', f)
            check(rc == 0 and o2['tt_loaded'] == o1['tt_saved'], f'{n}: stage 2 loaded {o2["tt_loaded"]} in {o2["tt_load_seconds"]}s, result {o2["result"]}')
            if o2['result'] == 'unknown':
                rc, o3, _ = run(solver, inp, '--seconds', 600, '--tt-load', f, '--proof', td / 'staged.jsonl')
                check(rc == 0 and o3['tt_loaded'] == o2['tt_saved'], f'{n}: stage 3 loaded {o3["tt_loaded"]}')
            else:
                rc, o3, _ = run(solver, inp, '--seconds', 600, '--tt-load', f, '--proof', td / 'staged.jsonl')
            ok, nodes = verified(pj, td / 'staged.jsonl', o3['result'])
            check(o3['result'] == fresh['result'] and ok,
                  f'{n}: staged {o3["result"]} (search {o1["seconds"]:.1f}+{o2["seconds"]:.1f}+{o3["seconds"]:.1f}s vs fresh {fresh["seconds"]:.1f}s), proof {nodes} verified')

        # ---- refusal cases, on the first position
        a, b = names[0], names[1]
        inp, f = posdir / f'{a}.txt', td / 'ref.bin'
        rc, o, _ = run(solver, inp, '--seconds', 1, '--tt-save', f)
        good = f.read_bytes()

        def refused(label, *args, inp2=inp, want='TT file refused'):
            rc, o, err = run(solver, inp2, '--seconds', 1, '--tt-load', f, *args)
            check(rc == 2 and o is None and want in err, f'refuse {label}: rc={rc} "{err[:90]}"')
        refused('other root position', inp2=posdir / f'{b}.txt')
        lines = inp.read_text().splitlines()
        nv, ng, cur = map(int, lines[0].split())
        have = {tuple(map(int, ln.split()[:2])) for ln in lines[1:]}
        s0, t0 = next((s, t) for s in range(nv) for t in range(nv) if (s, t) not in have)
        g2 = td / 'graph2.txt'
        g2.write_text('\n'.join([f'{nv} {ng + 1} {cur}'] + lines[1:] + [f'{s0} {t0} 0']) + '\n')
        refused('other game graph (one more group)', inp2=g2)
        refused('other --init', '--init', 0)
        refused('other --wpn', '--wpn', 1)
        f.write_bytes(good[:-100]); refused('truncated file')
        bad = bytearray(good); bad[len(good) // 2] ^= 1; f.write_bytes(bytes(bad)); refused('one flipped bit')
        f.write_bytes(good + b'x'); refused('trailing data')
        f.write_bytes(good[:200]); refused('header only')
        f.unlink(); refused('missing file', want='cannot open TT file')
        f.write_bytes(good)
        rc, o, _ = run(solver, inp, '--seconds', 1, '--tt-load', f, '--threads', 2)
        check(rc == 0 and o['tt_loaded'] > 0, f'intact file loads again ({o["tt_loaded"]} entries)')

        # ---- periodic checkpoints and a killed run
        name = names[0]
        inp, pj, ck = posdir / f'{name}.txt', posdir / f'{name}.json', td / 'ck.bin'
        rc, o, _ = run(solver, inp, '--seconds', 7, '--checkpoint-seconds', 2, '--tt-save', ck)
        check(rc == 0 and (o['result'] != 'unknown' or o['tt_saves'] >= 3), f'checkpoints: {o["tt_saves"]} saves in {o["seconds"]:.1f}s ({o["result"]})')
        ck.unlink(missing_ok=True)
        p = subprocess.Popen([solver, str(inp), '--tt-mb', '256', '--seconds', '600', '--checkpoint-seconds', '1', '--tt-save', str(ck)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(3.5); p.send_signal(signal.SIGKILL); p.wait()
        check(ck.exists(), 'killed run left its last complete checkpoint')
        rc, o, _ = run(solver, inp, '--seconds', 600, '--tt-load', ck, '--proof', td / 'after_kill.jsonl')
        ok, nodes = verified(pj, td / 'after_kill.jsonl', o['result'])
        check(rc == 0 and o['tt_loaded'] > 0 and ok, f'resumed after kill: {o["result"]}, loaded {o["tt_loaded"]}, proof {nodes} verified')
    print(json.dumps({"fails": fails}))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
