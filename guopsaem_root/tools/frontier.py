#!/usr/bin/env python3
"""Solve many root syllables through their shared frontier (Astra review 4, 2026-11-05).

  frontier.py plan     DICT WORD_COUNT SYLLABLES WORKDIR [--max-first N] [--skip-file F]
  frontier.py solve    DICT WORD_COUNT WORKDIR SECONDS TT_MB JOBS
  frontier.py assemble DICT WORD_COUNT WORKDIR

plan: for every root vertex (raw syllables with the same vertex are one root), expand each
legal first group of its canonical state, then follow FORCED moves (exactly one legal group,
non-static) and stop at the first non-forced or static state. Endpoints are merged when their
(vertex, complete canonical count bytes) are equal, so a state reached from several roots is
solved once. Every request keeps its full move list (groups and representative words); the
parity of the moves decides how the endpoint's value maps back to the root.
solve: each unique non-static endpoint is a job (position = a root syllable + history words);
solved with solve_common (solver_v5, v4 certificates, C++ verifier, checkpoints).
assemble: a root is W if some first move leads (after the forced moves) to a loss for the
side that must move after the root player, L if every first move leads to a win for it.
The root certificate is built bottom-up with merge_root_v4.py along each chain (forced nodes
included) and verified with every acceptance condition for each raw syllable of the root.
Nothing here is trusted: only the final verification of each root certificate counts.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'verifier_v3'))
sys.path.insert(0, str(ROOT / 'tools'))
from verify_v3 import ModelV3  # noqa: E402
import solve_common as sc  # noqa: E402

MERGE_V4 = ROOT / 'verifier_v4' / 'merge_root_v4.py'


def say(msg):
    print(time.strftime('%H:%M:%S'), msg, flush=True)


def load_model(dic, nwords):
    return ModelV3(open(dic, 'rb').read(), int(nwords))


def pick_word(m, group, used):
    for w in sorted(m.words):
        if w not in used and m.word_group(w) == group:
            return w
    raise RuntimeError(f'no unused word in group {group}')


def plan(dic, nwords, sylfile, work, max_first, skip):
    m = load_model(dic, nwords)
    work.mkdir(parents=True, exist_ok=True)
    roots = {}
    for s in open(sylfile, encoding='utf-8').read().split():
        if s not in skip:
            roots.setdefault(m.vertex_of(s), []).append(s)
    endpoints = {}          # (vertex, bytes) -> endpoint id
    ep_list = []
    requests = []
    root_list = []
    for v, members in sorted(roots.items(), key=lambda x: x[1][0]):
        rep = members[0]
        pos0 = {"initial_syllable": rep, "history": []}
        cur, counts, _ = m.position(pos0)
        canon, st = m.normalize(cur, counts)
        legal = [g for g in m.available[cur] if canon[g]]
        if st != -1:
            root_list.append({'members': members, 'static': st, 'requests': []})
            continue
        if max_first and len(legal) > max_first:
            continue
        rids = []
        for first in legal:
            hist, groups = [], []
            t, k, stt = cur, canon, -1
            g = first
            while True:
                w = pick_word(m, g, set(hist))
                hist.append(w); groups.append(g)
                t, k, stt = m.child(t, k, g)
                # the state the solver/verifier will see for this history must be the same
                c2, k2, _ = m.position({"initial_syllable": rep, "history": hist})
                n2, s2 = m.normalize(c2, k2)
                assert (c2, n2, s2) == (t, k, stt), f'{rep} {hist}: replayed state differs'
                if stt != -1:
                    break
                ls = [x for x in m.available[t] if k[x]]
                if len(ls) != 1:
                    break
                g = ls[0]
            key = (t, bytes(k))
            if stt == -1:
                if key not in endpoints:
                    endpoints[key] = len(ep_list)
                    ep_list.append({'id': len(ep_list), 'vertex': m.names[t], 'position': {"initial_syllable": rep, "history": hist},
                                    'roots': []})
                eid = endpoints[key]
                ep_list[eid]['roots'].append(rep)
            else:
                eid = None
            rids.append(len(requests))
            requests.append({'root': rep, 'groups': groups, 'words': hist, 'plies': len(hist),
                             'endpoint': eid, 'endpoint_static': stt})
        root_list.append({'members': members, 'static': -1, 'requests': rids})
    for e in ep_list:
        d = work / 'jobs' / f'e{e["id"]}'
        d.mkdir(parents=True, exist_ok=True)
        (d / 'pos.json').write_text(json.dumps(e['position'], ensure_ascii=False), encoding='utf-8')
        c, k, _ = m.position(e['position'])
        (d / 'in.txt').write_bytes(m.numeric_input(c, k))
    summary = {'roots': len(root_list), 'requests': len(requests),
               'static_endpoints': sum(1 for r in requests if r['endpoint'] is None),
               'unique_endpoints': len(ep_list),
               'max_plies': max((r['plies'] for r in requests), default=0)}
    (work / 'plan.json').write_text(json.dumps({'summary': summary, 'roots': root_list, 'requests': requests,
                                                'endpoints': ep_list}, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False))


def root_states(P, ep_value):
    """For every root: 'W', 'L' or None from the endpoint values known so far (parity per request)."""
    out = {}
    for R in P['roots']:
        if R['static'] != -1:
            continue
        vals = []
        for rid in R['requests']:
            q = P['requests'][rid]
            v_end = bool(q['endpoint_static']) if q['endpoint'] is None else ep_value.get(q['endpoint'])
            vals.append(None if v_end is None else (v_end if (q['plies'] - 1) % 2 == 0 else (not v_end)))
        out[R['members'][0]] = 'W' if any(v is False for v in vals) else ('L' if all(v is True for v in vals) else None)
    return out


def solve(dic, nwords, work, seconds, ttmb, jobs):
    """Solve the unique endpoints. An endpoint is skipped (left for later) once every root that
    uses it is already decided by other endpoints (e.g. a root already won by another first move)."""
    import threading
    P = json.loads((work / 'plan.json').read_text(encoding='utf-8'))
    # endpoints shared by many roots first, then by plan order
    order = sorted(P['endpoints'], key=lambda e: (-len(e['roots']), e['id']))
    ep_value = {}
    for e in P['endpoints']:
        f = work / 'jobs' / f'e{e["id"]}' / 'res.json'
        if f.exists():
            r = json.loads(f.read_text(encoding='utf-8'))
            if r.get('verified'):
                ep_value[e['id']] = r['solver']['result'] == 'win'
    users = {e['id']: sorted({P['requests'][i]['root'] for i, q in enumerate(P['requests']) if q['endpoint'] == e['id']})
             for e in P['endpoints']}

    # PER_ROOT_BUDGET=1: SECONDS is a budget per ROOT, split evenly over that root's first-move
    # requests (an endpoint shared by several roots gets the largest of their shares), so that a
    # comparison with solving the root directly uses the same total time per syllable.
    per_root = os.environ.get('PER_ROOT_BUDGET') == '1'
    nreq = {}
    for q in P['requests']:
        nreq[q['root']] = nreq.get(q['root'], 0) + 1

    def budget(e):
        if not per_root:
            return seconds
        return max(seconds / nreq[q['root']] for q in P['requests'] if q['endpoint'] == e['id'])

    def todo(e):
        f = work / 'jobs' / f'e{e["id"]}' / 'res.json'
        if not f.exists():
            return True
        r = json.loads(f.read_text(encoding='utf-8'))
        if r.get('verified'):
            return False
        if r['solver'].get('result') in ('win', 'loss'):
            return True        # solved but no accepted certificate: run again from the saved state
        return r['solver'].get('seconds', 0) < budget(e) - 1

    queue = [e for e in order if todo(e)]
    lock = threading.Lock()
    skipped = []

    def next_job():
        with lock:
            while queue:
                e = queue.pop(0)
                st = root_states(P, ep_value)
                if all(st.get(r) is not None for r in users[e['id']]):
                    skipped.append(e['id'])
                    continue
                return e
            return None

    def run(e):
        d = work / 'jobs' / f'e{e["id"]}'
        sc.wait_for_disk(work, f'e{e["id"]}')
        try:
            sol = sc.solve(d / 'in.txt', d / 'cert.jsonl.gz', budget(e), ttmb, tt=d / 'state.tt', log=d / 'solver.out')
        except sc.LowDisk as err:
            say(f'  e{e["id"]} 시작하지 않음 (디스크 부족, 저장 상태는 그대로 둠): {err}')
            return
        res = {'endpoint': e['id'], 'vertex': e['vertex'], 'roots': e['roots'], 'solver': sol, 'verified': False}
        if sol.get('result') in ('win', 'loss') and not sol.get('proof_error'):
            want = 'W' if sol['result'] == 'win' else 'L'
            ok, vr = sc.verify(dic, nwords, d / 'pos.json', d / 'cert.jsonl.gz', d / 'in.txt', want,
                               sol.get('proof_nodes', 0))
            res['verify'] = vr
            res['verified'] = ok
            res['state_released'] = sc.release_state(d / 'state.tt', ok, d / 'cert.jsonl.gz')   # only after acceptance
        elif (d / 'cert.jsonl.gz').exists() and sol.get('result') not in ('win', 'loss'):
            (d / 'cert.jsonl.gz').unlink()
        (d / 'res.json').write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
        if res['verified']:
            with lock:
                ep_value[e['id']] = sol['result'] == 'win'
        result = sol.get('result')
        tag = {'win': '둘 차례가 이김', 'loss': '둘 차례가 짐', 'error': '오류'}.get(result, '결론 없음')
        say(f'  e{e["id"]} ({e["vertex"]}, 루트 {len(e["roots"])}개: {" ".join(e["roots"][:6])}) → {tag}'
            + (' (검증 통과)' if res['verified'] else (' (검증 실패!)' if result in ('win', 'loss') else '')))

    def worker():
        while True:
            e = next_job()
            if e is None:
                return
            run(e)

    say(f'[시작] 고유 작업 {len(P["endpoints"])}개 중 {len(queue)}개를 {int(seconds)}초씩, {jobs}개 동시에 '
        f'({Path(sc.SOLVER).name}, 증명 {sc.PROOF_FORMAT}' + (', 공유 캐시' if sc.PROVEN_DIR else '') + ')')
    th = [threading.Thread(target=worker) for _ in range(jobs)]
    for t in th:
        t.start()
    for t in th:
        t.join()
    st = root_states(P, ep_value)
    say(f'[끝] 확정 루트: 승 {sum(v == "W" for v in st.values())}, 패 {sum(v == "L" for v in st.values())}, '
        f'미정 {sum(v is None for v in st.values())}; 이미 확정된 루트만 쓰는 작업 {len(skipped)}개는 건너뜀')
    (work / f'SOLVED_{int(seconds)}s').write_text('done\n')


def assemble(dic, nwords, work):
    m = load_model(dic, nwords)
    P = json.loads((work / 'plan.json').read_text(encoding='utf-8'))
    ep_value = {}
    for e in P['endpoints']:
        f = work / 'jobs' / f'e{e["id"]}' / 'res.json'
        if f.exists():
            r = json.loads(f.read_text(encoding='utf-8'))
            if r.get('verified'):
                ep_value[e['id']] = r['solver']['result'] == 'win'      # True: side to move wins
    out_dir = work / 'roots'
    out_dir.mkdir(exist_ok=True)
    summary = {'W': [], 'L': [], 'unknown': [], 'failed': []}
    for R in P['roots']:
        rep = R['members'][0]
        if R['static'] != -1:
            continue
        lines = []
        for rid in R['requests']:
            q = P['requests'][rid]
            if q['endpoint'] is None:
                v_end = bool(q['endpoint_static'])
            elif q['endpoint'] in ep_value:
                v_end = ep_value[q['endpoint']]
            else:
                v_end = None
            # value for the side to move right after the root move: flips once per forced move
            if v_end is None:
                lines.append((q, None))
            else:
                v_after = v_end if (q['plies'] - 1) % 2 == 0 else (not v_end)
                lines.append((q, v_after))
        win = [q for q, v in lines if v is False]
        if win:
            verdict, use = 'W', [win[0]]
        elif all(v is True for _, v in lines):
            verdict, use = 'L', [q for q, _ in lines]
        else:
            summary['unknown'].append(rep)
            continue
        ok = build_root_certificate(m, dic, nwords, work, out_dir, R, use, verdict)
        summary[verdict if ok else 'failed'].append(rep)
        say(f'  {rep}: 받으면 {"승" if verdict == "W" else "패"}' + (' (루트 증명 검증 통과)' if ok else ' (검증 실패!)'))
    (work / 'assemble.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps({k: len(v) for k, v in summary.items()}, ensure_ascii=False))


def build_root_certificate(m, dic, nwords, work, out_dir, R, use, verdict):
    """Bottom-up merges along each chain, then at the root; verified for every member syllable."""
    rep = R['members'][0]
    rd = out_dir / rep
    rd.mkdir(exist_ok=True)

    def position(hist):
        return {"initial_syllable": rep, "history": hist}

    def write_pos(path, hist):
        path.write_text(json.dumps(position(hist), ensure_ascii=False), encoding='utf-8')
        c, k, _ = m.position(position(hist))
        inp = path.with_suffix('.txt')
        inp.write_bytes(m.numeric_input(c, k))
        return inp

    children = []
    for n, q in enumerate(use):
        words = q['words']
        # certificate of the deepest position on this line
        if q['endpoint'] is None:
            cert = None
        else:
            src = work / 'jobs' / f'e{q["endpoint"]}' / 'cert.jsonl.gz'
            ep_pos = json.loads((work / 'jobs' / f'e{q["endpoint"]}' / 'pos.json').read_text(encoding='utf-8'))
            if ep_pos['history'] != words or ep_pos['initial_syllable'] != rep:
                # the endpoint was planned from another root: its certificate starts from the same
                # canonical state, which merge_root_v4 checks again when it is used as a child
                pass
            cert = src
        # walk up from the endpoint to the state right after the root move
        for depth in range(len(words) - 1, 0, -1):
            parent_hist = words[:depth]
            child_hist = words[:depth + 1]
            ppos = rd / f'l{n}_d{depth}.json'
            pin = write_pos(ppos, parent_hist)
            cpos = rd / f'l{n}_d{depth + 1}.json'
            write_pos(cpos, child_hist)
            out = rd / f'l{n}_d{depth}.cert.jsonl.gz'
            args = [sys.executable, str(MERGE_V4), dic, str(nwords), str(ppos), str(out)]
            args += [f'{cpos}:{cert}'] if cert is not None else []
            args += ['--input', str(pin)]
            r = subprocess.run(args, capture_output=True, text=True)
            if r.returncode != 0:
                say(f'    {rep}: chain merge failed: {r.stderr.strip()[-300:]}')
                return False
            cert = out
        cpos = rd / f'l{n}_d1.json'
        write_pos(cpos, words[:1])
        children.append((cpos, cert))
    rpos = rd / 'root.json'
    rin = write_pos(rpos, [])
    rcert = rd / 'root.cert.jsonl.gz'
    args = [sys.executable, str(MERGE_V4), dic, str(nwords), str(rpos), str(rcert)]
    args += [f'{p}:{c}' for p, c in children if c is not None]
    args += ['--input', str(rin)]
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        say(f'    {rep}: root merge failed: {r.stderr.strip()[-300:]}')
        return False
    ok_all = True
    record = {}
    for s in R['members']:
        p = rd / f'member_{s}.json'
        p.write_text(json.dumps({"initial_syllable": s, "history": []}, ensure_ascii=False), encoding='utf-8')
        c, k, _ = m.position({"initial_syllable": s, "history": []})
        inp = rd / f'member_{s}.txt'
        inp.write_bytes(m.numeric_input(c, k))
        ok, v = sc.verify(dic, nwords, p, rcert, inp, verdict)
        record[s] = v
        ok_all = ok_all and ok
    (rd / 'verify.json').write_text(json.dumps({'verdict': verdict, 'accepted': ok_all, 'members': record},
                                               ensure_ascii=False, indent=1), encoding='utf-8')
    return ok_all


def main():
    cmd = sys.argv[1]
    if cmd == 'plan':
        dic, nwords, sylfile, work = sys.argv[2:6]
        rest = sys.argv[6:]
        max_first = int(rest[rest.index('--max-first') + 1]) if '--max-first' in rest else 0
        skip = set(open(rest[rest.index('--skip-file') + 1], encoding='utf-8').read().split()) if '--skip-file' in rest else set()
        plan(dic, nwords, sylfile, Path(work), max_first, skip)
    elif cmd == 'solve':
        dic, nwords, work, seconds, ttmb, jobs = sys.argv[2:8]
        solve(dic, nwords, Path(work), float(seconds), ttmb, int(jobs))
    elif cmd == 'assemble':
        dic, nwords, work = sys.argv[2:5]
        assemble(dic, nwords, Path(work))
    else:
        sys.exit(__doc__)


if __name__ == '__main__':
    main()
