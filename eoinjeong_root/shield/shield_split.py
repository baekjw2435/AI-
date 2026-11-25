#!/usr/bin/env python3
"""보호막 계산을 첫 자리의 수별로 나눠 여러 코어에서 돌리고, 끝나면 합쳐 증명서를 만든다.

usage:
  shield_split.py start  present 죄 --shield 11 --dir DIR [--parts 4] [--hours 6]
  shield_split.py status --dir DIR
  shield_split.py finish --dir DIR --cert FILE        (모든 수가 끝났거나, 받은 쪽의 이기는 수가 하나라도 나왔을 때)

* 첫 자리 = 보호막 t(제시면 보호막-1)에서 그 음절을 받은 쪽. 낼 수 있는 수를 parts묶음으로 나눠(번갈아) C 엔진
  `part` 모드로 따로 돌린다. 수 하나가 끝날 때마다 DIR/moves/move_<i>.json에 그 수의 결과와 판정 근거가 남는다.
* 받은 쪽의 이기는 수(상대 자리가 패)가 하나라도 나오면 결과가 확정되므로 status가 나머지 묶음을 멈춘다.
* finish: 이기는 수가 있으면 첫 자리 = 승(그 수), 모든 수가 지면 첫 자리 = 패. 모든 수 파일의 근거 자리를 합치고
  루트 증명서(solver_v5 + verify_v4)를 붙여 shield-cert-2 증명서를 쓴다. 검증은 shield_verify.py로 따로.
* 시간 한도(--hours)는 묶음마다 timeout으로 건다. 다시 start하면 이미 끝난 수는 건너뛴다.
"""
import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import shield_calc as sc  # noqa: E402
import shield_export  # noqa: E402


def load_moves(d):
    out = {}
    for f in sorted((d / 'moves').glob('move_*.json')):
        m = json.loads(f.read_text(encoding='utf-8'))
        out[m['i']] = m
    return out


def cmd_start(a):
    d = Path(a.dir)
    (d / 'moves').mkdir(parents=True, exist_ok=True)
    base_used = [w.strip() for w in a.used.split(',') if w.strip()]
    t = max(0, a.shield - 1) if a.mode == 'present' else a.shield
    mp = shield_export.model_path(base_used)
    if not mp.exists():
        shield_export.export(base_used, mp)
    eng = sc.engine_binary()
    lst = json.loads(subprocess.run([str(eng), str(mp), a.syllable, str(t), 'list'], capture_output=True, text=True,
                                    check=True).stdout)
    head = json.loads(subprocess.run([str(eng), str(mp), a.syllable, '0'], capture_output=True, text=True,
                                     check=True).stdout)
    done = load_moves(d)
    parts = [[m['i'] for m in lst[k::a.parts] if m['i'] not in done] for k in range(a.parts)]
    meta = {'mode': a.mode, 'syllable': a.syllable, 'shield': a.shield, 'used': a.used, 't': t, 'model': str(mp),
            'moves': lst, 'cycle': head['cycle'], 'parts': parts, 'hours': a.hours, 'pids': [],
            'started': time.strftime('%Y-%m-%d %H:%M:%S')}
    for k, idx in enumerate(parts):
        if not idx:
            continue
        log = open(d / f'part{k}.log', 'a')
        p = subprocess.Popen(['timeout', f'{a.hours}h', str(eng), str(mp), a.syllable, str(t), 'part',
                              ','.join(map(str, idx)), str(d / 'moves')],
                             stdout=log, stderr=log, start_new_session=True)
        meta['pids'].append(p.pid)
    (d / 'meta.json').write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f"{a.syllable} 보호막 {t}에서 받음: 수 {len(lst)}개, 이미 끝난 수 {len(done)}개, "
          f"{len(meta['pids'])}묶음 시작(묶음마다 한도 {a.hours}시간)")


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def cmd_status(a):
    d = Path(a.dir)
    meta = json.loads((d / 'meta.json').read_text(encoding='utf-8'))
    moves = load_moves(d)
    wins = [m for m in moves.values() if m['value'] == 'L']
    unknown = [m for m in moves.values() if m['value'] not in ('L', 'W')]
    running = [p for p in meta['pids'] if alive(p)]
    print(json.dumps({'moves': len(meta['moves']), 'done': len(moves), 'receiver_wins': [(m['word'], m['end']) for m in wins],
                      'unknown': [(m['word'], m['end']) for m in unknown], 'running_parts': len(running)},
                     ensure_ascii=False))
    if wins and running:   # 이기는 수 하나로 확정: 나머지 묶음은 멈춘다
        for p in running:
            try:
                os.killpg(p, signal.SIGTERM)
            except OSError:
                pass
        print('받은 쪽의 이기는 수가 나와 결과가 확정되어 나머지 묶음을 멈췄습니다.')


