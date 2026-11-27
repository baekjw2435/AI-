#!/usr/bin/env python3
"""앞말잇기 루트 국면 목록(뒤집은 534단어 사전 기준).

usage: build_plan.py roots OUT.jsonl     음절 줄 113개, 빈 수순(ids R001..)  — eoinjeong_root/tools/build_plan.py roots와 같음
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]


def main():
    kind, out = sys.argv[1], Path(sys.argv[2])
    syls = (HERE / 'syllables_113.txt').read_text(encoding='utf-8').split()
    if kind != 'roots':
        raise SystemExit(__doc__)
    rows = [{'id': f'R{i:03d}', 'initial_syllable': s, 'history': []} for i, s in enumerate(syls, 1)]
    out.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')
    print(kind, len(rows), 'positions ->', out)


if __name__ == '__main__':
    main()
