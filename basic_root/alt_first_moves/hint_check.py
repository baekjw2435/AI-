#!/usr/bin/env python3
"""Compare each first move's verdict with the start-syllable verdict of the syllable it hands over.

usage: hint_check.py            (writes results/hint_check.json and prints a summary)

A first word w (s -> t) leaves the other side to move at t with only w used. The start-syllable results of
SOLVED_KO.md (94 syllables, plus 적 and 깽) say who wins at t with no word used. Removing one word keeps the
winner's win whenever some winning strategy of that side never plays it (the loser only loses options; the
winner's moves stay legal). So the expected verdict of w is the opposite of the receiver's result at t, and
the known answer at t is a likely answer after w. This is a prediction for ordering the search only; it decides
nothing. Exceptions show where every winning strategy needs w (self-loop words such as 왕왕, and cycles).
"""
import collections
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
EQ = {'락': '낙', '랑': '낭', '력': '역', '렵': '엽', '룩': '눅', '률': '율', '릉': '능'}   # SOLVED_KO: same position


def start_results():
    """syllable -> ('win', [receiver's winning first moves]) or ('lose', {receiver move: refutation})."""
    p0, sec = {}, None
    for line in (HERE.parent / 'SOLVED_KO.md').read_text(encoding='utf-8').splitlines():
        if line.startswith('## 받는 쪽이 이기는'):
            sec = 'win'
        elif line.startswith('## 받는 쪽이 지는'):
            sec = 'lose'
        elif line.startswith('## '):
            sec = None
        m = re.match(r'\| (\S+?)(\(.\))? \| (.+?) \|', line)
        if not (sec and m) or m.group(1) in ('음절', '---'):
            continue
        if sec == 'win':
            p0[m.group(1)] = ('win', [x.strip() for x in re.split(r'[,·]\s*', re.sub(r'\s*\(.*?\)', '', m.group(3)))])
        else:
            ref = {}
            for part in m.group(3).split(', '):
                a, b = part.split(' → ')
                for w in a.split('·'):
                    ref[w.strip()] = re.sub(r'\s*\(.*?\)', '', b).strip()
            p0[m.group(1)] = ('lose', ref)
    p0['적'] = ('win', ['적갈색', '적색', '적회색', '적자생존'])   # 아스트라 기록; 적자생존은 이 저장소에서 검증
    p0['깽'] = ('lose', {})                                      # 깽으로 시작하는 단어 없음
    return p0


def main():
    p0 = start_results()
    targets = json.loads((HERE / 'targets.json').read_text(encoding='utf-8'))['targets']
    summary = json.loads((HERE / 'results' / 'summary.json').read_text(encoding='utf-8'))
    rows = []
    for x in targets:
        t = EQ.get(x['target'], x['target'])
        verdict = x['existing']['verdict'] if x['existing']['evidence'] == 'verified' else None
        reply = [x['existing']['reply']] if verdict and x['existing'].get('reply') else []
        for r in summary.get(x['id'], []):
            if r.get('decided'):
                verdict, reply = r['first_move'], r.get('reply') or []
        known = p0.get(t)
        rows.append({'id': x['id'], 'split': x['split'], 'hands_over': t, 'self_loop': EQ.get(x['syllable'], x['syllable']) == t,
                     'start_result_at_t': known[0] if known else None,
                     'predicted': None if known is None else ('lose' if known[0] == 'win' else 'win'),
                     'hint': known[1] if known else None,
                     'verified': verdict, 'reply': reply})
    ver = [r for r in rows if r['verified']]
    lose_known = [r for r in ver if r['verified'] == 'lose' and r['start_result_at_t'] == 'win']
    out = {
        'format': 'alt817-hint-check-v1',
        'verified': len(ver),
        'verified_same_as_prediction': sum(r['verified'] == r['predicted'] for r in ver),
        'verified_by_kind': {f'{v} (예측 {p}, 자기 고리 {l})': n for (v, p, l), n in
                             sorted(collections.Counter((r['verified'], r['predicted'], r['self_loop']) for r in ver).items(), key=str)},
        'differs': [r['id'] for r in ver if r['verified'] != r['predicted']],
        'losing_refuted_by_known_answer': sum(bool(set(r['reply']) & set(r['hint'])) for r in lose_known),
        'losing_with_known_answer': len(lose_known),
        'not_verified': len(rows) - len(ver),
        'not_verified_by_prediction': {f'예측 {p}, 자기 고리 {l}': n for (p, l), n in
                                       sorted(collections.Counter((r['predicted'], r['self_loop']) for r in rows if not r['verified']).items(), key=str)},
        'rows': rows,
    }
    (HERE / 'results' / 'hint_check.json').write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in out.items() if k != 'rows'}, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
