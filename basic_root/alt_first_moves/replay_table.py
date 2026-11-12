#!/usr/bin/env python3
"""Markdown tables of the replay experiment, from results/<NAME>/*.json (see replay_test.py).

usage: replay_table.py NAME        (NAME: folder under results/, e.g. replay1)
Times are seconds on this machine. 'total' of a run = wall time of the solver process (table set-up, reading
the source, search, certificate writing) + the verifier's own run time. Waiting for the shared verification
lock is not part of it (verify_seconds is the verifier's elapsed time, not the caller's wall time).
"""
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent


def total(r):
    return None if r is None else round(r['solver_wall_seconds'] + (r.get('verify_seconds') or 0), 1)


def f(x, nd=1):
    return '-' if x is None else f'{x:,.{nd}f}'


def verdict(r):
    if r is None:
        return '안 돌림'
    if not r['decided']:
        return '미확정'
    return '**지는 수**' if r['first_move'] == 'lose' else '**이기는 수**'


def main():
    res = HERE / 'results' / sys.argv[1]
    recs = [json.loads(p.read_text(encoding='utf-8')) for p in sorted(res.glob('*.json'))]
    print('| 번호 | 첫 수 | 넘겨준 음절(원본 증명 국면) | 직접: 판정 | 직접 전체(초) | 재생: 판정 | 재생 전체(초) | 배 |')
    print('|---|---|---|---|---:|---|---:|---:|')
    for r in recs:
        a, b = r.get('direct'), r['replay']
        ta, tb = total(a), total(b)
        ratio = f'{ta / tb:.1f}' if a and a['decided'] and b['decided'] and tb else ('-' if not (a and b['decided']) else f'>{ta / tb:.1f}')
        print(f'| {r["name"]} | {r["word"]} | {r["source"]["syllable"]} ({r["source"]["proof_nodes"]:,}) | {verdict(a)} | {f(ta)} | {verdict(b)} | {f(tb)} | {ratio} |')
    print()
    print('| 번호 | 방법 | 탐색(초) | 그중 재생(초) | 증명 생성(초) | 검증(초) | 탐색 국면 | 증명 국면 | 재생 국면 | 막힌 곳 | 막힌 곳 탐색: 번/풀림/국면 |')
    print('|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|')
    for r in recs:
        for kind in ('direct', 'replay'):
            x = r.get(kind)
            if x is None:
                continue
            rp = x.get('replay') or {}
            stuck = sum(rp.get(k, 0) for k in ('stuck_old_leaf', 'stuck_witness_gone', 'stuck_witness_static', 'stuck_witness_refuted', 'stuck_new_move'))
            print(f'| {r["name"]} | {"직접" if kind == "direct" else "재생"} | {f(x.get("search_seconds"))} | {f(rp.get("seconds")) if rp else "-"} | '
                  f'{f(x.get("proof_seconds")) if x["decided"] else "-"} | {f(x.get("verify_seconds")) if x["decided"] else "-"} | '
                  f'{x.get("mid_calls") or 0:,} | {(x.get("proof_nodes") or 0):,} | {rp.get("nodes", 0):,} | {stuck:,} | '
                  + (f'{rp.get("local_calls", 0):,} / {rp.get("local_solved", 0):,} / {rp.get("local_mid", 0):,}' if rp else '-') + ' |')


if __name__ == '__main__':
    main()
