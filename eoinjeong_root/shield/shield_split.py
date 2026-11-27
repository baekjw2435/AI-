#!/usr/bin/env python3
"""보호막 계산을 첫 자리의 수별로 나눠 여러 코어에서 돌리고, 끝나면 합쳐 증명서를 만든다.

usage:
  shield_split.py start  present 죄 --shield 11 --dir DIR [--parts 4] [--hours 6]
  shield_split.py status --dir DIR
  shield_split.py rebalance --dir DIR [--cores 4]     (묶음이 먼저 끝나 코어가 놀 때)
  shield_split.py finish --dir DIR --cert FILE        (모든 수가 끝났거나, 받은 쪽의 이기는 수가 하나라도 나왔을 때)
  shield_split.py store --cert FILE --verify-json V --out DIR --name present_법_12 --question "보호막 12에서 ~법 제시"

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
import shield_files as F  # noqa: E402  (끝말잇기/앞말잇기 자료: SHIELD_GAME)


def load_heads(d):
    """수 파일의 앞부분(결과)만 읽는다. 근거 자리(nodes)는 크니까 status에서는 안 읽는다."""
    import re
    out = {}
    for f in sorted((d / 'moves').glob('move_*.json')):
        with open(f, encoding='utf-8') as fh:
            head = fh.read(4096)
        m = re.match(r'\{"i":(\d+),"end":"([^"]*)","word":"([^"]*)","value":"([WL?])"', head)
        if m:
            out[int(m.group(1))] = {'i': int(m.group(1)), 'end': m.group(2), 'word': m.group(3), 'value': m.group(4)}
    return out


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
    meta = {'game': F.GAME, 'mode': a.mode, 'syllable': a.syllable, 'shield': a.shield, 'used': a.used, 't': t, 'model': str(mp),
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
    moves = load_heads(d)
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
    if meta.get('game', 'end') != F.GAME:
        raise SystemExit(f"이 계산은 {meta.get('game', 'end')} 게임인데 지금 SHIELD_GAME은 {F.GAME}입니다.")
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
    cert = {'format': 'shield-cert-2', 'game': F.GAME, 'root': root_key, 'used': sorted(lite.base_used), 'cycle': meta['cycle'],
            'nodes': nodes, 'engine': {'engine': 'c', 'split': len(meta['parts'])}, 'query': q}
    Path(a.cert).write_text(json.dumps(cert, ensure_ascii=False), encoding='utf-8')
    res = {'present': {'L': '제시한 쪽 승', 'W': '제시한 쪽 패'}, 'receive': {'W': '받은 쪽 승', 'L': '받은 쪽 패'}}[meta['mode']][root['v']]
    print(f"{res}  ({root['why']})  근거 자리 {len(nodes)}개 → {a.cert}")


def cmd_rebalance(a):
    """놀고 있는 코어에 남은 수를 나눠 준다. 지금 계산 중인 수는 건드리지 않고, 일이 가장 많이 남은 묶음의
    뒤쪽 절반을 새 묶음으로 띄운다(같은 수를 두 묶음이 겹쳐 따지지 않게, 이미 맡긴 수는 다시 안 맡긴다)."""
    d = Path(a.dir)
    meta = json.loads((d / 'meta.json').read_text(encoding='utf-8'))
    done = set(load_heads(d))
    live = [(idx, pid) for idx, pid in zip(meta['parts'], meta['pids']) if alive(pid)]
    idle = a.cores - len(live)
    # 살아 있는 묶음마다: 지금 하는 수(첫 미완료)는 그 묶음 몫, 나머지 중 다른 살아 있는 묶음이 먼저 맡은 수는 빼고
    claimed, pools = set(), []
    for idx, _ in live:
        rest = [i for i in idx if i not in done]
        if rest:
            claimed.add(rest[0])
    for idx, _ in live:
        rest = [i for i in idx if i not in done and i not in claimed]
        pools.append(rest[::-1])     # 뒤에서부터 맡긴다(원래 묶음은 앞에서부터 하므로 겹침이 적다)
    started = time.mktime(time.strptime(meta['started'], '%Y-%m-%d %H:%M:%S'))
    left_h = meta['hours'] - (time.time() - started) / 3600
    eng = sc.engine_binary()
    given = set()
    for _ in range(max(0, idle)):
        pools = [[i for i in p if i not in given] for p in pools]
        pools.sort(key=len, reverse=True)
        if not pools or not pools[0] or left_h <= 0.05:
            break
        take = pools[0][:len(pools[0]) // 2 + 1]
        given |= set(take)
        log = open(d / f"extra{len(meta['pids'])}.log", 'a')
        p = subprocess.Popen(['timeout', f'{left_h:.2f}h', str(eng), meta['model'], meta['syllable'], str(meta['t']),
                              'part', ','.join(map(str, take)), str(d / 'moves')],
                             stdout=log, stderr=log, start_new_session=True)
        meta['pids'].append(p.pid)
        meta['parts'].append(take)
        print(f'놀던 코어에 {len(take)}수를 맡김(남은 한도 {left_h:.2f}시간)')
    (d / 'meta.json').write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding='utf-8')
    if idle <= 0:
        print('놀고 있는 코어 없음')


def cmd_store(a):
    """검증을 통과한 큰 증명서를 저장소용 40MB 조각 + MANIFEST.json으로 만든다(GitHub 파일 하나 100MB 제한).
    증명서(.json)와 그 옆 .json.route/ 폴더(루트 증명서)를 조각으로 나누고, 다시 합친 해시를 확인한다."""
    import glob
    import gzip
    import hashlib
    import io
    import tarfile
    cert, out = Path(a.cert), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    ver = json.loads(Path(a.verify_json).read_text(encoding='utf-8'))
    if not ver.get('verified'):
        raise SystemExit('검증을 통과하지 않은 증명서는 보관하지 않습니다.')

    def sha(b):
        return hashlib.sha256(b).hexdigest()
    raw = cert.read_bytes()
    gz = gzip.compress(raw, 9)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as tar:
        rdir = Path(str(cert) + '.route')
        if rdir.exists():
            for f in sorted(rdir.iterdir()):
                if f.suffix not in ('.log', '.tt'):
                    tar.add(f, arcname=f'{a.name}.json.route/{f.name}')
    route = buf.getvalue()
    size = 40 << 20
    parts = {}
    for label, data in ((f'{a.name}.json.gz', gz), ('route.tgz', route)):
        for k in range(0, max(1, (len(data) + size - 1) // size)):
            name = f'{label}.part{k:02d}'
            chunk = data[k * size:(k + 1) * size]
            (out / name).write_bytes(chunk)
            parts[name] = {'bytes': len(chunk), 'sha256': sha(chunk)}
    m = {'question': a.question, 'result': ver['result'], 'verified': True, 'nodes': ver['nodes'], 'leaves': ver['leaves'],
         'certificate_json_sha256': sha(raw), 'certificate_json_gz_sha256': sha(gz), 'route_tgz_sha256': sha(route),
         'parts': parts}
    (out / 'MANIFEST.json').write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding='utf-8')
    back = b''.join((out / n).read_bytes() for n in sorted(parts) if n.startswith(f'{a.name}.json.gz'))
    assert sha(back) == m['certificate_json_gz_sha256'] and sha(gzip.decompress(back)) == m['certificate_json_sha256']
    (out / 'README_KO.md').write_text(f"""# {a.question} — {ver['result']} (검증 통과)

