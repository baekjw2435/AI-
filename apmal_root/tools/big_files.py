#!/usr/bin/env python3
"""GitHub은 100MB가 넘는 파일을 받지 않습니다. 그래서 큰 증명서는 조각으로 나눠 올립니다.

  pack            apmal_root/results 아래(저장 상태 tt/ 제외)에서 95MB가 넘는 파일을
                  <이름>.part00, .part01 … (조각마다 90MiB)과 <이름>.parts.json(전체·조각 sha256)으로 나눕니다.
                  원래 파일은 그 폴더의 .gitignore에 넣고, 이미 올라가 있었다면 git 목록에서만 뺍니다.
                  원래 파일이 바뀌었으면 조각을 새로 만듭니다. 원래 파일은 지우지 않습니다.
  check DIR       DIR 아래 모든 .parts.json에 대해 조각 sha256과, 이어 붙인 전체 sha256을 확인합니다.
                  (다시 받은 저장소에서 확인할 때 씀) --restore 를 주면 원래 파일도 다시 만듭니다.
"""
import hashlib, json, os, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / 'apmal_root' / 'results'
LIMIT = int(os.environ.get('BIG_LIMIT', 95 * 1000 * 1000))  # 시험할 때만 바꿈
PART = int(os.environ.get('BIG_PART', 90 * 1024 * 1024))
FORMAT = 'apmal-big-file-parts-1'


def sha_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def parts_of(p):
    return sorted(p.parent.glob(p.name + '.part[0-9][0-9]'))


def ignore(p):
    gi = p.parent / '.gitignore'
    lines = gi.read_text(encoding='utf-8').splitlines() if gi.exists() else []
    entry = '/' + p.name
    if entry not in lines:
        if not lines:
            lines = ['# 100MB가 넘어서 조각(.partNN)으로 나눠 올린 원래 파일 (tools/big_files.py)']
        lines.append(entry)
        gi.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    tracked = subprocess.run(['git', 'ls-files', '--error-unmatch', str(p)], cwd=ROOT,
                             capture_output=True).returncode == 0
    if tracked:
        subprocess.run(['git', 'rm', '--cached', '-q', str(p)], cwd=ROOT, check=True)


def pack():
    done = 0
    for p in sorted(RESULTS.rglob('*')):
        if not p.is_file() or 'tt' in p.relative_to(RESULTS).parts or '.part' in p.name \
                or p.name.endswith('.parts.json') or p.name.endswith('.tmp') or p.stat().st_size <= LIMIT:
            continue
        meta = p.parent / (p.name + '.parts.json')
        whole = sha_file(p)
        if meta.exists():
            m = json.loads(meta.read_text(encoding='utf-8'))
            if m.get('sha256') == whole and len(parts_of(p)) == len(m['parts']):
                ignore(p)
                continue
        for old in parts_of(p):
            old.unlink()
        parts = []
        with open(p, 'rb') as f:
            for i, b in enumerate(iter(lambda: f.read(PART), b'')):
                q = p.parent / f'{p.name}.part{i:02d}'
                q.write_bytes(b)
                parts.append({'name': q.name, 'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest()})
        meta.write_text(json.dumps({'format': FORMAT, 'file': p.name, 'bytes': p.stat().st_size,
                                    'sha256': whole, 'parts': parts}, ensure_ascii=False, indent=1) + '\n',
                        encoding='utf-8')
        ignore(p)
        done += 1
        print(f'나눔 {p.relative_to(ROOT)} {p.stat().st_size} 바이트 → 조각 {len(parts)}개')
    for meta in sorted(RESULTS.rglob('*.parts.json')):
        p = meta.parent / json.loads(meta.read_text(encoding='utf-8'))['file']
        if not p.exists() or p.stat().st_size <= LIMIT:
            print(f'주의: {p.relative_to(ROOT)} 원래 파일이 없거나 작아짐 — 조각을 손으로 확인할 것')
    print(f'pack: 새로 나눈 파일 {done}개')


def check(d, restore=False):
    bad = n = 0
    for meta in sorted(Path(d).rglob('*.parts.json')):
        m = json.loads(meta.read_text(encoding='utf-8'))
        assert m.get('format') == FORMAT, meta
        h, size, ok = hashlib.sha256(), 0, True
        out = open(meta.parent / m['file'], 'wb') if restore else None
        for part in m['parts']:
            b = (meta.parent / part['name']).read_bytes()
            if len(b) != part['bytes'] or hashlib.sha256(b).hexdigest() != part['sha256']:
                ok = False
            h.update(b)
            size += len(b)
            if out:
                out.write(b)
        if out:
            out.close()
        ok = ok and size == m['bytes'] and h.hexdigest() == m['sha256']
        n += 1
        bad += not ok
        print(('맞음 ' if ok else '틀림 ') + str(meta.parent / m['file']), m['sha256'])
    print(f'check: {n}개 중 틀림 {bad}개')
    return bad == 0


if __name__ == '__main__':
    if sys.argv[1:2] == ['pack']:
        pack()
    elif sys.argv[1:2] == ['check'] and len(sys.argv) >= 3:
        sys.exit(0 if check(sys.argv[2], '--restore' in sys.argv) else 1)
    else:
        sys.exit(__doc__)
