# gen_solved.py OUT.md ROWS.json... : SOLVED_KO.md from the 30 earlier rows (base30.json) plus rows.py outputs; status.json lists open syllables
import json, sys, os
S = '/tmp/claude-0/-home-user-AI-/80ff9426-9f7b-5815-97c0-938f621a9f93/scratchpad'
sys.path.insert(0, S + '/verifier/route-verifier-v2')
from verify_v2 import IndependentModelV2
m = IndependentModelV2(open(S + '/basic_root.txt', 'rb').read())
byg = {}
for w in m.words: byg.setdefault(m.group[m.word_endpoints[w]], []).append(w)
D = os.path.dirname(os.path.abspath(__file__))
base = json.load(open(f'{D}/base30.json', encoding='utf-8'))
status = json.load(open(f'{D}/status.json', encoding='utf-8'))
# latest estimate table (red circle = 받으면 불리); 온 is not in it, the 랑 cell was covered in the image
CIRCLED = set('갑 곡 능 룩 맥 벽 삭 색 솥 습 십 약 업 엽 웅 젓 존 죄 충 칙 칭 쾌 큼 탑 혁 활 훈 흔'.split())
TABLE = set('''갑 객 격 곡 교 군 권 규 균 극 급 능 돌 득 락 력 렵 룩 률 릉 맥 맹 멸 명 박 법 벽 변 병 삭 삼 색 섭 솥 숙 순 습 승 식 십
압 야 약 언 업 역 엽 완 왕 운 움 웅 율 적 절 젓 존 죄 죽 준 즉 증 직 진 찬 축 충 칙 칠 칭 쾌 큼 탁 탄 탑 탕 퇴 편 폭 표 풍 학
할 합 항 행 향 혁 혈 홍 환 활 훈 휘 흑 흔 흥'''.split())
LABEL = {'눅': '눅(룩)', '낭': '낭(랑)', '낙': '낙(락)', '능': '능(릉)'}
EST_KEY = {'눅': '룩', '낭': None, '낙': '락', '능': '능'}
def est(s, res):
    k = EST_KEY.get(s, s)
    if k is None or k not in TABLE: return '—'
    e = '불리' if k in CIRCLED else '유리'
    ok = (e == '유리') == (res == 'W')
    return f'{e} (일치)' if ok else f'{e} → **틀림**'
rows = dict()
for s, v in base.items():
    rows[s] = {'result': v['result'], 'text': v['text'], 'nodes': v['nodes'], 'sha16': v['sha16']}
def ro(w):
    c = ord(w[-1]) - 0xac00; j = c % 28 if 0 <= c < 11172 else 0
    return '로' if j in (0, 8) else '으로'
for path in sys.argv[2:]:
    for s, v in json.load(open(path, encoding='utf-8')).items():
        if v['result'] == 'W':
            text = ', '.join('·'.join(ws) for ws, r, rep, st in v['rows'] if r == 'L')
        else:
            parts = []
            for ws, r, rep, st in v['rows']:
                if r == 'W': parts.append(f"{'·'.join(ws)} → {rep[0]}")
                elif r is None and st == -1:
                    g = m.group[m.word_endpoints[ws[0]]]; a, b = m.edges[g]
                    rv = m.group.get((b, a)); parts.append(f"{'·'.join(ws)} → {byg[rv][0]} (되받기)" if rv is not None else f"{'·'.join(ws)} → ?")
                else: parts.append(f"{'·'.join(ws)} → (정적)")
            text = ', '.join(parts)
        rows[s] = {'result': v['result'], 'text': text, 'nodes': v['nodes'], 'sha16': v['sha'][:16]}
W = sorted(s for s in rows if rows[s]['result'] == 'W'); L = sorted(s for s in rows if rows[s]['result'] == 'L')
out = ['# 시작 음절별 판정 정리 (첫 제시 기준)', '',
       '기초사전 루트 817단어, 표준두음법칙, 한 경기 안 단어 재사용 금지, 낼 단어가 없으면 패배.', '',
       '- **첫 제시 기준:** 그 음절을 817단어 밖의 단어로 넘겨받아, 817단어가 하나도 쓰이지 않은 국면입니다.',
       '- **받는 쪽:** 그 음절로 시작해야 하는 사람. **낸 쪽:** 그 음절을 넘긴 사람.',
       f'- 아래 {len(rows)}개는 모두 증명을 만들어 수정하지 않은 `verify_v2.py`(sha256 `9019cd1d…`)로 검증했습니다. 종료 코드 0, `verified: true`, 판정이 탐색 결과와 같은 것만 넣었습니다.',
       '- 두음법칙으로 같은 국면: 락=낙, 랑=낭, 력=역, 렵=엽, 룩=눅, 률=율, 릉=능.',
       "- '추정표'는 다른 분이 준 한기사 시작글자별 유불리 추정표(최신판)입니다. 빨간 원 = 받으면 불리, 표시 없음 = 받으면 유리. '—'는 표에 없거나 칸이 가려진 음절입니다.",
       '- 받는 쪽이 이기는 음절에서는 이기는 첫 수 하나만 증명했습니다. 다른 첫 수가 이기는지 지는지는 따로 확인하지 않았습니다.', '',
       f'## 받는 쪽이 이기는 음절 ({len(W)}개) — 이 음절을 내면 낸 쪽이 불리', '',
       '| 음절 | 받는 쪽의 이기는 첫 수 | 추정표 | 증명 노드 | proof_sha256 앞 16자 |', '|---|---|---|---:|---|']