def cmd_finish(a):
    d = Path(a.dir)
    meta = json.loads((d / 'meta.json').read_text(encoding='utf-8'))
    moves = load_moves(d)
    x, t = meta['syllable'], meta['t']
    wins = [m for m in moves.values() if m['value'] == 'L']
    nodes = {}
    for m in moves.values():
        for k, n in m['nodes'].items():
            nodes.setdefault(k, n)
    root_key = f'{x}|{t}|'
    if wins:
        m = min(wins, key=lambda m: m['i'])
        root = {'x': x, 't': t, 'used': [], 'v': 'W', 'why': f"{m['word']}(→{m['end']})", 'word': m['word'],
                'child': m['child']}
    else:
        missing = [mm['i'] for mm in meta['moves'] if mm['i'] not in moves]
        bad = [mm for mm in moves.values() if mm['value'] != 'W']
        if missing or bad:
            raise SystemExit(f'아직 확정 아님: 안 끝난 수 {len(missing)}개, 미정 {len(bad)}개')
        root = {'x': x, 't': t, 'used': [], 'v': 'L', 'why': f"낼 수 있는 수 {len(meta['moves'])}가지가 모두 상대 승",
                'words': [mm['word'] for mm in meta['moves']]}
    if t == 0:
        root = {k: v for k, v in root.items() if k not in ('word', 'child', 'words')} | {'leaf': True}
    nodes[root_key] = root
    lite = sc.Lite([w.strip() for w in meta['used'].split(',') if w.strip()])
    sc.attach_route_proofs(nodes, lite.base_used, lite.route_words, Path(a.cert + '.route'))
    q = {'mode': meta['mode'], 'syllable': x, 'shield': meta['shield'], 'used': meta['used']}
    cert = {'format': 'shield-cert-2', 'root': root_key, 'used': sorted(lite.base_used), 'cycle': meta['cycle'],
            'nodes': nodes, 'engine': {'engine': 'c', 'split': len(meta['parts'])}, 'query': q}
    Path(a.cert).write_text(json.dumps(cert, ensure_ascii=False), encoding='utf-8')
    res = {'present': {'L': '제시한 쪽 승', 'W': '제시한 쪽 패'}, 'receive': {'W': '받은 쪽 승', 'L': '받은 쪽 패'}}[meta['mode']][root['v']]
    print(f"{res}  ({root['why']})  근거 자리 {len(nodes)}개 → {a.cert}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('start')
    s.add_argument('mode', choices=['present', 'receive'])
    s.add_argument('syllable')
    s.add_argument('--shield', type=int, required=True)
    s.add_argument('--used', default='')
    s.add_argument('--dir', required=True)
    s.add_argument('--parts', type=int, default=4)
    s.add_argument('--hours', type=float, default=6)
    st = sub.add_parser('status')
    st.add_argument('--dir', required=True)
    f = sub.add_parser('finish')
    f.add_argument('--dir', required=True)
    f.add_argument('--cert', required=True)
    a = ap.parse_args()
    {'start': cmd_start, 'status': cmd_status, 'finish': cmd_finish}[a.cmd](a)


if __name__ == '__main__':
    main()
