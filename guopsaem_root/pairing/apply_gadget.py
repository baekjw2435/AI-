#!/usr/bin/env python3
"""Small feasibility check of 3-ply answers (gadget.py) on existing samples (2026-11-07).

usage: apply_gadget.py DICT WORD_COUNT SOLVER OUT.jsonl SAMPLE.log ... [--per-file N] [--nodes K] [--seconds T]

From each sample file, positions that the production solver does NOT solve within K nodes (as a root) are
chosen: the N smallest (fewest live groups) and N more spread over the file. For each chosen position:
  * node: a 3-ply strategy proving the player to move loses?
  * children: for every move, a 3-ply strategy proving the child lost for its player to move?
Every strategy found must pass gadget.check and is compared with the solver's result for that position.
Finding nothing decides nothing.
"""
import json
from multiprocessing import Pool
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[0] / 'verifier_v3'))
from verify_v3 import ModelV3  # noqa: E402
import apply_pairing  # noqa: E402
import gadget  # noqa: E402

MODEL = None


def init(dict_path, nwords):
    global MODEL
    MODEL = ModelV3(Path(dict_path).read_bytes(), int(nwords))


def counts_of(s):
    c = bytearray(len(MODEL.edges))
    for g, k in s['groups']:
        c[g] = k
    return bytes(c)


def solver_result(solver, s, nodes):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / 'in.txt'
        p.write_bytes(MODEL.numeric_input(s['cur'], counts_of(s)))
        r = subprocess.run([solver, str(p), '--nodes', str(nodes), '--seconds', '600', '--tt-mb', '256', '--threads', '1'],
                           capture_output=True, text=True)
        return json.loads(r.stdout.strip().splitlines()[-1])


def found_summary(m, g):
    return {'S': sorted(m.names[v] for v in g['S']), 'M': sorted(m.names[v] for v in g['M']),
            'twoway': len(g['twoway']), 'oneway': len(g['oneway']), 'entries': len(g['entries']),
            'middle_used': g['middle_used']}


def one(args):
    s, solver, nodes, seconds = args
    m = MODEL
    counts = counts_of(s)
    sol = solver_result(solver, s, nodes)
    rec = {k: s[k] for k in ('entry', 'cur', 'res', 'depth')}
    rec['live_groups'] = len(s['groups'])
    rec['solver_quick'] = {'result': sol['result'], 'mid_calls': sol['mid_calls']}
    g = gadget.find(m, s['cur'], counts, seconds=seconds)
    rec['node'] = {'status': g['status'], 'seconds': g['seconds']}
    if g['status'] == 'found':
        gadget.check(m, s['cur'], counts, g['S'], g['M'], g['twoway'], g['oneway'], g['entries'], g['replies'])
        rec['node'].update(found_summary(m, g), checked=True)
    kids = []
    for grp in m.available[s['cur']]:
        if not counts[grp]:
            continue
        t, ch, st = m.child(s['cur'], counts, grp)
        k = {'group': grp, 'static': st}
        if st == -1:
            gk = gadget.find(m, t, ch, seconds=seconds)
            k.update(status=gk['status'], seconds=gk['seconds'])
            if gk['status'] == 'found':
                gadget.check(m, t, ch, gk['S'], gk['M'], gk['twoway'], gk['oneway'], gk['entries'], gk['replies'])
                k.update(found_summary(m, gk), checked=True)
        kids.append(k)
    rec['children'] = kids
    return rec


def main():
    args = sys.argv[1:]
    opt = {'--per-file': 5, '--nodes': 100000, '--seconds': 30.0}
    files = []
    i = 4
    dict_path, nwords, solver, out = args[:4]
    while i < len(args):
        if args[i] in opt:
            opt[args[i]] = type(opt[args[i]])(args[i + 1]); i += 2
        else:
            files.append(args[i]); i += 1
    init(dict_path, nwords)
    chosen = []
    for f in files:
        ss = apply_pairing.read_samples(f)
        unsolved = []
        for s in sorted(ss, key=lambda s: len(s['groups'])):
            r = solver_result(solver, s, opt['--nodes'])
            if r['result'] == 'unknown':
                unsolved.append(s)
            if len(unsolved) >= opt['--per-file']:
                break
        rest = [s for s in ss if s not in unsolved]
        step = max(1, len(rest) // opt['--per-file'])
        spread = []
        for s in rest[::step]:
            if len(spread) >= opt['--per-file']:
                break
            if solver_result(solver, s, opt['--nodes'])['result'] == 'unknown':
                spread.append(s)
        chosen += [dict(s, source=Path(f).name) for s in unsolved + spread]
    print(f'{len(chosen)} positions chosen', flush=True)
    with Pool(3, initializer=init, initargs=(dict_path, nwords)) as p, open(out, 'w', encoding='utf-8') as fo:
        for rec, s in zip(p.imap(one, [(s, solver, opt['--nodes'], opt['--seconds']) for s in chosen]), chosen):
            rec['source'] = s['source']
            fo.write(json.dumps(rec, ensure_ascii=False) + '\n')
            fo.flush()


if __name__ == '__main__':
    main()
