#!/usr/bin/env python3
"""Keep the accepted certificates of a replay experiment in the repository, with everything needed to check them.

usage: replay_archive.py NAME [WORKDIR ...] [--jobs 3]

For every decided case of results/NAME/*.phase1.json:
  results/NAME/archive/certs/<sha256>.v4.gz   the accepted certificate, named by its SHA-256 (the hash in the
                                              case record). The same file can serve several positions: a v4
                                              certificate lists moves only, so it is stored once.
  results/NAME/archive/<case>/pos.json        the position
  results/NAME/archive/<case>/in.txt          the numeric solver input
  results/NAME/archive/<case>/verify.json     the full output of verify_v4 run on the ARCHIVED file, plus the
                                              acceptance conditions of solve_common.verify
  results/NAME/archive/INDEX.json             case -> certificate, sizes, verdict, hashes
With WORKDIR arguments the files are copied from WORKDIR/<case>/ (as replay_test.py left them) and their hashes
are compared with the case records first. Without WORKDIR nothing is copied: the archive is only checked.
A case is done when its verify.json says accepted for the certificate hash in the record; re-running skips it
unless --recheck 1 is given. Exit code 0 only if every decided case is archived and accepted.
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time

HERE = Path(__file__).resolve().parent
BASIC = HERE.parent
os.environ.setdefault('BIG_PROOF_NODES', str(10**12))     # no shared verification lock: --jobs bounds the load
sys.path.insert(0, str(BASIC.parent / 'guopsaem_root' / 'tools'))
import solve_common as sc  # noqa: E402

DICT = BASIC / 'words_817.txt'


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    args = sys.argv[1:]
    opt = {'--jobs': 3, '--recheck': 0}
    while len(args) >= 2 and args[-2] in opt:
        opt[args[-2]] = int(args[-1])
        args = args[:-2]
    name, works = args[0], [Path(w) for w in args[1:]]
    res = HERE / 'results' / name
    arc = res / 'archive'
    (arc / 'certs').mkdir(parents=True, exist_ok=True)
    recs = [json.loads(p.read_text(encoding='utf-8')) for p in sorted(res.glob('*.phase1.json'))]
    todo = [r for r in recs if r['decided']]

    def one(r):
        case, want_sha = r['name'], r['verify']['proof_sha256']
        d = arc / case
        d.mkdir(exist_ok=True)
        cert = arc / 'certs' / f'{want_sha}.v4.gz'
        for w in works:
            src = w / case
            if not (src / 'result.json').exists():
                continue
            f = src / f'{r["method"]}.v4.gz'
            assert sha(f) == want_sha, f'{case}: {f} does not have the recorded hash'
            assert sha(src / 'pos.json') == r['position_sha256'] and sha(src / 'in.txt') == r['input_sha256'], f'{case}: position/input differ'
            if not cert.exists():
                shutil.copyfile(f, str(cert) + '.part')
                os.replace(str(cert) + '.part', cert)
            shutil.copyfile(src / 'pos.json', d / 'pos.json')
            shutil.copyfile(src / 'in.txt', d / 'in.txt')
        entry = {'case': case, 'id': r['id'], 'first_move': r['first_move'], 'method': r['method'], 'certificate': f'certs/{cert.name}',
                 'proof_sha256': want_sha, 'position_sha256': r['position_sha256'], 'input_sha256': r['input_sha256'],
                 'proof_nodes': r['proof_nodes'], 'archived': False, 'accepted': False}
        if not (cert.exists() and (d / 'pos.json').exists() and (d / 'in.txt').exists()):
            entry['problem'] = 'files missing'
            return entry
        entry['archived'] = True
        entry['proof_bytes'] = cert.stat().st_size
        vf = d / 'verify.json'
        if vf.exists() and not opt['--recheck']:
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
        vf.write_text(json.dumps(v, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
        entry.update(accepted=ok, verify_seconds=v.get('elapsed_seconds'), checked=v['checked'])
        print(time.strftime('%H:%M:%S'), case, r['id'], '수락' if ok else f'거부: {v.get("error") or v.get("acceptance")}', flush=True)
        return entry

    with ThreadPoolExecutor(opt['--jobs']) as ex:
        entries = list(ex.map(one, todo))
    files = sorted({e['certificate'] for e in entries if e['archived']})
    index = {'format': 'replay-archive-1', 'experiment': name, 'dictionary_sha256': sha(DICT),
             'decided_cases': len(todo), 'archived': sum(e['archived'] for e in entries), 'accepted': sum(e['accepted'] for e in entries),
             'certificate_files': len(files), 'certificate_bytes': sum((arc / f).stat().st_size for f in files), 'cases': entries}
    (arc / 'INDEX.json').write_text(json.dumps(index, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    extra = sorted(p.name for p in (arc / 'certs').iterdir() if f'certs/{p.name}' not in files)
    print(json.dumps({k: index[k] for k in ('decided_cases', 'archived', 'accepted', 'certificate_files', 'certificate_bytes')}
                     | {'unreferenced_files': extra}, ensure_ascii=False))
    sys.exit(0 if index['accepted'] == len(todo) and not extra else 1)


if __name__ == '__main__':
    main()
