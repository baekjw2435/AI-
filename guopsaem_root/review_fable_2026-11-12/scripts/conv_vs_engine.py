#!/usr/bin/env python3
"""Compare the verifier's initial-sound table (verify_v3.conv) with the bot engine's (route_engine.dueum)
on all 11,172 precomposed syllables.   usage: conv_vs_engine.py REPO"""
import importlib.util
import sys
from pathlib import Path

REPO = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location('v3', REPO / 'guopsaem_root/verifier_v3/verify_v3.py')
v3 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v3)
src = (REPO / 'route_engine.py').read_text(encoding='utf-8')
ns = {}
exec(src[src.index('# 표준두음법칙'):src.index('def dueum_variants')], ns)   # only the table, not the bot
diff = 0
for o in range(11172):
    ch = chr(0xAC00 + o)
    a = ns['dueum'](ch)
    a = a if a != ch else None
    if a != v3.conv(ch):
        diff += 1
        print('DIFF', ch, a, v3.conv(ch))
print('differences over 11172 syllables:', diff)
