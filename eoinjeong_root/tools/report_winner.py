#!/usr/bin/env python3
"""Tables of the winner's next choice (stages winner_w, winner_l) from results/<stage>/records.jsonl.gz.

usage: report_winner.py    writes RESULTS_WINNER_W_KO.md, RESULTS_WINNER_L_KO.md, results/summary_winner.json
Only ACCEPTED results are 확정.  A "place" is a position where the winner is to move (after the loser's reply);
a move there is a winning move if the position after it is L for the loser (who is then to move).
"""
import gzip
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parent
sys.path.insert(0, str(REPO / 'guopsaem_root' / 'verifier_v3'))
from verify_v3 import ModelV3  # noqa: E402


def records(stage):
    with gzip.open(HERE / 'results' / stage / 'records.jsonl.gz', 'rt', encoding='utf-8') as f:
        return [json.loads(x) for x in f]


def wall(stage):
    f = list((HERE / 'results' / stage).glob('DONE_*'))
    return float(f[0].read_text()) if f else None


def main():
    m = ModelV3((HERE / 'words_621.txt').read_bytes(), 621)
    syls = (HERE / 'syllables_173.txt').read_text(encoding='utf-8').split()
    summary = {}
    for stage, fname, title, header in (
            ('winner_w', 'RESULTS_WINNER_W_KO.md',
             '받으면 이기는 음절: 승자(받은 쪽)의 이기는 첫 수 → 패자(제시자)의 모든 응수 → 승자의 모든 수',
             '| 승자 첫 수 → 패자 응수 | 승자 판정 | 이기는 수 | 지는 수 |'),
            ('winner_l', 'RESULTS_WINNER_L_KO.md',
             '받으면 지는 음절: 패자(받은 쪽) 첫 수 → 승자(제시자)의 이기는 2번째 수 → 패자의 모든 3번째 수 → 승자의 모든 4번째 수',
             '| 1 → 2 → 3번째 수 | 승자 판정 | 이기는 4번째 수 | 지는 4번째 수 |')):
        rs = records(stage)
        plan = [json.loads(x) for x in (HERE / 'plans' / f'{stage}.jsonl').read_text(encoding='utf-8').splitlines() if x]
        res = {(r['position']['initial_syllable'], tuple(r['position']['history'])):
               (r['result_for_player_to_move'] if r['accepted'] else None) for r in rs}
        acc = [r for r in rs if r['accepted']]
        tried = {r['id'] for r in rs}
        places = [p for p in plan if p['kind'] == 'place']
        full, wins, loses, unk_moves, bad = 0, 0, 0, 0, []
        lines = [f'# {title}', '',
                 '> 어인정 표준사전 루트단어(621단어) 사전에서만 유효합니다. 모든 칸은 verify_v4 수락 조건을 통과한 확정 결과만 적었습니다.', '',
                 '"승자 판정"은 패자가 응수한 뒤 승자 차례 자리의 판정(승이어야 함)입니다. '
                 '"이기는 수"는 승자가 두면 계속 이기는 수, "지는 수"는 두면 역전당하는 수입니다.', '']
        by_syl = {}
        for p in places:
            by_syl.setdefault(p['initial_syllable'], []).append(p)
        for s in syls:
            if s not in by_syl:
                continue
            lines += [f'## {s}', '', header, '|---|---|---|---|']
            for p in by_syl[s]:
                h = p['history']
                pr = res.get((s, tuple(h)))
                win, lose, unk = [], [], []
                cur, _, used = m.position({'initial_syllable': s, 'history': h})
                for w in [w for w in m.words if w[0] in m.keys[cur] and w not in used]:
                    r = res.get((s, tuple(h) + (w,)))
                    (win if r == 'L' else lose if r == 'W' else unk).append(w)
                wins += len(win)
                loses += len(lose)
                unk_moves += len(unk)
                if not unk:
                    full += 1
                    if pr is not None and (pr == 'W') != bool(win):
                        bad.append(p['id'])
                extra = f" (미확정: {', '.join(unk)})" if unk else ''
                verdict = {'W': '승', 'L': '패'}.get(pr, '미확정')
                lines.append(f"| {' → '.join(h)} | {verdict} | {', '.join(win) or '없음'} | "
                             f"{', '.join(lose) or '없음'}{extra} |")
            lines.append('')
        (HERE / fname).write_text('\n'.join(lines) + '\n', encoding='utf-8')
        summary[stage] = {
            'positions_planned': len(plan), 'confirmed': len(acc), 'tried_unconfirmed': len(rs) - len(acc),
            'not_tried': len([p for p in plan if p['id'] not in tried]),
            'places': len(places), 'places_confirmed_W': sum(1 for p in places
                                                            if res.get((p['initial_syllable'], tuple(p['history']))) == 'W'),
            'places_confirmed_L': sum(1 for p in places if res.get((p['initial_syllable'], tuple(p['history']))) == 'L'),
            'places_all_moves_classified': full, 'winning_moves': wins, 'losing_moves': loses,
            'unconfirmed_moves': unk_moves, 'place_vs_moves_inconsistent': bad,
            'search_seconds': round(sum(r['solver'].get('seconds', 0) for r in rs), 2),
            'proof_writing_seconds': round(sum(r['solver'].get('emit_seconds', 0) for r in rs), 2),
            'verify_wall_seconds': round(sum(r.get('wall_verify_seconds', 0) for r in rs), 2),
            'solver_process_wall_seconds': round(sum(r['wall_solve_seconds'] for r in rs), 2),
            'stage_wall_clock_seconds_4_jobs': wall(stage),
            'max_search_seconds': max((r['solver'].get('seconds', 0) for r in rs), default=0),
            'max_certificate_nodes': max((r['solver'].get('proof_nodes', 0) for r in rs), default=0),
            'certificate_bytes': sum(r.get('proof_bytes', 0) for r in acc)}
    (HERE / 'results' / 'summary_winner.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1),
                                                          encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
