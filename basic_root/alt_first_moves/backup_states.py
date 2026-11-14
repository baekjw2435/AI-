#!/usr/bin/env python3
"""Back up saved search states (state.tt) outside the work environment, as GitHub release attachments.

A saved state lives only in the work folder (.work/); a new work environment does not have it. This tool keeps
a gzip copy of each state with its SHA-256, so a later session can download it and continue the search.

usage:
  backup_states.py stage TAG STAGING NOTE STATE [STATE ...]
        STAGING/TAG/<sha256 of the .gz>.tt.gz for every STATE, STAGING/TAG/MANIFEST.json, and the entries in
        results/states/INDEX.json (status 'staged'). STATE is a path under /home/user/AI-/.work/, or FILE=RELPATH
        to back up a copy FILE (e.g. taken before a run that keeps rewriting the state) that restores to RELPATH.
        Then commit STAGING/TAG to the session branch and run the upload job (upload-proof-releases).
  backup_states.py check TAG
        download every file of TAG again, compare the SHA-256 of the .gz and of the unpacked state, and write the
        result into results/states/INDEX.json.
  backup_states.py restore WORK [TAG ...]
        put the states back under WORK (default layout /home/user/AI-/.work). A file that is already there with the
        same content is left alone; a different file there is NOT overwritten (reported instead).

What a state is: the 2,000,000 table entries with the most work (--tt-save-max), plus the search seconds carried in
it (solve_common.state_carried_seconds). Loading it is not the same as never having stopped. A state is a hint for
the solver only; a verdict still needs an accepted certificate.
"""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / 'guopsaem_root' / 'tools'))
import solve_common as sc  # noqa: E402

WORK = Path('/home/user/AI-/.work')
INDEX = HERE / 'results' / 'states' / 'INDEX.json'
REPO_URL = 'https://github.com/baekjw2435/AI-/releases'


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def load_index():
    if INDEX.exists():
        return json.loads(INDEX.read_text(encoding='utf-8'))
    return {'format': 'state-backup-1', 'note': 'saved search states (state.tt) kept as gzip release attachments', 'states': []}


