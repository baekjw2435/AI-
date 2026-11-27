#!/usr/bin/env python3
"""The recorded proof_sha256 must be the hash of the bytes that were checked, even if the
path is replaced while the verifier runs (Astra review 1-2, 2026-11-05).
Usage: hash_once_test.py VALID_PROOF OTHER_FILE   (both v3 or v4, gz or plain)"""
import hashlib, os, shutil, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'verifier_v3'))
from verify_v3 import HashedProof  # noqa: E402

valid, other = sys.argv[1], sys.argv[2]
want = hashlib.sha256(Path(valid).read_bytes()).hexdigest()
with tempfile.TemporaryDirectory() as d:
    for text in (False, True):
        p = os.path.join(d, 'proof')
        shutil.copy(valid, p)
        with HashedProof(p, text=text) as hp:
            first = hp.stream.readline()               # parsing has started on the original file
            shutil.copy(other, p + '.new')
            os.replace(p + '.new', p)                  # the path now names a different file
            for _ in hp.stream:
                pass
            got = hp.digest()
        assert got == want, (text, got, want)
        assert hashlib.sha256(Path(p).read_bytes()).hexdigest() != want  # the path really changed
print('ok: digest is of the bytes read, not of the file now at the path')
