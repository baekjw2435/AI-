#!/usr/bin/env python3
"""Download again the certificates of a branch INDEX.json that are not checked yet, and record the check.

usage: check_release_index.py RESULTS_DIR/INDEX.json SCRATCH_DIR
Only confirmed entries with uploaded_verified = null are downloaded (the new files of the last run); each must have
the SHA-256 in its name and in proof_sha256. Entries already checked after an earlier upload are left as they are.
Prints how many files were downloaded, how many differ, and the seconds it took.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def main():
    p, scratch = Path(sys.argv[1]), sys.argv[2]
    d = json.loads(p.read_text(encoding='utf-8'))
    t0 = time.time()
    done, bad, n = {}, 0, 0
    with tempfile.TemporaryDirectory(dir=scratch) as t:
        for c in d['cases']:
            if c.get('status') != 'confirmed' or c.get('uploaded_verified'):
                continue
            if c['asset'] in done:
                c['uploaded_verified'] = done[c['asset']]
                continue
            n += 1
            f = Path(t) / c['asset']
            for _ in range(3):
                if subprocess.run(['curl', '-sSfL', '-o', str(f), c['url']]).returncode == 0:
                    break
                time.sleep(3)
            h = hashlib.sha256(f.read_bytes()).hexdigest() if f.exists() else None
            if h == c['proof_sha256'] == c['asset'].split('.')[0]:
                c['uploaded_verified'] = done[c['asset']] = time.strftime('%Y-%m-%d %H:%M:%S')
            else:
                bad += 1
            f.unlink(missing_ok=True)
    p.write_text(json.dumps(d, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    left = sum(1 for c in d['cases'] if c.get('status') == 'confirmed' and not c.get('uploaded_verified'))
    print(json.dumps({'downloaded': n, 'differ': bad, 'still_unchecked': left, 'seconds': round(time.time() - t0, 1)}))


if __name__ == '__main__':
    main()
