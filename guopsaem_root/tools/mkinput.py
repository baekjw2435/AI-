#!/usr/bin/env python3
"""Numeric solver_v4 input for a position: mkinput.py DICT WORD_COUNT POS.json OUT.txt"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'verifier_v3'))
from verify_v3 import ModelV3
d, n, pos, out = sys.argv[1:5]
m = ModelV3(open(d, 'rb').read(), int(n))
cur, counts, _ = m.position(json.load(open(pos, encoding='utf-8')))
open(out, 'wb').write(m.numeric_input(cur, counts))