def save_index(ix):
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(json.dumps(ix, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    if INDEX == HERE / 'results' / 'states' / 'INDEX.json':
        write_readme(ix)


def still_needed(e):
    """Is the position of this state still undecided? From the repository's records only."""
    pos = e.get('position') or {}
    hist = pos.get('history') or []
    if not hist:                                   # a source: 'syllable received, nothing used'
        syl = Path(e['work_path']).parts[1]
        done = list((HERE / 'results').glob(f'*/sources/{syl}/prep.json'))
        return (False, f'원본 완성({done[0].parts[-4]})') if done else (True, '원본 미완성')
    doc = json.loads((HERE / 'targets.json').read_text(encoding='utf-8'))
    summ = json.loads((HERE / 'results' / 'summary.json').read_text(encoding='utf-8'))
    t = next((t for t in doc['targets'] if t['syllable'] == pos['initial_syllable'] and hist[0] in t['words']), None)
    if t is None:
        return True, '?'
    dec = next((x for x in summ.get(t['id'], []) if x['decided']), None)
    return (False, f'확정({dec["batch"]})') if dec else (True, '미확정')


def write_readme(ix):
    L = ['# 저장 상태 백업', '',
         '이 파일은 `backup_states.py`가 `INDEX.json`에서 만듭니다. 직접 고치지 마세요.', '',
         '- 저장 상태(`state.tt`)를 gzip으로 묶어 GitHub 릴리스에 첨부한 목록입니다. 작업 환경이 바뀌어도 이어 풀 수 있게 하려는 것입니다.',
         '- 저장 상태는 다시 계산하기 가장 비싼 기록 200만 개만 남깁니다. 불러와 이어 풀어도 끊기지 않은 것과 같지는 않습니다.',
         '- 판정이 아닙니다. 확정은 검증을 통과한 증명서로만 합니다.',
         '- 되돌리기: `python3 backup_states.py restore /home/user/AI-/.work [태그]`', '',
         '| 태그 | 국면 | 되돌릴 경로 | 든 탐색(초) | 크기(MB) | 올린 뒤 확인 | 지금 |', '|---|---|---|---:|---:|---|---|']
    for e in sorted(ix['states'], key=lambda e: (e['release_tag'], e['work_path'])):
        pos = e.get('position') or {}
        what = f'{pos.get("initial_syllable", "?")} 받음' + (f', {pos["history"][0]}' if pos.get('history') else ', 단어 없음(원본)')
        need, now = still_needed(e)
        L.append(f'| `{e["release_tag"]}` | {what} | `{e["work_path"]}` | {e["carried_search_seconds"]:,.0f} | {e["gz_bytes"] / 1e6:,.0f} | '
                 f'{e["uploaded_verified"] or "아직"} | {now if need else now + " - 더 필요 없음"} |')
    L.append('')
    (INDEX.parent / 'README_KO.md').write_text('\n'.join(L), encoding='utf-8')


def describe(state):
    """What the state is for: the position file next to it."""
    pos = state.parent / 'pos.json'
    p = json.loads(pos.read_text(encoding='utf-8')) if pos.exists() else None
    return {'position': p, 'position_sha256': sha(pos) if pos.exists() else None,
            'input_sha256': sha(state.parent / 'in.txt') if (state.parent / 'in.txt').exists() else None}


def stage(tag, staging, note, states):
    out = Path(staging) / tag
    out.mkdir(parents=True, exist_ok=True)
    ix = load_index()
    manifest = {'release_tag': tag, 'files': {}}
    for arg in states:
        src, _, as_rel = arg.partition('=')
        s = Path(src).resolve()
        rel = Path(as_rel) if as_rel else s.relative_to(WORK)
        raw = sha(s)
        tmp = out / 'tmp.tt.gz'
        with open(s, 'rb') as fi, open(tmp, 'wb') as raw_out, \
                gzip.GzipFile(filename='', mode='wb', fileobj=raw_out, compresslevel=6, mtime=0) as fo:
            shutil.copyfileobj(fi, fo, 1 << 20)
        gz = sha(tmp)
        name = f'{gz}.tt.gz'
        tmp.replace(out / name)
        e = {'release_tag': tag, 'asset': name, 'url': f'{REPO_URL}/download/{tag}/{name}', 'gz_sha256': gz,
             'gz_bytes': (out / name).stat().st_size, 'state_sha256': raw, 'state_bytes': s.stat().st_size,
             'carried_search_seconds': sc.state_carried_seconds(s), 'work_path': str(rel), 'note': note,
             'staged': time.strftime('%Y-%m-%d %H:%M:%S'), 'uploaded_verified': False, **describe(WORK / rel)}
        manifest['files'][name] = {'sha256': gz, 'bytes': e['gz_bytes'], 'state_sha256': raw, 'work_path': str(rel),
                                   'carried_search_seconds': e['carried_search_seconds']}
        ix['states'] = [x for x in ix['states'] if not (x['release_tag'] == tag and x['work_path'] == str(rel))] + [e]
        print(rel, f'{e["carried_search_seconds"]:.0f} s in state', f'{e["gz_bytes"] / 1e6:.0f} MB', flush=True)
    manifest['file_count'] = len(manifest['files'])
    manifest['total_bytes'] = sum(f['bytes'] for f in manifest['files'].values())
    (out / 'MANIFEST.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    save_index(ix)
    print(json.dumps({'tag': tag, 'files': manifest['file_count'], 'bytes': manifest['total_bytes']}))


def fetch(url, dst):
    r = subprocess.run(['curl', '-sSL', '--fail', '-o', str(dst), url], capture_output=True, text=True)
    return r.returncode == 0 and dst.exists()


def unpacked_sha(gzpath):
    h = hashlib.sha256()
    with gzip.open(gzpath, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def check(tag):
    ix = load_index()
    ok = bad = 0
    stamp = time.strftime('%Y-%m-%d %H:%M:%S')
    with tempfile.TemporaryDirectory() as tmp:
        for e in ix['states']:
            if e['release_tag'] != tag:
                continue
            f = Path(tmp) / 'x.gz'
            good = fetch(e['url'], f) and sha(f) == e['gz_sha256'] and unpacked_sha(f) == e['state_sha256']
            e['uploaded_verified'] = stamp if good else False
            ok += good
            bad += not good
            if not good:
                print('다름 또는 내려받기 실패:', e['url'], flush=True)
            f.unlink(missing_ok=True)
    save_index(ix)
    print(json.dumps({'tag': tag, 'downloaded_with_recorded_hash': ok, 'failed': bad}))
    return bad == 0 and ok > 0


def restore(work, tags):
    ix = load_index()
    done, same, conflict, failed = [], [], [], []
    for e in ix['states']:
        if tags and e['release_tag'] not in tags:
            continue
        dst = Path(work) / e['work_path']
        if dst.exists():
            (same if sha(dst) == e['state_sha256'] else conflict).append(e['work_path'])
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=dst.parent) as tmp:
            f = Path(tmp) / 'x.gz'
            if not (fetch(e['url'], f) and sha(f) == e['gz_sha256']):
                failed.append(e['work_path'])
                continue
            part = Path(tmp) / 'state.tt'
            with gzip.open(f, 'rb') as fi, open(part, 'wb') as fo:
                shutil.copyfileobj(fi, fo, 1 << 20)
            if sha(part) != e['state_sha256']:
                failed.append(e['work_path'])
                continue
            os.replace(part, dst)
            done.append(e['work_path'])
    print(json.dumps({'restored': done, 'already_there': len(same), 'different_file_there_not_touched': conflict,
                      'failed': failed}, ensure_ascii=False))
    return not failed


def main():
    cmd = sys.argv[1]
    if cmd == 'stage':
        stage(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5:])
    elif cmd == 'check':
        sys.exit(0 if check(sys.argv[2]) else 1)
    elif cmd == 'restore':
        sys.exit(0 if restore(sys.argv[2], set(sys.argv[3:])) else 1)
    else:
        sys.exit(__doc__)


if __name__ == '__main__':
    main()
