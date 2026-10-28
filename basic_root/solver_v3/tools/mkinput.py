#!/usr/bin/env python3
"""mkinput.py DICT POSITION.json OUT.txt : numeric solver input exactly as verify.py expects."""
import json, sys
sys.dont_write_bytecode = True
sys.path.insert(0, '/tmp/claude-0/-home-user-AI-/80ff9426-9f7b-5815-97c0-938f621a9f93/scratchpad/verifier/route-verifier-v2')
from verify import IndependentModel
m = IndependentModel(open(sys.argv[1], 'rb').read())
cur, counts, used = m.position(json.load(open(sys.argv[2], encoding='utf-8')))
lines = [f"{len(m.syllables)} {len(m.edges)} {cur}"] + [f"{s} {t} {c}" for (s, t), c in zip(m.edges, counts)]
open(sys.argv[3], 'w').write('\n'.join(lines) + '\n')
