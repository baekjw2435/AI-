#!/usr/bin/env python3
"""Markdown table and totals of one batch, from results/<BATCH>/ (see run_batch.py, report.py).

usage: batch_table.py BATCH PICKS.json
Per position: cumulative search time over its phases, certificate size, certificate-writing time and
verification time (decided positions only), and the verdict for the receiver's first word.
"""
from collections import defaultdict
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from phase_time import phase_key  # noqa: E402


def main():
    batch, picks_path = sys.argv[1:3]
    picks = {p['name']: p for p in json.loads(Path(picks_path).read_text(encoding='utf-8'))['picks']}
    runs = defaultdict(list)
    for f in sorted((HERE / 'results' / batch).glob('*.phase*.json')):
        r = json.loads(f.read_text(encoding='utf-8'))
        runs[r['name']].append(r)
    form = {'kept': '', 'kept_partly_cancelled': '', 'pair_cancelled': '짝'}
    side = {'tune': '조정용', 'final': '비교용'}
    print('| 번호 | 첫 수 | 용도 | 종류 | 누적 탐색(초) | 탐색 국면 | 결과 | 증명 국면 | 증명 생성(초) | 검증(초) | 상대의 반박 |')
    print('|---|---|---|---|---:|---:|---|---:|---:|---:|---|')
    tot = defaultdict(float)
    rows = []
    for name in sorted(picks):
        p = picks[name]
        rs = sorted(runs.get(name, []), key=lambda r: phase_key(r['phase']))
        if not rs:
            continue
        dec = next((r for r in rs if r.get('decided')), None)
        last = dec or rs[-1]
        search = last['search_seconds_total']
        mids = sum(r.get('mid_calls') or 0 for r in rs)
        partial = any(r.get('mid_calls') is None and (r.get('search_seconds') or 0) > 0 for r in rs)
        mtxt = ('≥' if partial else '') + f'{mids:,}'
        tot['search'] += search
        tot['n'] += 1
        words = '·'.join(p.get('words', [p['word']]))
        if dec:
            tot['decided'] += 1
            tot['win' if dec['first_move'] == 'win' else 'lose'] += 1
            tot['proof'] += dec['proof_seconds']; tot['verify'] += dec['verify_seconds']; tot['nodes'] += dec['proof_nodes']
            tot['search_decided'] += search
            res = '**지는 수**' if dec['first_move'] == 'lose' else '**이기는 수**'
            print(f'| {name} | {words} | {side.get(p.get("split"), "")} | {form.get(p.get("root_form"), "")} | {search:.0f} | {mtxt} | {res} | '
                  f'{dec["proof_nodes"]:,} | {dec["proof_seconds"]:.1f} | {dec["verify_seconds"]:.1f} | {"·".join(dec.get("reply") or []) or "-"} |')
        else:
            print(f'| {name} | {words} | {side.get(p.get("split"), "")} | {form.get(p.get("root_form"), "")} | {search:.0f} | {mtxt} | 미확정 | - | - | - | - |')
        rows.append((name, p, rs, dec))
    print()
    print(json.dumps({k: (round(v, 1) if isinstance(v, float) else v) for k, v in tot.items()}, ensure_ascii=False))


if __name__ == '__main__':
    main()