근거 자리 {ver['nodes']:,}개. 파일이 커서 40MB 조각으로 나눠 두었습니다. 다시 확인하려면 이 폴더에서:

```
cat {a.name}.json.gz.part* > {a.name}.json.gz
cat route.tgz.part* | tar xzf -
python3 ../../../shield_verify.py {a.name}.json.gz
```
""", encoding='utf-8')
    print(f"{out}: 조각 {len(parts)}개, 합친 해시 확인됨")


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
    r = sub.add_parser('rebalance')
    r.add_argument('--dir', required=True)
    r.add_argument('--cores', type=int, default=4)
    so = sub.add_parser('store')
    so.add_argument('--cert', required=True, help='finish로 만든 증명서 .json (옆에 .json.route/)')
    so.add_argument('--verify-json', required=True, help='shield_verify.py 출력(JSON)')
    so.add_argument('--out', required=True, help='저장소 안의 보관 폴더')
    so.add_argument('--name', required=True, help='파일 이름 앞부분, 예: present_법_12')
    so.add_argument('--question', required=True, help='예: 보호막 12에서 ~법 제시')
    a = ap.parse_args()
    {'start': cmd_start, 'status': cmd_status, 'finish': cmd_finish, 'rebalance': cmd_rebalance,
     'store': cmd_store}[a.cmd](a)


if __name__ == '__main__':
    main()
