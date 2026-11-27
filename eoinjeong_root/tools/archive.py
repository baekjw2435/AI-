#!/usr/bin/env python3
"""Put the accepted certificates of the 어인정 621-word study outside the repository and check them again.

usage:
  archive.py stage TAG             copy every accepted certificate of results/{roots,first,second} to
                                   release_staging/TAG/<sha256>.v4.gz (one file per distinct certificate) and
                                   write release_staging/TAG/MANIFEST.json and results/archive_index.json
  archive.py check TAG [JOBS]      download every file of MANIFEST.json from the release TAG, compare its
                                   SHA-256, then run verify_v4 again on the DOWNLOADED copy for every position
                                   that uses it (all acceptance conditions of solve_common.verify);
                                   writes results/archive_check.json
  archive.py stage_many PREFIX STAGE...   large stages (winner_w, winner_l): new certificates only, 900 per tag
                                   (PREFIX-01, PREFIX-02, ...), index results/archive_index_<STAGE>.json.gz
  archive.py check_many STAGE...   download every certificate those stages use, compare SHA-256, re-verify
                                   every position from the downloaded copy; results/archive_check_<STAGES>.json
Saved search states: every position was decided and its state deleted after acceptance, so there is no
state to keep (checked: no results/*/tt/*.tt file). If one is left, stage refuses to run.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parent
sys.path.insert(0, str(REPO / 'guopsaem_root' / 'tools'))
import solve_common as sc  # noqa: E402

STAGES = ('roots', 'first', 'second')
URL = 'https://github.com/baekjw2435/AI-/releases/download/{tag}/{name}'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def records():
    for st in STAGES:
        for f in sorted((HERE / 'results' / st / 'res').glob('*.json')):
            yield st, json.loads(f.read_text(encoding='utf-8'))


def stage(tag):
    left = [str(p) for st in STAGES for p in (HERE / 'results' / st / 'tt').glob('*.tt')]
    assert not left, f'saved states left, archive them first: {left[:3]}'
    out = HERE / 'release_staging' / tag
    out.mkdir(parents=True, exist_ok=True)
    files, index = {}, {}
    for st, r in records():
        if not r.get('accepted'):
            continue
        proof = HERE / 'results' / st / 'proof' / f"{r['id']}.v4.gz"
        h = sha(proof)
        assert h == r['proof_sha256'] == r['verify']['proof_sha256'], r['id']
        name = f'{h}.v4.gz'
        if name not in files:
            shutil.copyfile(proof, out / name)
            files[name] = {'sha256': h, 'bytes': proof.stat().st_size, 'positions': []}
        files[name]['positions'].append(r['id'])
        index[r['id']] = {'stage': st, 'position': r['position'], 'result_for_player_to_move': r['result_for_player_to_move'],
                          'proof_sha256': h, 'release_tag': tag, 'url': URL.format(tag=tag, name=name)}
    man = {'release_tag': tag, 'dictionary': 'eoinjeong_root/words_621.txt',
           'dictionary_sha256': sha(HERE / 'words_621.txt'), 'files': files,
           'total_bytes': sum(e['bytes'] for e in files.values())}
    (out / 'MANIFEST.json').write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding='utf-8')
    (HERE / 'results' / 'archive_index.json').write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding='utf-8')
    print(tag, len(files), 'files', man['total_bytes'], 'bytes for', len(index), 'positions')


def check(tag, jobs=4):
    man = json.loads((HERE / 'release_staging' / tag / 'MANIFEST.json').read_text(encoding='utf-8'))
    dl = HERE / 'results' / 'archive_download' / tag
    dl.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    def fetch(name):
        dest = dl / name
        err = ''
        for attempt in range(4):
            r = subprocess.run(['curl', '-sSL', '--fail', '-o', str(dest), URL.format(tag=tag, name=name)],
                               capture_output=True, text=True)
            if r.returncode == 0:
                return name, sha(dest)
            err = r.stderr[-200:]
            time.sleep(2 ** attempt)
        return name, 'download failed: ' + err

    with ThreadPoolExecutor(8) as ex:
        got = dict(ex.map(fetch, sorted(man['files'])))
    t1 = time.time()
    differ = [n for n, e in man['files'].items() if got.get(n) != e['sha256']]
    where = {}
    for st, r in records():
        if r.get('accepted'):
            where[r['id']] = (st, r)

    def reverify(pid):
        st, r = where[pid]
        name = f"{r['proof_sha256']}.v4.gz"
        base = HERE / 'results' / st
        ok, vr = sc.verify(HERE / 'words_621.txt', 621, base / 'pos' / f'{pid}.json', dl / name,
                           base / 'in' / f'{pid}.txt', r['result_for_player_to_move'], r['solver'].get('proof_nodes', 0))
        return pid, ok, vr.get('elapsed_seconds')

    pids = [p for e in man['files'].values() for p in e['positions'] if got.get(f"{e['sha256']}.v4.gz") == e['sha256']]
    with ThreadPoolExecutor(jobs) as ex:
        rv = list(ex.map(reverify, pids))
    t2 = time.time()
    failed = [p for p, ok, _ in rv if not ok]
    rep = {'release_tag': tag, 'checked_at': time.strftime('%Y-%m-%d %H:%M:%S %Z'),
           'files_in_manifest': len(man['files']), 'files_downloaded_same_sha256': len(man['files']) - len(differ),
           'files_differ_or_missing': differ, 'positions_reverified_from_download': len(rv),
           'positions_reverify_failed': failed, 'download_wall_seconds': round(t1 - t0, 1),
           'reverify_wall_seconds': round(t2 - t1, 1),
           'reverify_verifier_seconds_sum': round(sum(e or 0 for _, _, e in rv), 1)}
    (HERE / 'results' / 'archive_check.json').write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(rep, ensure_ascii=False, indent=1))


PER_TAG = 900   # a GitHub release holds at most 1,000 files


def staged_files():
    """sha256 -> tag of every certificate already staged (and uploaded) under release_staging/."""
    where = {}
    for man in sorted((HERE / 'release_staging').glob('*/MANIFEST.json')):
        m = json.loads(man.read_text(encoding='utf-8'))
        for e in m['files'].values():
            where.setdefault(e['sha256'], m['release_tag'])
    return where


def stage_many(prefix, stages):
    """Large stages: certificates not yet in any release go to release_staging/PREFIX-01, -02, ... (900 each);
    a certificate already staged under another tag is not copied again, the index points to that tag.
    Writes results/archive_index_<stage>.json.gz (id -> sha256, tag, url)."""
    import gzip
    left = [str(p) for st in stages for p in (HERE / 'results' / st / 'tt').glob('*.tt')]
    assert not left, f'saved states left, archive them first: {left[:3]}'
    old = staged_files()
    new, index = {}, {st: {} for st in stages}
    for st in stages:
        for f in sorted((HERE / 'results' / st / 'res').glob('*.json')):
            r = json.loads(f.read_text(encoding='utf-8'))
            if not r.get('accepted'):
                continue
            proof = HERE / 'results' / st / 'proof' / f"{r['id']}.v4.gz"
            h = sha(proof)
            assert h == r['proof_sha256'] == r['verify']['proof_sha256'], r['id']
            if h not in old:
                e = new.setdefault(h, {'sha256': h, 'bytes': proof.stat().st_size, 'positions': [], 'src': proof})
                e['positions'].append(r['id'])
            index[st][r['id']] = h
    names = sorted(new)
    tags = {}
    for k in range(0, len(names), PER_TAG):
        tag = f'{prefix}-{k // PER_TAG + 1:02d}'
        out = HERE / 'release_staging' / tag
        out.mkdir(parents=True, exist_ok=True)
        files = {}
        for h in names[k:k + PER_TAG]:
            e = new[h]
            shutil.copyfile(e['src'], out / f'{h}.v4.gz')
            files[f'{h}.v4.gz'] = {'sha256': h, 'bytes': e['bytes'], 'positions': e['positions']}
            tags[h] = tag
        man = {'release_tag': tag, 'dictionary': 'eoinjeong_root/words_621.txt',
               'dictionary_sha256': sha(HERE / 'words_621.txt'), 'files': files,
               'total_bytes': sum(e['bytes'] for e in files.values())}
        (out / 'MANIFEST.json').write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding='utf-8')
        print(tag, len(files), 'files', man['total_bytes'], 'bytes')
    for st in stages:
        idx = {pid: {'proof_sha256': h, 'release_tag': old.get(h) or tags[h],
                     'url': URL.format(tag=old.get(h) or tags[h], name=f'{h}.v4.gz')} for pid, h in index[st].items()}
        with gzip.open(HERE / 'results' / f'archive_index_{st}.json.gz', 'wt', encoding='utf-8') as f:
            json.dump(idx, f, ensure_ascii=False, separators=(',', ':'))
        print(st, len(idx), 'positions;', sum(1 for h in index[st].values() if h in old), 'use a file of an earlier tag')
    print('new files', len(names), 'tags', sorted(set(tags.values())))


def check_many(stages, jobs=4):
    """Download every certificate the given stages use (from whichever tag holds it), compare SHA-256, and run
    verify_v4 again on the downloaded copy for every position.  Writes results/archive_check_<stages>.json."""
    import gzip
    idx = {}
    for st in stages:
        with gzip.open(HERE / 'results' / f'archive_index_{st}.json.gz', 'rt', encoding='utf-8') as f:
            for pid, e in json.load(f).items():
                idx[pid] = (st, e)
    need = {e['url']: e['proof_sha256'] for _, e in idx.values()}
    dl = HERE / 'results' / 'archive_download' / 'many'
    dl.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    def fetch(url):
        dest = dl / url.rsplit('/', 1)[1]
        err = ''
        for attempt in range(4):
            r = subprocess.run(['curl', '-sSL', '--fail', '-o', str(dest), url], capture_output=True, text=True)
            if r.returncode == 0:
                return url, sha(dest)
            err = r.stderr[-200:]
            time.sleep(2 ** attempt)
        return url, 'download failed: ' + err

    with ThreadPoolExecutor(8) as ex:
        got = dict(ex.map(fetch, sorted(need)))
    t1 = time.time()
    differ = [u for u, h in need.items() if got.get(u) != h]

    def reverify(pid):
        st, e = idx[pid]
        base = HERE / 'results' / st
        r = json.loads((base / 'res' / f'{pid}.json').read_text(encoding='utf-8'))
        ok, vr = sc.verify(HERE / 'words_621.txt', 621, base / 'pos' / f'{pid}.json', dl / f"{e['proof_sha256']}.v4.gz",
                           base / 'in' / f'{pid}.txt', r['result_for_player_to_move'], r['solver'].get('proof_nodes', 0))
        return pid, ok, vr.get('elapsed_seconds')

    pids = sorted(p for p, (_, e) in idx.items() if got.get(e['url']) == e['proof_sha256'])
    with ThreadPoolExecutor(jobs) as ex:
        rv = list(ex.map(reverify, pids))
    t2 = time.time()
    rep = {'stages': list(stages), 'checked_at': time.strftime('%Y-%m-%d %H:%M:%S %Z'),
           'tags': sorted({u.split('/download/')[1].split('/')[0] for u in need}),
           'files_needed': len(need), 'files_downloaded_same_sha256': len(need) - len(differ),
           'files_differ_or_missing': differ, 'positions': len(idx), 'positions_reverified_from_download': len(rv),
           'positions_reverify_failed': [p for p, ok, _ in rv if not ok],
           'download_wall_seconds': round(t1 - t0, 1), 'reverify_wall_seconds': round(t2 - t1, 1),
           'reverify_verifier_seconds_sum': round(sum(x or 0 for _, _, x in rv), 1)}
    (HERE / 'results' / f"archive_check_{'_'.join(stages)}.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(rep, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    if sys.argv[1] == 'stage':
        stage(sys.argv[2])
    elif sys.argv[1] == 'check':
        check(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 4)
    elif sys.argv[1] == 'stage_many':
        stage_many(sys.argv[2], sys.argv[3:])
    elif sys.argv[1] == 'check_many':
        check_many(sys.argv[2:])
    else:
        raise SystemExit(__doc__)