for s in W:
    r = rows[s]; out.append(f"| {LABEL.get(s, s)} | {r['text']} | {est(s, 'W')} | {r['nodes']:,} | {r['sha16']} |")
out += ['', f'## 받는 쪽이 지는 음절 ({len(L)}개) — 이 음절을 내면 낸 쪽이 유리', '',
        '받는 쪽이 낼 수 있는 모든 첫 수와, 그 수에 대한 낸 쪽의 반박입니다. 반박 뒤의 모든 갈래도 증명 안에서 끝까지 확인했습니다.', '',
        '| 음절 | 받는 쪽 첫 수 → 낸 쪽의 반박 | 추정표 | 증명 노드 | proof_sha256 앞 16자 |', '|---|---|---|---:|---|']
for s in L:
    r = rows[s]; out.append(f"| {LABEL.get(s, s)} | {r['text']} | {est(s, 'L')} | {r['nodes']:,} | {r['sha16']} |")
wrong = [s for s in W + L if '틀림' in est(s, rows[s]['result'])]
out += ['', '## 추정표와 다른 곳', '']
why = {'탑': '추정표는 불리, 실제로는 받는 쪽이 탑승객으로 이깁니다. 탑승객으로 넘긴 객이 받으면 지는 음절이기 때문입니다.',
       '균': '추정표는 유리, 실제로는 받는 쪽이 집니다. 첫 수가 균형적 하나뿐이고, 낸 쪽이 적갈색으로 이깁니다.',
       '객': '추정표는 유리, 실제로는 받는 쪽이 집니다. 첫 수가 객관식·객관적 둘뿐이고, 낸 쪽이 식생활·적갈색으로 이깁니다.'}
for s in wrong: out.append(f"- **{s}:** {why.get(s, '추정표와 반대입니다.')}")
same = [s for s in W + L if '일치' in est(s, rows[s]['result'])]; absent = [LABEL.get(s, s) for s in W + L if est(s, rows[s]['result']) == '—']
out.append(f'- 나머지 중 {len(same)}개는 추정표와 같습니다.' + (f" {', '.join(absent)}은 표에 없거나 칸이 가려져 비교하지 않았습니다." if absent else ''))
out += ['', '## 아직 확정하지 않은 음절', '']
for k, v in status.items(): out.append(f'- **{k}:** {v}')
out += ['', '## 지는 첫 수로 확인된 것 (역·격)', '',
        '- **역:** 역방향 → 향토색, 역사학·역학 → 학업, 역풍 → 풍류객 (낸 쪽이 이김). 나머지 첫 수의 승패는 아스트라 기록입니다.',
        '- **격:** 격랑 → 낭비벽, 격멸 → 멸치젓, 격변 → 변색, 격식적·격정적 → 적갈색, 격언 → 언약, 격찬 → 찬성표, 격퇴 → 퇴색 (낸 쪽이 이김). 격돌은 보류입니다.', '',
        '## 참고', '',
        '- **깽:** 817단어 중 깽으로 시작하는 단어가 없어서, 817단어만 따지면 받는 순간 집니다(모델 밖 음절).',
        '- **룩:** 두음법칙으로 눅과 같습니다. 눅진눅진 하나뿐이고 낸 쪽이 진갈색으로 이깁니다.',
        '- **적:** 아스트라 쪽에서 연구한 음절이라 이 정리에는 넣지 않았습니다.',
        '- **넘겨받은 단어가 817단어 안의 단어인 경우**는 다른 국면입니다. 칭·존은 따로 계산했습니다(`scan/RESULTS_SCAN.md`). 존칭으로 넘겨받은 칭만 받는 쪽이 이기고(칭칭), 나머지는 모두 받는 쪽이 집니다.',
        '- 받는 쪽이 지는 음절의 첫 수가 표에 없는 경우(예: 곡명)는 왕복 쌍이라 낸 쪽이 짝(명곡)으로 되받아 같은 국면으로 돌아갑니다.']
open(sys.argv[1], 'w', encoding='utf-8').write('\n'.join(out) + '\n')
print(len(W), len(L), wrong)
