#!/usr/bin/env python3
"""Pack the per-position records of a large stage into one file that goes into the repository.

usage: pack_records.py STAGE      (results/STAGE/res/*.json -> results/STAGE/records.jsonl.gz)

The stages winner_w / winner_l have tens of thousands of positions, too many small files for the repository.
Their pos/, in/, res/ and log/ folders stay in the work folder; the repository gets records.jsonl.gz:
one line per position, the full res JSON (solver JSON, verifier JSON, the eight acceptance checks, hashes).
Before packing, every position file and solver input is rebuilt from the record alone and must have the
recorded SHA-256:  position file = json.dumps({"initial_syllable", "history"}, ensure_ascii=False) in UTF-8,
input = ModelV3.numeric_input(ModelV3.position(position)).  So the packed file is enough to rerun verify_v4.
"""
import gzip
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parent
sys.path.insert(0, str(REPO / 'guopsaem_root' / 'verifier_v3'))
from verify_v3 import ModelV3  # noqa: E402


def main():
    stage = sys.argv[1]
    base = HERE / 'results' / stage
    m = ModelV3((HERE / 'words_621.txt').read_bytes(), 621)
    files = sorted((base / 'res').glob('*.json'))
    out = base / 'records.jsonl.gz'
    n = bad = 0
    with gzip.open(out, 'wt', encoding='utf-8', compresslevel=9) as f:
        for p in files:
            r = json.loads(p.read_text(encoding='utf-8'))
            pos_bytes = json.dumps(r['position'], ensure_ascii=False).encode('utf-8')
            cur, counts, _ = m.position(r['position'])
            ok = (hashlib.sha256(pos_bytes).hexdigest() == r['position_sha256'] ==
                  hashlib.sha256((base / 'pos' / f"{r['id']}.json").read_bytes()).hexdigest()
                  and hashlib.sha256(m.numeric_input(cur, counts)).hexdigest() == r['input_sha256'])
            bad += not ok
            f.write(json.dumps(r, ensure_ascii=False, separators=(',', ':')) + '\n')
            n += 1
    print(stage, n, 'records ->', out, out.stat().st_size, 'bytes; rebuild mismatches:', bad)
    if bad:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
