#!/usr/bin/env python3
"""Feasibility probe (reviewer's experiment, NOT a verdict tool): replay the proof of syllable t on the
position 's received, first word w played' (w ends in t), and count where the old strategy gets stuck.
Stuck states are handed to solver_v5 (separate short runs, no shared table) just to measure their cost.

usage: replay_probe.py REV BIN WORK SYLLABLE WORD [OLD_SECONDS] [STUCK_SECONDS]
"""
import gzip, json, subprocess, sys, time
from collections import Counter
from pathlib import Path

REV, BIN, WORK = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
S, W = sys.argv[4], sys.argv[5]
OLD_SECONDS = float(sys.argv[6]) if len(sys.argv) > 6 else 120
STUCK_SECONDS = float(sys.argv[7]) if len(sys.argv) > 7 else 20
sys.path.insert(0, str(REV / 'guopsaem_root' / 'verifier_v3'))
from verify_v3 import ModelV3

sys.setrecursionlimit(200000)
DICT = REV / 'basic_root' / 'words_817.txt'
m = ModelV3(DICT.read_bytes(), 817)
T = W[-1]
d = WORK / f'{S}_{W}'
d.mkdir(parents=True, exist_ok=True)


def run_solver(inp_bytes, name, seconds, ttmb, proof=None):
    p = d / f'{name}.in.txt'
    p.write_bytes(inp_bytes)
    cmd = [str(BIN / 'solver_v5'), str(p), '--seconds', str(seconds), '--tt-mb', str(ttmb), '--threads', '1']
    if proof:
        cmd += ['--proof', str(proof), '--proof-format', 'v4']
    r = subprocess.run(cmd, capture_output=True, text=True)
    return json.loads(r.stdout.strip().splitlines()[-1])


# 1) the proof of t (first presentation, nothing used)
old_pos = {'initial_syllable': T, 'history': []}
ov, ocounts, _ = m.position(old_pos)
old_proof = d / 'old.v4.gz'
t0 = time.time()
old_sol = run_solver(m.numeric_input(ov, ocounts), 'old', OLD_SECONDS, 1024, old_proof)
if old_sol['result'] not in ('win', 'loss') or old_sol.get('proof_error'):
    print(json.dumps({'case': f'{S}/{W}', 'error': 'old root not solved', 'old': old_sol}, ensure_ascii=False))
    sys.exit(0)
old_w, old_m = [], []
with gzip.open(old_proof, 'rb') as f:
    f.readline()
    for line in f:
        n = json.loads(line)
        old_w.append(n['r'] == 'W')
        old_m.append(n['m'])
old_root = len(old_w) - 1

# 2) the new position: s received, w played
new_pos = {'initial_syllable': S, 'history': [W]}
nv, ncounts_raw, _ = m.position(new_pos)
ncounts, nstatic = m.normalize(nv, ncounts_raw)
assert nv == ov

memo = {}
stats = Counter()
stuck_log = []


def stuck(kind, v, counts, depth):
    """Hand a state to the solver; returns True (mover wins) / False / None."""
    stats['stuck_' + kind] += 1
    sol = run_solver(m.numeric_input(v, counts), 'stuck', STUCK_SECONDS, 64)
    stats['stuck_mid_calls'] += sol.get('mid_calls', 0)
    stats['stuck_seconds_x1000'] += int(1000 * sol.get('seconds', 0))
    res = {'win': True, 'loss': False}.get(sol['result'])
    stuck_log.append({'kind': kind, 'depth': depth, 'words_left': sum(counts), 'mid_calls': sol.get('mid_calls'), 'result': sol['result']})
    if res is None:
        stats['stuck_unsolved'] += 1
    return res


def rep(old_id, v, counts, static, depth):
    key = (v, counts)
    if key in memo:
        return memo[key]
    stats['new_nodes'] += 1
    if static != -1:
        val = static == 1
        stats['static_leaf'] += 1
    else:
        legal = [g for g in m.available[v] if counts[g]]
        moves = old_m[old_id]
        if not moves:                                   # old node was a static leaf, the new state is not
            val = stuck('old_static_leaf', v, counts, depth)
        elif old_w[old_id]:
            g, cid = moves[0]
            if g in legal:
                cv, cc, cs = m.child(v, counts, g)
                r = rep(cid, cv, cc, cs, depth + 1)
                if r is False:
                    val = True
                else:
                    val = stuck('witness_refuted' if r is True else 'witness_unknown', v, counts, depth)
            else:
                val = stuck('witness_illegal', v, counts, depth)
        else:
            omap = {g: c for g, c in moves}
            val, unknown = False, False
            for g in legal:
                cv, cc, cs = m.child(v, counts, g)
                if g in omap:
                    r = rep(omap[g], cv, cc, cs, depth + 1)
                elif cs != -1:
                    r = cs == 1
                    stats['new_move_static'] += 1
                else:
                    ck = (cv, cc)
                    if ck not in memo:
                        memo[ck] = stuck('new_move', cv, cc, depth + 1)
                    r = memo[ck]
                if r is False:
                    val = True
                    stats['old_L_node_became_W'] += 1
                    break
                if r is None:
                    unknown = True
            if val is False and unknown:
                val = None
    memo[key] = val
    return val


t1 = time.time()
root_val = rep(old_root, nv, ncounts, nstatic, 0)
out = {'case': f'{S}/{W}', 'hands_over': T,
       'old_root': {'result': old_sol['result'], 'search_nodes': old_sol['mid_calls'], 'proof_nodes': old_sol['proof_nodes'],
                    'seconds': old_sol['seconds']},
       'replay_root_value_for_mover': {True: 'W', False: 'L', None: 'unknown'}[root_val],
       'first_move': {True: 'lose', False: 'win', None: 'unknown'}[root_val],
       'replay_new_nodes': stats['new_nodes'], 'replay_python_seconds': round(time.time() - t1, 1),
       'stats': dict(stats),
       'stuck_calls': len(stuck_log),
       'stuck_biggest': sorted(stuck_log, key=lambda x: -(x['mid_calls'] or 0))[:5]}
print(json.dumps(out, ensure_ascii=False))
