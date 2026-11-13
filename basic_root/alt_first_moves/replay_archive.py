#!/usr/bin/env python3
"""Keep the accepted certificates of a replay experiment, with everything needed to check them.

usage: replay_archive.py NAME [WORKDIR ...] [--jobs 3] [--recheck 0]
                         [--release TAG --staging DIR] [--sources SRCDIR] [--check-release 0]

For every decided case of results/NAME/*.phase1.json, in the repository:
  results/NAME/archive/<case>/pos.json        the position
  results/NAME/archive/<case>/in.txt          the numeric solver input
  results/NAME/archive/<case>/verify.json     the full output of verify_v4 run on the KEPT file, plus the
                                              acceptance conditions of solve_common.verify
  results/NAME/archive/INDEX.json             case -> certificate, sizes, verdict, hashes, where the file is
The certificate file itself, named by its SHA-256 (the same file can serve several positions: a v4 certificate
lists moves only, so it is kept once):
  without --release   results/NAME/archive/certs/<sha256>.v4.gz          (in the repository; experiments 1 and 2)
  with --release TAG  DIR/TAG/<sha256>.v4.gz, to be attached to the GitHub release TAG. The repository then
                      holds only position, input, verification record, hash and download address
                      (https://github.com/<owner>/<repo>/releases/download/TAG/<sha256>.v4.gz), and
                      DIR/TAG/MANIFEST.json lists every file of the release with its hash.
  --sources SRCDIR    (with --release) also the source certificates of SRCDIR (replay_prep.py) that are not yet in
                      the repository: prep.json, position, input and run log go to results/NAME/sources/<syllable>/,
                      the certificate to DIR/TAG/.
With WORKDIR arguments the files are copied from WORKDIR/<case>/ (as replay_test.py left them) and their hashes
are compared with the case records first. Without WORKDIR nothing is copied: what is kept is only checked.
A case is done when its verify.json says accepted for the certificate hash in the record; re-running skips it
unless --recheck 1 is given.
  --check-release 1   after the files were attached to the release: download every address of INDEX.json again,
                      compare the SHA-256 and write the result into INDEX.json (uploaded_verified).
Exit code 0 only if every decided case is kept and accepted (and, with --check-release, every download matches).
"""
from concurrent.futures import ThreadPoolExecutor
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
BASIC = HERE.parent
os.environ.setdefault('BIG_PROOF_NODES', str(10**12))     # no shared verification lock: --jobs bounds the load
sys.path.insert(0, str(BASIC.parent / 'guopsaem_root' / 'tools'))
import solve_common as sc  # noqa: E402

DICT = BASIC / 'words_817.txt'
REPO = os.environ.get('GITHUB_REPO', 'baekjw2435/AI-')


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def url_of(tag, asset):
    return f'https://github.com/{REPO}/releases/download/{tag}/{asset}'


def place(src, dst):
    """Copy src to dst unless dst is already that file."""
    if not dst.exists():
        shutil.copyfile(src, str(dst) + '.part')
        os.replace(str(dst) + '.part', dst)


