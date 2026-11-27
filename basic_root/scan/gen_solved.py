# gen_solved.py CATALOG.json OUT.md [STATUS.json] : SOLVED_KO.md from the route site's catalog, so the summary shows exactly
# the first moves and answers the site shows. Every entry there comes from a proof verified with the unmodified verify_v2.py.
import json, sys

cat = json.load(open(sys.argv[1], encoding='utf-8'))
out_path = sys.argv[2]
status = json.load(open(sys.argv[3], encoding='utf-8')) if len(sys.argv) > 3 else {}
LABEL = {'눅': '눅(룩)', '낭': '낭(랑)', '낙': '낙(락)', '능': '능(릉)'}


def ro(w):
    c = ord(w[-1]) - 0xac00
    j = c % 28 if 0 <= c < 11172 else 0
    return '로' if j in (0, 8) else '으로'


grid = {}
for g in cat['grid']:
    grid.setdefault(g['base'], g)
    if g['s'] == g['base']:
        grid[g['base']] = g


def est(s, wins):
    g = grid.get(s)
    if not g or g['estimate'] is None:
        return '—'
    e = g['estimate']
    return f'{e} (일치)' if (e == '유리') == wins else f'{e} → **틀림**'


fresh = [e for e in cat['entries'] if e['kind'] == 'fresh']
rows = {}
for e in fresh:
    moves = e['root']['moves']
    if e['receiverWins']:
        win = [m for m in moves if m['status'] == 'win']
        text = ', '.join('·'.join(m['words']) for m in win)
        extra = [w for w, n in (e.get('notes') or {}).items() if '이기는 수' in n]
        if extra:
            text += f" (아스트라 기록상 {'·'.join(extra)}도 이김)"
    else:
        parts = []
        for m in moves:
            r = m['reply']
            if m['status'] != 'lose':
                parts.append(f"{'·'.join(m['words'])} → ?")
            elif r:
                parts.append(f"{'·'.join(m['words'])} → {r['word']}" + (' (되받기)' if r['how'] == '되받기' else ''))
            else:
                parts.append(f"{'·'.join(m['words'])} → ({m['how']})")
        text = ', '.join(parts)
    rows[e['syllable']] = (e, text)
W = sorted(s for s, (e, _) in rows.items() if e['receiverWins'])
L = sorted(s for s, (e, _) in rows.items() if not e['receiverWins'])
out = ['# 시작 음절별 판정 정리 (첫 제시 기준)', '',
       '기초사전 루트 817단어, 표준두음법칙, 한 경기 안 단어 재사용 금지, 낼 단어가 없으면 패배.', '',
       '- **첫 제시 기준:** 그 음절을 817단어 밖의 단어로 넘겨받아, 817단어가 하나도 쓰이지 않은 국면입니다.',
       '- **받는 쪽:** 그 음절로 시작해야 하는 사람. **낸 쪽:** 그 음절을 넘긴 사람.',
       f'- 아래 {len(rows)}개는 모두 증명을 만들어 수정하지 않은 `verify_v2.py`(sha256 `9019cd1d…`)로 검증했습니다. 종료 코드 0, `verified: true`, 판정이 탐색 결과와 같은 것만 넣었습니다.',
       '- 표의 첫 수와 응수는 루트 수순 지도(`route-site/`)가 보여 주는 것과 같습니다(같은 목록 파일에서 만듦).',
       '- 두음법칙으로 같은 국면: 락=낙, 랑=낭, 력=역, 렵=엽, 룩=눅, 률=율, 릉=능.',
       "- '추정표'는 다른 분이 준 한기사 시작글자별 유불리 추정표(최신판)입니다. 빨간 원 = 받으면 불리, 표시 없음 = 받으면 유리. '—'는 표에 없거나 칸이 가려진 음절입니다.",
       '- 받는 쪽이 이기는 음절에서는 이기는 첫 수를 증명한 것만 적었습니다. 나머지 첫 수가 이기는지 지는지는 따로 확인하지 않았습니다.', '',
       f'## 받는 쪽이 이기는 음절 ({len(W)}개) — 이 음절을 내면 낸 쪽이 불리', '',
       '| 음절 | 받는 쪽의 이기는 첫 수 | 추정표 | 증명 노드 | proof_sha256 앞 16자 |', '|---|---|---|---:|---|']
