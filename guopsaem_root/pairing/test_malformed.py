#!/usr/bin/env python3
"""Malformed pairing certificates must be refused cleanly (verified False, exit 1), never crash."""
import hashlib, json, subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'verifier_v3'))
from verify_v3 import ModelV3
words = ['라고나', '나라', '락낙', '낙라']
with tempfile.TemporaryDirectory() as d:
    d = Path(d)
    (d / 'dict.txt').write_text('\n'.join(words) + '\n', encoding='utf-8')
    (d / 'pos.json').write_text(json.dumps({'initial_syllable': '라', 'history': []}, ensure_ascii=False), encoding='utf-8')
    M = ModelV3((d / 'dict.txt').read_bytes(), 0)
    NAME = M.names[M.vertex_of('라')]
    print('current vertex name:', NAME)
    base = {'format': 'pairing-proof-v1', 'claim': 'player_to_move_loses', 'mode': 'raw',
            'dictionary_sha256': hashlib.sha256((d / 'dict.txt').read_bytes()).hexdigest(),
            'position_sha256': hashlib.sha256((d / 'pos.json').read_bytes()).hexdigest(), 'S': [NAME], 'pairs': []}
    bad = [{'S': [[]]}, {'S': [{}]}, {'S': [1]}, {'S': 'abc'}, {'S': None}, {'pairs': [[[], '나라']]}, {'pairs': [['나라']]},
           {'pairs': 'x'}, {'pairs': [None]}, {'pairs': [['나라', '나라']]}, {'pairs': [['없는말', '나라']]}, {'pairs': [[1, 2]]}, {'pairs': [['나라', '낙라', '락낙']]}, {'mode': []}, {'format': []}, {'claim': {}}, {'dictionary_sha256': []}]
    for patch in bad:
        c = dict(base); c.update(patch)
        (d / 'cert.json').write_text(json.dumps(c, ensure_ascii=False), encoding='utf-8')
        r = subprocess.run([sys.executable, sys.argv[1], '--dictionary', str(d / 'dict.txt'), '--expected-word-count', '0',
                            '--position', str(d / 'pos.json'), '--certificate', str(d / 'cert.json')], capture_output=True, text=True)
        out = json.loads(r.stdout) if r.stdout.strip() else None
        ok = r.returncode == 1 and out is not None and out.get('verified') is False and not r.stderr
        print('ok ' if ok else 'BAD', patch, '->', r.returncode, (out or {}).get('error'), r.stderr[-200:])
    for txt in ['[]', '"x"', '{', '[[]]']:
        (d / 'cert.json').write_text(txt, encoding='utf-8')
        r = subprocess.run([sys.executable, sys.argv[1], '--dictionary', str(d / 'dict.txt'), '--expected-word-count', '0',
                            '--position', str(d / 'pos.json'), '--certificate', str(d / 'cert.json')], capture_output=True, text=True)
        print('ok ' if (r.returncode == 1 and not r.stderr) else 'BAD', repr(txt), '->', r.returncode, r.stdout.strip()[-120:], r.stderr[-200:])