def check_release(arc):
    """Download every release address of INDEX.json and compare hashes."""
    index = json.loads((arc / 'INDEX.json').read_text(encoding='utf-8'))
    items = {}
    for e in index['cases'] + index.get('sources', []):
        if e.get('store') == 'release':
            items[e['url']] = e['proof_sha256']
    ok = bad = 0
    results = {}
    with tempfile.TemporaryDirectory() as tmp:
        for i, (url, want) in enumerate(sorted(items.items())):
            f = Path(tmp) / f'{i}.bin'
            r = subprocess.run(['curl', '-sSL', '--fail', '-o', str(f), url], capture_output=True, text=True)
            got = sha(f) if r.returncode == 0 and f.exists() else None
            results[url] = got == want
            ok += got == want
            bad += got != want
            if got != want:
                print('다름 또는 내려받기 실패:', url, (r.stderr or '').strip()[-150:], flush=True)
            if f.exists():
                f.unlink()
    stamp = time.strftime('%Y-%m-%d %H:%M:%S')
    for e in index['cases'] + index.get('sources', []):
        if e.get('store') == 'release':
            e['uploaded_verified'] = stamp if results.get(e['url']) else False
    index['release']['status'] = 'uploaded, every file downloaded again and its SHA-256 compared' if bad == 0 and ok else \
        'not all files could be downloaded with the recorded hash'
    index['release']['checked'] = stamp
    (arc / 'INDEX.json').write_text(json.dumps(index, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(json.dumps({'release_files': len(items), 'downloaded_with_recorded_hash': ok, 'failed': bad}, ensure_ascii=False))
    return bad == 0 and ok > 0


def main():
    args = sys.argv[1:]
    opt = {'--jobs': '3', '--recheck': '0', '--release': '', '--staging': '', '--sources': '', '--check-release': '0'}
    while len(args) >= 2 and args[-2] in opt:
        opt[args[-2]] = args[-1]
        args = args[:-2]
    name, works = args[0], [Path(w) for w in args[1:]]
    res = HERE / 'results' / name
    arc = res / 'archive'
    if int(opt['--check-release']):
        sys.exit(0 if check_release(arc) else 1)
    tag = opt['--release']
    store = Path(opt['--staging']) / tag if tag else arc / 'certs'
    store.mkdir(parents=True, exist_ok=True)
    recs = [json.loads(p.read_text(encoding='utf-8')) for p in sorted(res.glob('*.phase1.json'))]
    todo = [r for r in recs if r['decided']]

    def where(want_sha):
        if tag:
            asset = f'{want_sha}.v4.gz'
            return {'store': 'release', 'release_tag': tag, 'asset': asset, 'url': url_of(tag, asset), 'uploaded_verified': False}
        return {'store': 'repository', 'certificate': f'certs/{want_sha}.v4.gz'}

    def one(r):
        case, want_sha = r['name'], r['verify']['proof_sha256']
        d = arc / case
        d.mkdir(parents=True, exist_ok=True)
        cert = store / f'{want_sha}.v4.gz'
        for w in works:
            src = w / case
            if not (src / 'result.json').exists():
                continue
            f = src / f'{r["method"]}.v4.gz'
            assert sha(f) == want_sha, f'{case}: {f} does not have the recorded hash'
            assert sha(src / 'pos.json') == r['position_sha256'] and sha(src / 'in.txt') == r['input_sha256'], f'{case}: position/input differ'
            place(f, cert)
            shutil.copyfile(src / 'pos.json', d / 'pos.json')
            shutil.copyfile(src / 'in.txt', d / 'in.txt')
        entry = {'case': case, 'id': r['id'], 'first_move': r['first_move'], 'method': r['method'], **where(want_sha),
                 'proof_sha256': want_sha, 'position_sha256': r['position_sha256'], 'input_sha256': r['input_sha256'],
                 'proof_nodes': r['proof_nodes'], 'archived': False, 'accepted': False}
        if not (cert.exists() and (d / 'pos.json').exists() and (d / 'in.txt').exists()):
            vf = d / 'verify.json'
            if tag and vf.exists() and (d / 'pos.json').exists():
                v = json.loads(vf.read_text(encoding='utf-8'))      # verified earlier; the file now lives in the release only
                if v.get('accepted') and v.get('proof_sha256') == want_sha:
                    entry.update(archived=True, accepted=True, verify_seconds=v.get('elapsed_seconds'), checked=v.get('checked'),
                                 proof_bytes=v.get('proof_bytes'))
                    return entry
            entry['problem'] = 'files missing'
            return entry
        entry['archived'] = True
        entry['proof_bytes'] = cert.stat().st_size
        vf = d / 'verify.json'
        if vf.exists() and not int(opt['--recheck']):
            v = json.loads(vf.read_text(encoding='utf-8'))
            if v.get('accepted') and v.get('proof_sha256') == want_sha:
                entry.update(accepted=True, verify_seconds=v.get('elapsed_seconds'), checked=v.get('checked'))
                return entry
        want = 'W' if r['first_move'] == 'lose' else 'L'
        ok, v = sc.verify(DICT, 817, d / 'pos.json', cert, d / 'in.txt', want, r['proof_nodes'])
        ok = bool(ok) and v.get('proof_sha256') == want_sha and v.get('position_sha256') == r['position_sha256'] \
            and v.get('input_sha256') == r['input_sha256']
        v['accepted'] = ok
        v['checked'] = time.strftime('%Y-%m-%d %H:%M:%S')
        v['verifier_sha256'] = sha(sc.VERIFY_V4)
        v['proof_bytes'] = cert.stat().st_size
        vf.write_text(json.dumps(v, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
        entry.update(accepted=ok, verify_seconds=v.get('elapsed_seconds'), checked=v['checked'])
        print(time.strftime('%H:%M:%S'), case, r['id'], '수락' if ok else f'거부: {v.get("error") or v.get("acceptance")}', flush=True)
        return entry

    with ThreadPoolExecutor(int(opt['--jobs'])) as ex:
        entries = list(ex.map(one, todo))
    # ---- source certificates that are not in the repository yet
    sources = []
    if tag and opt['--sources']:
        known = {json.loads(p.read_text(encoding='utf-8'))['proof_sha256'] for p in (HERE / 'results').glob('*/sources/*/prep.json')
                 if (p.parent / 'proof.v4.gz').exists()}
        for sd in sorted(p for p in Path(opt['--sources']).iterdir() if (p / 'prep.json').exists()):
            prep = json.loads((sd / 'prep.json').read_text(encoding='utf-8'))
            h = prep['proof_sha256']
            if h in known:
                continue
            assert sha(sd / 'proof.v4.gz') == h, f'source {sd.name}: certificate differs from prep.json'
            place(sd / 'proof.v4.gz', store / f'{h}.v4.gz')
            dst = res / 'sources' / sd.name
            dst.mkdir(parents=True, exist_ok=True)
            for f in ('prep.json', 'pos.json', 'in.txt', 'runs.jsonl'):
                shutil.copyfile(sd / f, dst / f)
            sources.append({'syllable': sd.name, 'result_for_receiver': prep['result_for_receiver'], 'proof_nodes': prep['proof_nodes'],
                            'proof_bytes': prep['proof_bytes'], 'proof_sha256': h, 'position_sha256': prep['position_sha256'],
                            'input_sha256': prep['input_sha256'], 'accepted': all(prep['acceptance'].values()), **where(h)})
    used = {e['proof_sha256'] for e in entries if e['archived']} | {s['proof_sha256'] for s in sources}
    index = {'format': 'replay-archive-2', 'experiment': name, 'dictionary_sha256': sha(DICT),
             'decided_cases': len(todo), 'archived': sum(e['archived'] for e in entries), 'accepted': sum(e['accepted'] for e in entries),
             'certificate_files': len(used),
             'certificate_bytes': sum((store / f'{h}.v4.gz').stat().st_size for h in used if (store / f'{h}.v4.gz').exists()),
             'cases': entries}
    if sources:
        index['sources'] = sources
    if tag:
        old = json.loads((arc / 'INDEX.json').read_text(encoding='utf-8')) if (arc / 'INDEX.json').exists() else {}
        index['release'] = old.get('release') or {'tag': tag, 'url': f'https://github.com/{REPO}/releases/tag/{tag}',
                                                  'status': 'staged: the files are not attached to the release yet'}
        # manifest of the release folder: every file there, with what it certifies
        what = {}
        for e in entries:
            what.setdefault(e['proof_sha256'], []).append(f'{name}/{e["case"]} {e["id"]}')
        for s in sources:
            what.setdefault(s['proof_sha256'], []).append(f'{name}/source {s["syllable"]}')
        man_path = store / 'MANIFEST.json'
        man = json.loads(man_path.read_text(encoding='utf-8')) if man_path.exists() else {'release_tag': tag, 'files': {}}
        for h, uses in what.items():
            f = store / f'{h}.v4.gz'
            if f.exists():
                item = man['files'].setdefault(f.name, {'sha256': h, 'bytes': f.stat().st_size, 'certifies': []})
                item['certifies'] = sorted(set(item['certifies']) | set(uses))
        man['file_count'] = len(man['files'])
        man['total_bytes'] = sum(x['bytes'] for x in man['files'].values())
        man_path.write_text(json.dumps(man, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    (arc / 'INDEX.json').write_text(json.dumps(index, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    extra = [] if tag else sorted(p.name for p in store.iterdir() if p.name.split('.')[0] not in used)
    print(json.dumps({k: index[k] for k in ('decided_cases', 'archived', 'accepted', 'certificate_files', 'certificate_bytes')}
                     | {'sources': len(sources), 'unreferenced_files': extra}, ensure_ascii=False))
    sys.exit(0 if index['accepted'] == len(todo) and not extra else 1)


if __name__ == '__main__':
    main()