for s in W:
    e, text = rows[s]
    out.append(f"| {LABEL.get(s, s)} | {text} | {est(s, True)} | {e['proof']['nodes']:,} | {e['proof']['sha256'][:16]} |")
out += ['', f'## 받는 쪽이 지는 음절 ({len(L)}개) — 이 음절을 내면 낸 쪽이 유리', '',
        '받는 쪽이 낼 수 있는 모든 첫 수와, 그 수에 대한 낸 쪽의 반박입니다. 반박 뒤의 모든 갈래도 증명 안에서 끝까지 확인했습니다.', '',
        '| 음절 | 받는 쪽 첫 수 → 낸 쪽의 반박 | 추정표 | 증명 노드 | proof_sha256 앞 16자 |', '|---|---|---|---:|---|']
for s in L:
    e, text = rows[s]
    out.append(f"| {LABEL.get(s, s)} | {text} | {est(s, False)} | {e['proof']['nodes']:,} | {e['proof']['sha256'][:16]} |")
wrong = [s for s in W + L if '틀림' in est(s, rows[s][0]['receiverWins'])]
same = [s for s in W + L if '일치' in est(s, rows[s][0]['receiverWins'])]
absent = [LABEL.get(s, s) for s in W + L if est(s, rows[s][0]['receiverWins']) == '—']
out += ['', '## 추정표와 다른 곳', '']
why = {'탑': '추정표는 불리, 실제로는 받는 쪽이 탑승객으로 이깁니다. 탑승객으로 넘긴 객이 받으면 지는 음절이기 때문입니다.',
       '균': '추정표는 유리, 실제로는 받는 쪽이 집니다. 첫 수가 균형적 하나뿐이고, 낸 쪽이 적갈색으로 이깁니다.',
       '객': '추정표는 유리, 실제로는 받는 쪽이 집니다. 첫 수가 객관식·객관적 둘뿐이고, 낸 쪽이 식생활·적갈색으로 이깁니다.',
       '습': '추정표는 불리, 실제로는 받는 쪽이 습식으로 이깁니다(첫 수별로 나눠 푼 뒤 합친 증명).'}
for s in wrong:
    out.append(f"- **{s}:** {why.get(s, '추정표와 반대입니다.')}")
out.append(f'- 나머지 중 {len(same)}개는 추정표와 같습니다.' + (f" {', '.join(absent)}은 표에 없거나 칸이 가려져 비교하지 않았습니다." if absent else ''))
astra = [e for e in cat['entries'] if e['kind'] == 'astra']
if astra:
    out += ['', '## 적 (아스트라 연구)', '',
            f"- 아스트라 ‘적색 루트 연습실’ v3의 증명 색인(정준 국면 {astra[0]['proof']['nodes']:,}개)으로는 받는 쪽이 이깁니다"
            f"({', '.join('·'.join(m['words']) for m in astra[0]['root']['moves'] if m['status'] == 'win')}). 이 저장소의 verify_v2로 검증한 것은 아닙니다."]
if status:
    out += ['', '## 아직 확정하지 않은 음절', '']
    for k, v in status.items():
        out.append(f'- **{k}:** {v}')
out += ['', '## 참고', '',
        '- **깽:** 817단어 중 깽으로 시작하는 단어가 없어서, 817단어만 따지면 받는 순간 집니다(모델 밖 음절).',
        '- **넘겨받은 단어가 817단어 안의 단어인 경우**는 다른 국면입니다. 칭·존은 따로 계산했습니다(`scan/RESULTS_SCAN.md`). 존칭으로 넘겨받은 칭만 받는 쪽이 이기고(칭칭), 나머지는 모두 받는 쪽이 집니다.',
        '- 역·격의 지는 첫 수와 반박은 `RESULTS_YEOK.md`, `RESULTS_GYEOK.md`와 수순 지도에 있습니다. 역의 일부 첫 수는 아스트라 기록만 있고, 격돌은 보류입니다.',
        '- (되받기): 왕복 쌍의 한쪽을 내면 낸 쪽이 짝으로 되받아, 받는 쪽이 다시 같은 국면에 서게 됩니다.']
open(out_path, 'w', encoding='utf-8').write('\n'.join(out) + '\n')
print(len(W), len(L), 'wrong', wrong, 'absent', absent)
