#!/usr/bin/env python3
"""Write the tables and the summary of the 어인정 621-word study from results/{roots,first,second}/res.

usage: report.py      writes RESULTS_KO.md, results/summary.json
Only ACCEPTED results (every verify_v4 acceptance condition) are written as 확정; everything else is 미확정.
"""
import collections
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parent
sys.path.insert(0, str(REPO / 'guopsaem_root' / 'verifier_v3'))
from verify_v3 import ModelV3  # noqa: E402


def load(stage):
    d = HERE / 'results' / stage / 'res'
    return [json.loads(f.read_text(encoding='utf-8')) for f in sorted(d.glob('*.json'))]


def plan(stage):
    p = HERE / 'plans' / f'{stage}.jsonl'
    return [json.loads(x) for x in p.read_text(encoding='utf-8').splitlines() if x.strip()] if p.exists() else []


def legal(m, s, history):
    cur, _, used = m.position({'initial_syllable': s, 'history': history})
    return [w for w in m.words if w[0] in m.keys[cur] and w not in used]


def wall(stage):
    f = list((HERE / 'results' / stage).glob('DONE_*'))
    return float(f[0].read_text()) if f else None


def main():
    m = ModelV3((HERE / 'words_621.txt').read_bytes(), 621)
    syls = (HERE / 'syllables_173.txt').read_text(encoding='utf-8').split()
    stages = {st: load(st) for st in ('roots', 'first', 'second')}
    plans = {st: plan(st) for st in stages}
    res = {}
    for st, rs in stages.items():
        for r in rs:
            key = (r['position']['initial_syllable'], tuple(r['position']['history']))
            res[key] = r['result_for_player_to_move'] if r['accepted'] else None
    summary = {'stages': {}}
    for st, rs in stages.items():
        tried = {r['id'] for r in rs}
        acc = [r for r in rs if r['accepted']]
        summary['stages'][st] = {
            'positions_planned': len(plans[st]), 'confirmed': len(acc),
            'tried_unconfirmed': len(rs) - len(acc), 'not_tried': len([p for p in plans[st] if p['id'] not in tried]),
            'search_seconds': round(sum(r['solver'].get('seconds', 0) for r in rs), 2),
            'proof_writing_seconds': round(sum(r['solver'].get('emit_seconds', 0) for r in rs), 2),
            'verify_wall_seconds': round(sum(r.get('wall_verify_seconds', 0) for r in rs), 2),
            'verifier_reported_seconds': round(sum(r.get('verify', {}).get('elapsed_seconds', 0) for r in acc), 2),
            'solver_process_wall_seconds': round(sum(r['wall_solve_seconds'] for r in rs), 2),
            'stage_wall_clock_seconds_4_jobs': wall(st),
            'max_search_seconds': max((r['solver'].get('seconds', 0) for r in rs), default=0),
            'max_certificate_nodes': max((r['solver'].get('proof_nodes', 0) for r in rs), default=0),
            'certificate_bytes': sum(r.get('proof_bytes', 0) for r in acc)}

    root = {s: res.get((s, ())) for s in syls}
    lines = []
    W = [s for s in syls if root[s] == 'W']
    L = [s for s in syls if root[s] == 'L']
    U = [s for s in syls if root[s] is None]
    places_first = [s for s in syls if all(res.get((s, (w,))) for w in legal(m, s, []))]
    places_second = []
    deeper_w, deeper_l = 0, 0
    for s in L:
        for w1 in legal(m, s, []):
            if all(res.get((s, (w1, w2))) for w2 in legal(m, s, [w1])):
                places_second.append((s, w1))
    for s in W:
        for w1 in legal(m, s, []):
            if res.get((s, (w1,))) == 'L':
                deeper_w += len(legal(m, s, [w1]))
    for s in L:
        for w1 in legal(m, s, []):
            for w2 in legal(m, s, [w1]):
                if res.get((s, (w1, w2))) == 'L':
                    deeper_l += len(legal(m, s, [w1, w2]))
    summary.update({'roots_W': len(W), 'roots_L': len(L), 'roots_unconfirmed': len(U),
                    'places_all_first_moves_classified': len(places_first),
                    'places_all_second_moves_classified': len(places_second),
                    'deeper_W_presenter_replies_after_winning_first_move': deeper_w,
                    'deeper_L_receiver_third_moves_after_winning_second_move': deeper_l})

    def mv(s, hist):
        win, lose, unk = [], [], []
        for w in legal(m, s, list(hist)):
            r = res.get((s, tuple(hist) + (w,)))
            (win if r == 'L' else lose if r == 'W' else unk).append(w)
        return win, lose, unk

    def cell(ws):
        return ', '.join(ws) if ws else '없음'

    lines += ['# 어인정 표준사전 루트단어(621단어) 결과', '',
              '> 이 판정은 이 사전(`words_621.txt`, sha256 `98f81ea532c8a45a…`)에서만 유효합니다. '
              '817단어(한기사)·3,683단어(구없샘) 연구와 섞지 않습니다.', '',
              '- **확정**은 verify_v4의 수락 조건(종료 코드 0, verified, 결과 일치, deflate-exact, 사전·국면·입력·증명서 sha256 일치)을 모두 통과한 것만입니다.',
              '- "받은 쪽"은 음절을 받아 먼저 두는 쪽, "제시자"는 그 음절을 넘긴 쪽입니다.', '',
              '## 1. 음절 173개, 아무 단어도 안 쓴 채 받았을 때', '',
              f'- 받은 쪽 **승 {len(W)}개**, **패 {len(L)}개**, 미확정 {len(U)}개.', '',
              f'**받으면 이기는 음절 ({len(W)})**: ' + ' '.join(W), '',
              f'**받으면 지는 음절 ({len(L)})**: ' + ' '.join(L), '']
    if U:
        lines += [f'**미확정 ({len(U)})**: ' + ' '.join(U), '']
    lines += ['## 2. 받은 쪽의 모든 첫 수 (기본 제시)', '',
              '"이기는 수"는 받은 쪽이 두면 이기는 첫 수, "지는 수"는 두면 지는 첫 수입니다.', '',
              '| 음절 | 받은 쪽 | 이기는 수 | 지는 수 |', '|---|---|---|---|']
    for s in syls:
        win, lose, unk = mv(s, ())
        tag = {'W': '승', 'L': '패'}.get(root[s], '미확정')
        extra = f' (미확정: {cell(unk)})' if unk else ''
        lines.append(f'| {s} | {tag} | {cell(win)} | {cell(lose)}{extra} |')
    lines += ['', '## 3. 받으면 지는 음절: 첫 수마다 제시자(이기는 쪽)의 모든 2번째 수', '',
              '"이기는 수"는 제시자가 두면 이기는 2번째 수, "지는 수"는 두면 지는(역전당하는) 2번째 수입니다.', '']
    for s in L:
        lines += [f'### {s}', '', '| 받은 쪽 첫 수 | 이기는 2번째 수 | 지는 2번째 수 |', '|---|---|---|']
        for w1 in legal(m, s, []):
            win, lose, unk = mv(s, (w1,))
            extra = f' (미확정: {cell(unk)})' if unk else ''
            lines.append(f'| {w1} | {cell(win)} | {cell(lose)}{extra} |')
        lines.append('')
    (HERE / 'RESULTS_KO.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    (HERE / 'results' / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
