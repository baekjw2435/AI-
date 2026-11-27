#!/usr/bin/env python3
"""Put the archived source certificates back into a work folder, so a new work environment can go on replaying.

usage: replay_restore_sources.py SRCDIR [--staging DIR] [--download 1]
For every results/*/sources/<syllable>/prep.json it fills SRCDIR/<syllable>/ (prep.json, pos.json, in.txt,
runs.jsonl, proof.v4.gz) in the layout replay_prep.py makes. The certificate is taken from the first place
that has a file with the recorded SHA-256:
  1. results/*/sources/<syllable>/proof.v4.gz      (experiment 1 keeps its sources in the repository)
  2. DIR/<release tag>/<sha256>.v4.gz              (--staging: files waiting to be attached to a release)
  3. the release address of results/*/archive/INDEX.json   (--download 1, default; needs the release to exist)
A syllable whose certificate cannot be found with the recorded hash is NOT restored (replay_prep.py can
prepare it again; that makes a new, equally valid certificate). A folder that is already complete is left alone.
"""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def main():
    out = Path(sys.argv[1])
    rest = sys.argv[2:]
    opt = {'--staging': '', '--download': '1'}
    opt.update({rest[i]: rest[i + 1] for i in range(0, len(rest), 2)})
    where = {}  # sha -> (release tag, url)
    for ip in sorted((HERE / 'results').glob('*/archive/INDEX.json')):
        for e in json.loads(ip.read_text(encoding='utf-8')).get('sources', []):
            if e.get('store') == 'release':
                where[e['proof_sha256']] = (e['release_tag'], e['url'])
    done, kept, missing = [], [], []
    for pp in sorted((HERE / 'results').glob('*/sources/*/prep.json')):
        prep = json.loads(pp.read_text(encoding='utf-8'))
        syl, want = pp.parent.name, prep['proof_sha256']
        d = out / syl
        if (d / 'prep.json').exists() and (d / 'proof.v4.gz').exists() and sha(d / 'proof.v4.gz') == \
                json.loads((d / 'prep.json').read_text(encoding='utf-8'))['proof_sha256']:
            kept.append(syl)
            continue
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / 'proof.v4.gz.restore'
        got = False
        cands = [pp.parent / 'proof.v4.gz']
        if want in where and opt['--staging']:
            cands.append(Path(opt['--staging']) / where[want][0] / f'{want}.v4.gz')
        for c in cands:
            if c.exists() and sha(c) == want:
                shutil.copyfile(c, tmp)
                got = True
                break
        if not got and want in where and int(opt['--download']):
            r = subprocess.run(['curl', '-sSL', '--fail', '-o', str(tmp), where[want][1]], capture_output=True, text=True)
            got = r.returncode == 0 and tmp.exists() and sha(tmp) == want
        if not got:
            if tmp.exists():
                tmp.unlink()
            missing.append(syl)
            continue
        for n in ('pos.json', 'in.txt', 'runs.jsonl'):
            if (pp.parent / n).exists():
                shutil.copyfile(pp.parent / n, d / n)
        tmp.replace(d / 'proof.v4.gz')
        shutil.copyfile(pp, d / 'prep.json')  # last: a folder with prep.json is complete
        done.append(syl)
    print(json.dumps({'restored': len(done), 'already_there': len(kept), 'not_found': missing}, ensure_ascii=False))
    return 0 if not missing else 1


if __name__ == '__main__':
    sys.exit(main())
