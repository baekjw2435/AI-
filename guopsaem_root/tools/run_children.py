#!/usr/bin/env python3
"""Solve the first moves of one syllable, printing progress lines meant for people.

usage: run_children.py DICT WORD_COUNT DIR SECONDS TT_MB JOBS [--tt-save] [--only=c_5,c_9]

With --tt-save each undecided child keeps its search state in DIR/c_<k>.tt (checkpoint
every 10 minutes) and a later run resumes from it; the file is deleted once decided.
A child is started only while at least MIN_FREE_GB of disk is free.

DIR holds root.json and the children c_<k>.json / c_<k>.txt made by children.py.
Each child is the position after the receiver's first move (the other side to move).
 * a child the other side LOSES is a winning first move: the other runs are stopped,
   the child proof is verified, merged into a root proof and the root is verified;
 * if every child is a win for the other side, all are verified and merged (root = L).
Resumable: decided children, and undecided ones already run at least SECONDS, are skipped.
"""
import fcntl
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOLVER = os.environ.get('SOLVER_V4', '/home/user/AI-/.work/measure/solver_v4')
VERIFY = ROOT / 'verifier_v3' / 'verify_v3.py'
MERGE = ROOT / 'tools' / 'merge_root.py'
LOCK = Path(os.environ.get('VERIFY_LOCK', '/home/user/AI-/.work/verify.lock'))
MIN_FREE_GB = float(os.environ.get('MIN_FREE_GB', '4'))


def free_gb(path):
    return shutil.disk_usage(path).free / 2**30


def say(msg):
    print(time.strftime('%H:%M:%S'), msg, flush=True)


def verify(dic, nwords, pos, proof, inp):
    # one verification at a time across all runners (big certificates need a lot of memory)
    with open(LOCK, 'w') as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        return _verify(dic, nwords, pos, proof, inp)


def _verify(dic, nwords, pos, proof, inp):
    v = subprocess.run([sys.executable, str(VERIFY), '--dictionary', dic, '--expected-word-count', str(nwords),
                        '--position', str(pos), '--proof', str(proof)] + (['--input', str(inp)] if inp else []),
                       capture_output=True, text=True)
    try:
        r = json.loads(v.stdout)
    except ValueError:
        r = {'verified': False, 'error': (v.stderr or v.stdout)[-400:]}
    r['exit_code'] = v.returncode
    return r


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
    say(f'[시작] {name}: 첫 수 {len(kids)}개 중 {len(todo)}개를 {int(seconds)}초씩, {jobs}개 동시에 풉니다.')
    for k in kids:
        if decided(k):
            say(f'  (이미 끝남) {word[k]} → 상대 {"승" if res[k]["result"] == "win" else "패"}')
    running = {}
    found = next((k for k in kids if decided(k) and res[k]['result'] == 'loss'), None)
    while (todo or running) and not found:
        while todo and len(running) < jobs:
            k = todo.pop(0)
            out = open(d / f'{k}.out', 'w')
            cmd = [SOLVER, str(d / f'{k}.txt'), '--seconds', str(seconds), '--tt-mb', str(ttmb),
                   '--threads', '1', '--proof', str(d / f'{k}.pf.gz')]
            tt = d / f'{k}.tt'
            note = ''
            if save and free_gb(d) - int(ttmb) / 1024 >= MIN_FREE_GB:
                if tt.exists():
                    cmd += ['--tt-load', str(tt)]
                    note = ' (저장해 둔 계산 상태에서 이어서)'
                cmd += ['--tt-save', str(tt), '--checkpoint-seconds', '600']
            elif save:
                note = f' (디스크 여유 {free_gb(d):.1f}GB라 계산 상태 저장 안 함)'
            while free_gb(d) < MIN_FREE_GB:
                say(f'  디스크 여유 {free_gb(d):.1f}GB: 공간이 날 때까지 기다림')
                time.sleep(60)
            running[k] = (subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT), out)
            say(f'  풀기 시작: {word[k]}{note}')
        time.sleep(2)
        for k in list(running):
            p, out = running[k]
            if p.poll() is None:
                continue
            out.close()
            del running[k]
            try:
                r = json.loads((d / f'{k}.out').read_text().strip().splitlines()[-1])
            except (ValueError, IndexError):
                r = {'result': 'error', 'returncode': p.returncode}
            r['word'] = word[k]
            res[k] = r
            (d / f'res_{k}.json').write_text(json.dumps(r, ensure_ascii=False), encoding='utf-8')
            if r['result'] in ('win', 'loss') and (d / f'{k}.tt').exists():
                (d / f'{k}.tt').unlink()
            if r['result'] == 'loss':
                say(f'  ★ {word[k]} → 상대가 짐. 받는 쪽이 이기는 첫 수입니다 (증명 {r.get("proof_nodes", 0):,}국면, {r["seconds"]:.0f}초)')
                found = k
            elif r['result'] == 'win':
                say(f'  {word[k]} → 상대가 이김. 이 수로는 받는 쪽이 짐 (증명 {r.get("proof_nodes", 0):,}국면, {r["seconds"]:.0f}초)')
            else:
                say(f'  {word[k]} → {int(seconds)}초 안에 결론 없음 ({r.get("reason", r["result"])})')
                if (d / f'{k}.pf.gz').exists():
                    (d / f'{k}.pf.gz').unlink()
    for k, (p, out) in running.items():
        p.terminate(); p.wait(); out.close()
        say(f'  멈춤: {word[k]} (이기는 수를 찾아서 더 풀 필요 없음)')

    def check(ks):
        ok = True
        for k in ks:
            say(f'  검증 중: {word[k]} (증명 {res[k].get("proof_nodes", 0):,}국면)')
            v = verify(dic, nwords, d / f'{k}.json', d / f'{k}.pf.gz', d / f'{k}.txt')
            want = 'L' if res[k]['result'] == 'loss' else 'W'
            good = v['exit_code'] == 0 and v.get('verified') is True and v.get('result_for_player_to_move') == want
            res[k]['verify'] = {x: v.get(x) for x in ('verified', 'result_for_player_to_move', 'proof_sha256',
                                                       'checked_certificate_states', 'elapsed_seconds', 'error', 'exit_code')}
            (d / f'res_{k}.json').write_text(json.dumps(res[k], ensure_ascii=False), encoding='utf-8')
            say(f'  검증 {"통과" if good else "실패"}: {word[k]} ({v.get("elapsed_seconds", "?")}초) {v.get("error", "")}')
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
    rootproof = d / 'root.pf.gz'
    m = subprocess.run([sys.executable, str(MERGE), dic, str(nwords), str(d / 'root.json'), str(rootproof)]
                       + [str(d / f'{k}.pf.gz') for k in ks], capture_output=True, text=True)
    say(f'  합치기: {m.stdout.strip() or m.stderr.strip()[-300:]}')
    v = verify(dic, nwords, d / 'root.json', rootproof, None)
    want = 'W' if found else 'L'
    good = v['exit_code'] == 0 and v.get('verified') is True and v.get('result_for_player_to_move') == want
    (d / 'root_verify.json').write_text(json.dumps(v, ensure_ascii=False, indent=1), encoding='utf-8')
    if good:
        how = f'이기는 첫 수 {word[found]}' if found else f'첫 수 {len(kids)}개 모두 반박됨'
        say(f'[끝] {name} = {verdict} ({how}). 루트 증명 {v["checked_certificate_states"]:,}국면 검증 통과, sha256 {v["proof_sha256"][:16]}')
    else:
        say(f'[끝] {name}: 루트 검증 실패 {v.get("error", "")}')


if __name__ == '__main__':
    main()
