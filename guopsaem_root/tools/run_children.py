#!/usr/bin/env python3
"""Solve the first moves of one syllable, printing progress lines meant for people.

usage: run_children.py DICT WORD_COUNT DIR SECONDS TT_MB JOBS [--tt-save] [--only=c_5,c_9]

DIR holds root.json and the children c_<k>.json / c_<k>.txt made by children.py.
Each child is the position after the receiver's first move (the other side to move).
 * a child the other side LOSES is a winning first move: the other runs are stopped,
   the child certificate is verified, merged into a root certificate and the root is verified;
 * if every child is a win for the other side, all are verified and merged (root = L).
Defaults: solver_v5, route-proof-v4 certificates, C++ verify_v4 with every acceptance
condition (see solve_common). With --tt-save each child checkpoints its search state in
DIR/c_<k>.tt (every CHECKPOINT_SECONDS, default 60 s per GB of table) and a later run, or the
same run after a container restart, resumes from it; the file is deleted once decided.
Resumable: decided children, and undecided ones already run at least SECONDS, are skipped.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'verifier_v3'))
sys.path.insert(0, str(ROOT / 'tools'))
from verify_v3 import ModelV3  # noqa: E402
import solve_common as sc  # noqa: E402

MERGE_V3 = ROOT / 'tools' / 'merge_root.py'
MERGE_V4 = ROOT / 'verifier_v4' / 'merge_root_v4.py'


def say(msg):
    print(time.strftime('%H:%M:%S'), msg, flush=True)


def main():
    dic, nwords, d, seconds, ttmb, jobs = sys.argv[1:7]
    save = '--tt-save' in sys.argv[7:]
    only = next((x.split('=', 1)[1].split(',') for x in sys.argv[7:] if x.startswith('--only=')), None)
    d, seconds, jobs = Path(d), float(seconds), int(jobs)
    root = json.loads((d / 'root.json').read_text(encoding='utf-8'))
    name = root['initial_syllable']
    kids = sorted((p.stem for p in d.glob('c_*.json')), key=lambda s: int(s.split('_')[1]))
    word = {k: json.loads((d / f'{k}.json').read_text(encoding='utf-8'))['history'][-1] for k in kids}
    res = {}
    for k in kids:
        f = d / f'res_{k}.json'
        if f.exists():
            res[k] = json.loads(f.read_text(encoding='utf-8'))

    def decided(k):
        return k in res and res[k]['result'] in ('win', 'loss')

    todo = [k for k in kids if not decided(k) and not (k in res and res[k].get('seconds', 0) >= seconds - 1)]
    if only:
        todo = [k for k in todo if k in only]
    say(f'[시작] {name}: 첫 수 {len(kids)}개 중 {len(todo)}개를 {int(seconds)}초씩, {jobs}개 동시에 풉니다 '
        f'({Path(sc.SOLVER).name}, 증명 {sc.PROOF_FORMAT}).')
    for k in kids:
        if decided(k):
            say(f'  (이미 끝남) {word[k]} → 상대 {"승" if res[k]["result"] == "win" else "패"}')
    running = {}
    found = next((k for k in kids if decided(k) and res[k]['result'] == 'loss'), None)
    while (todo or running) and not found:
        while todo and len(running) < jobs:
            k = todo.pop(0)
            sc.wait_for_disk(d, word[k])
            tt = d / f'{k}.tt' if save else None
            cmd, note = sc.solver_cmd(d / f'{k}.txt', d / f'{k}.pf.gz', seconds, ttmb, tt)
            out = open(d / f'{k}.out', 'w')
            running[k] = (subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT), out, tt, cmd)
            say(f'  풀기 시작: {word[k]}' + (f' ({note})' if note else ''))
        time.sleep(2)
        for k in list(running):
            p, out, tt, cmd = running[k]
            if p.poll() is None:
                continue
            out.close()
            del running[k]
            r = sc.parse_solver_output((d / f'{k}.out').read_text(), p.returncode)
            r['word'] = word[k]
            res[k] = r
            (d / f'res_{k}.json').write_text(json.dumps(r, ensure_ascii=False), encoding='utf-8')
            sc.finish_tt(tt, r, keep_unknown=True)
            pm = sc.merge_proven(cmd, ttmb)
            if pm is not None:
                r['proven_merge'] = pm
            if r['result'] == 'loss':
                say(f'  ★ {word[k]} → 상대가 짐. 받는 쪽이 이기는 첫 수입니다 (증명 {r.get("proof_nodes", 0):,}국면, {r["seconds"]:.0f}초)')
                found = k
            elif r['result'] == 'win':
                say(f'  {word[k]} → 상대가 이김. 이 수로는 받는 쪽이 짐 (증명 {r.get("proof_nodes", 0):,}국면, {r["seconds"]:.0f}초)')
            else:
                say(f'  {word[k]} → {int(seconds)}초 안에 결론 없음 ({r.get("reason", r["result"])})')
                if (d / f'{k}.pf.gz').exists():
                    (d / f'{k}.pf.gz').unlink()
    for k, (p, out, tt, cmd) in running.items():
        p.terminate(); p.wait(); out.close()
        say(f'  멈춤: {word[k]} (이기는 수를 찾아서 더 풀 필요 없음; 저장된 계산 상태는 남김)')

    def check(ks):
        ok = True
        for k in ks:
            say(f'  검증 중: {word[k]} (증명 {res[k].get("proof_nodes", 0):,}국면)')
            want = 'L' if res[k]['result'] == 'loss' else 'W'
            good, v = sc.verify(dic, nwords, d / f'{k}.json', d / f'{k}.pf.gz', d / f'{k}.txt', want,
                                res[k].get('proof_nodes', 0))
            res[k]['verify'] = v
            (d / f'res_{k}.json').write_text(json.dumps(res[k], ensure_ascii=False), encoding='utf-8')
            bad = [c for c, okc in v.get('acceptance', {}).items() if not okc]
            say(f'  검증 {"통과" if good else "실패"}: {word[k]} ({v.get("elapsed_seconds", "?")}초) {v.get("error", "")} {bad if bad else ""}')
            ok = ok and good
        return ok

    if found:
        ks = [found]
        verdict = '받으면 승'
    elif all(decided(k) and res[k]['result'] == 'win' for k in kids):
        ks = kids
        verdict = '받으면 패'
    else:
        open_ = [word[k] for k in kids if not decided(k)]
        say(f'[끝] {name}: 아직 결론 없음. 상대 승 {sum(decided(k) for k in kids)}개, 미정 {len(open_)}개: {", ".join(open_)}')
        return
    if not check(ks):
        say(f'[끝] {name}: 검증 실패. 결과를 쓰지 않습니다.')
        return
    m = ModelV3(open(dic, 'rb').read(), int(nwords))
    cur, counts, _ = m.position(root)
    root_in = d / 'root.txt'
    root_in.write_bytes(m.numeric_input(cur, counts))
    rootproof = d / 'root.pf.gz'
    if sc.PROOF_FORMAT == 'v4':
        cmd = [sys.executable, str(MERGE_V4), dic, str(nwords), str(d / 'root.json'), str(rootproof)] \
            + [f'{d / (k + ".json")}:{d / (k + ".pf.gz")}' for k in ks] + ['--input', str(root_in)]
    else:
        cmd = [sys.executable, str(MERGE_V3), dic, str(nwords), str(d / 'root.json'), str(rootproof)] \
            + [str(d / f'{k}.pf.gz') for k in ks]
    mr = subprocess.run(cmd, capture_output=True, text=True)
    say(f'  합치기: {mr.stdout.strip()[-300:] or mr.stderr.strip()[-300:]}')
    want = 'W' if found else 'L'
    nodes = sum(res[k].get('proof_nodes', 0) for k in ks)
    good, v = sc.verify(dic, nwords, d / 'root.json', rootproof, root_in, want, nodes)
    (d / 'root_verify.json').write_text(json.dumps(v, ensure_ascii=False, indent=1), encoding='utf-8')
    if good:
        how = f'이기는 첫 수 {word[found]}' if found else f'첫 수 {len(kids)}개 모두 반박됨'
        say(f'[끝] {name} = {verdict} ({how}). 루트 증명 {v.get("checked_certificate_states", 0):,}국면 검증 통과, sha256 {v["proof_sha256"][:16]}')
    else:
        say(f'[끝] {name}: 루트 검증 실패 {v.get("error", "")} {v.get("acceptance")}')


if __name__ == '__main__':
    main()
