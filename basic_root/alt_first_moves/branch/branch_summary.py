#!/usr/bin/env python3
"""What the accepted branch certificates say: the verdict of each choice, the winning side's next moves, and what is
still unconfirmed.

usage: branch_summary.py CASES.json WORK OUT_DIR
  reads WORK/<name>/run.json and proof.v4.gz of every case; writes OUT_DIR/summary.json and OUT_DIR/SUMMARY_KO.md

For one case the root is the position after the chosen word; the side to move there is called the mover.
  root W (the mover wins, so the chosen word LOSES for the side that played it): the certificate's winning move R;
         the mover's other real moves (unconfirmed, except moves the static rule decides); and after R, every real
         move of the other side with the certificate's answer.
  root L (the chosen word WINS): every real move of the mover loses (that is what the verified verdict says); for each
         the certificate's answer, and how many other answers of the winner stay unconfirmed.
Real moves are counted on the real word counts (ModelV3.position). A move missing from the canonical state is either
static (its target is statically decided, the verifier's own static rule) or cancelled by a pair / self-loop
(the canonical form answers it with the partner word).
"""
import gzip
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
BASIC = HERE.parents[1]
sys.path.insert(0, str(BASIC.parent / 'guopsaem_root' / 'verifier_v3'))
from verify_v3 import ModelV3  # noqa: E402

m = ModelV3((BASIC / 'words_817.txt').read_bytes(), 817)
WORDS = [[] for _ in m.edges]
for w in m.words:
    WORDS[m.word_group(w)].append(w)


def load_nodes(proof, want):
    """id -> (r, [(group, child)]) for the ids in `want`, plus the root id."""
    out = {}
    with gzip.open(proof, 'rt', encoding='utf-8') as f:
        head = json.loads(f.readline())
        for line in f:
            if not line.strip():
                continue
            i = int(line[6:line.index(',')])
            if (i == head['root']) if want == 'root' else (i in want):
                n = json.loads(line)
                out[i] = (n['r'], [tuple(x) for x in n['m']])
    return head['root'], out


def real_moves(pos):
    """[(group, words not used yet, class)] of the side to move; class: canonical / static_lose / static_win / cancelled."""
    cur, counts, used = m.position(pos)
    paired = m.reduce(cur, counts)
    labels = m.static_labels(paired)
    core, st = m.normalize(cur, counts)
    res = []
    for g in m.available[cur]:
        if not counts[g]:
            continue
        free = [w for w in WORDS[g] if w not in used]
        tgt = m.edges[g][1]
        if st == -1 and core[g]:
            cls = 'canonical'
        elif labels[tgt] == 1 and paired[g]:
            cls = 'static_lose'      # the next mover wins statically: this move loses
        elif labels[tgt] == 0 and paired[g]:
            cls = 'static_win'
        else:
            cls = 'cancelled'
        res.append((g, free, cls))
    return res


def partner(pos, g):
    """The word that answers a cancelled move of group g (its pair's other group, or the same self-loop group)."""
    cur, counts, used = m.position(pos)
    for a, b in m.pairs:
        if g in (a, b):
            o = b if g == a else a
            return [w for w in WORDS[o] if w not in used]
    if g in m.loops:
        return [w for w in WORDS[g] if w not in used]
    return None


def name(g, free):
    return '·'.join(free) if free else '·'.join(WORDS[g])


def summarize(c, d):
    run = json.loads((d / 'run.json').read_text(encoding='utf-8'))
    rec = {'name': c['name'], 'word': c['word'], 'group_words': c['group_words'], 'accepted': run.get('accepted', False),
           'search_seconds': run['solver'].get('seconds'), 'proof_seconds': run['solver'].get('emit_seconds'),
           'verify_seconds': run.get('verify_wall_seconds'), 'proof_nodes': run['solver'].get('proof_nodes'),
           'proof_sha256': (run.get('verify') or {}).get('proof_sha256')}
    if not rec['accepted']:
        rec['verdict'] = 'unknown'
        return rec
    proof = d / 'proof.v4.gz'
    pos = c['position']
    root, nodes = load_nodes(proof, 'root')
    r, mv = nodes[root]
    rec['mover_result'] = r
    rec['verdict'] = 'lose' if r == 'W' else 'win'          # for the side that played the chosen word
    if r == 'W':
        g, child = mv[0]
        moves = real_moves(pos)
        free = next(f for gg, f, _ in moves if gg == g)
        rec['reply'] = {'group': g, 'words': free}
        rec['mover_other'] = [{'words': f, 'class': 'static_lose' if cls == 'static_lose' else 'unconfirmed'}
                              for gg, f, cls in moves if gg != g]
        pos2 = {**pos, 'history': pos['history'] + [free[0]]}
        _, n2 = load_nodes(proof, {child})
        r2, mv2 = n2[child]
        assert r2 == 'L'
        kids = {gg: cc for gg, cc in mv2}
        _, n3 = load_nodes(proof, set(kids.values()))
        after = []
        for gg, f, cls in real_moves(pos2):
            if gg in kids:
                cr, cmv = n3[kids[gg]]
                if cmv:
                    ag, _ = cmv[0]
                    pos3 = {**pos2, 'history': pos2['history'] + [f[0]]}
                    af = next(x for g3, x, _ in real_moves(pos3) if g3 == ag)
                    after.append({'words': f, 'answer': af, 'how': 'certificate'})
                else:
                    after.append({'words': f, 'answer': None, 'how': 'static (the next position is statically won)'})
            elif cls == 'cancelled':
                pos3 = {**pos2, 'history': pos2['history'] + [f[0]]}
                after.append({'words': f, 'answer': partner(pos3, gg), 'how': 'pair/loop answer'})
            else:
                after.append({'words': f, 'answer': None, 'how': {'static_lose': 'static', 'static_win': 'static?'}.get(cls, cls)})
        rec['after_reply'] = after
    else:
        kids = {gg: cc for gg, cc in mv}
        _, n2 = load_nodes(proof, set(kids.values()))
        replies = []
        for gg, f, cls in real_moves(pos):
            if gg in kids:
                cr, cmv = n2[kids[gg]]
                if cmv:
                    ag, _ = cmv[0]
                    pos2 = {**pos, 'history': pos['history'] + [f[0]]}
                    rm = real_moves(pos2)
                    af = next(x for g3, x, _ in rm if g3 == ag)
                    others = [x for g3, x, c3 in rm if g3 != ag and c3 != 'static_lose']
                    replies.append({'words': f, 'answer': af, 'how': 'certificate', 'answer_alternatives_unconfirmed': len(others)})
                else:
                    replies.append({'words': f, 'answer': None, 'how': 'static (the position after it is statically won)'})
            elif cls == 'cancelled':
                pos2 = {**pos, 'history': pos['history'] + [f[0]]}
                replies.append({'words': f, 'answer': partner(pos2, gg), 'how': 'pair/loop answer'})
            else:
                replies.append({'words': f, 'answer': None, 'how': {'static_lose': 'static'}.get(cls, cls)})
        rec['replies'] = replies
    return rec


def main():
    cases_doc = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    work, out = Path(sys.argv[2]), Path(sys.argv[3])
    out.mkdir(parents=True, exist_ok=True)
    recs = [summarize(c, work / c['name']) for c in cases_doc['cases']]
    (out / 'summary.json').write_text(json.dumps({'batch': cases_doc['batch'], 'base_position': cases_doc['base_position'],
                                                  'cases': recs}, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    (out / 'SUMMARY_KO.md').write_text(markdown(cases_doc, recs), encoding='utf-8')
    print(json.dumps([{k: r.get(k) for k in ('name', 'word', 'accepted', 'verdict')} for r in recs], ensure_ascii=False))


def markdown(doc, recs):
    j = lambda ws: '·'.join(ws) if ws else '-'
    how = {'certificate': '증명서', 'pair/loop answer': '되받기(짝 단어)', 'static': '정적 판정'}
    base = doc['base_position']
    L = [f"# 후속 갈래: {' → '.join(base['history'])} 뒤 ({doc.get('created', '')})", '',
         f"질문: {doc['question']}", '',
         '용어: 제시자 = 식생활을 낸 사람(지금 둘 차례), 받은 쪽 = 활극을 낸 사람. 지는 수 = 그 단어를 낸 제시자 패·받은 쪽 승.', '',
         '## 판정', '',
         '| 제시자의 선택 | 판정 | 받은 쪽의 승리수(증명서) | 탐색·증명서 작성·검증(초) | 증명 국면 |', '|---|---|---|---|---:|']
    for k, v in doc.get('already_known', {}).items():
        L.append(f'| {k} | 이기는 수(제시자 승) | - | 기존 증명(묶음 17) | |')
    for r in recs:
        if not r['accepted']:
            L.append(f"| {j(r['group_words'])} | 미확정 | | {r['search_seconds']} · - · - | |")
            continue
        v = '지는 수(제시자 패·받은 쪽 승)' if r['verdict'] == 'lose' else '이기는 수(제시자 승·받은 쪽 패)'
        rep = j(r['reply']['words']) if r['verdict'] == 'lose' else '(받은 쪽의 모든 수가 짐)'
        L.append(f"| {j(r['group_words'])} | {v} | {rep} | {r['search_seconds']:.1f} · {r['proof_seconds']:.1f} · {r['verify_seconds']:.1f} | {r['proof_nodes']:,} |")
    L += ['', '- 같은 줄의 단어(예: 극적·극단적)는 한 묶음입니다. 어느 단어를 써도 같은 국면입니다.',
          '- 각 판정은 그 국면(앞의 단어와 그 선택까지 모두 쓴 이력)의 v4 증명서가 바꾸지 않은 verify_v4를 수락 조건 모두로 통과한 것입니다.', '']
    done = [r for r in recs if r['accepted']]
    nk = len(doc.get('already_known', {}))
    unconf = sum(sum(1 for x in r.get('mover_other', []) if x['class'] != 'static_lose') for r in done if r['verdict'] == 'lose')
    L += ['## 완료 상태(`../../TERMS_KO.md`의 네 단계)', '',
          f"- 이 자리({' → '.join(base['history'])} 뒤, 제시자 차례): 합법적인 묶음 {len(recs) + nk}개 중 {len(done) + nk}개 분류"
          + (' → **3단계(그 자리의 모든 선택 분류) 완료**' if len(done) == len(recs) else ' → 3단계 미완료'),
          f"  - 이기는 수 {nk + sum(1 for r in done if r['verdict'] == 'win')}개, 지는 수 {sum(1 for r in done if r['verdict'] == 'lose')}개, 미확정 {len(recs) - len(done)}개",
          '- 각 선택 뒤 국면: 1단계(승패 확정)·2단계(승리 전략 확보). 증명서가 끝까지의 승리 전략입니다.',
          f"- 남는 미확인: 지는 수 뒤에서 받은 쪽(이기는 쪽)이 증명과 다르게 둘 수 있는 수 {unconf}묶음(아래 각 절). 그 뒤의 갈래도 같은 식으로 미확인이 남습니다(4단계는 범위를 정해야 함).", '']
    for r in recs:
        if not r['accepted']:
            continue
        L += [f"## {j(r['group_words'])}", '']
        if r['verdict'] == 'lose':
            L += [f"- 받은 쪽의 승리수: **{j(r['reply']['words'])}** (증명서)",
                  f"- 받은 쪽의 다른 수: " + (', '.join(f"{j(x['words'])}" + (' (정적으로 짐)' if x['class'] == 'static_lose' else '') for x in r['mover_other']) or '없음')
                  + " → **미확인**(증명이 고르지 않은 이기는 쪽의 다른 선택)",
                  f"- {j(r['reply']['words'])} 뒤 제시자의 모든 수와 받은 쪽의 응수:", '',
                  '| 제시자의 수 | 받은 쪽의 응수 | 근거 |', '|---|---|---|']
            for a in r['after_reply']:
                L.append(f"| {j(a['words'])} | {j(a['answer'])} | {how.get(a['how'], a['how'])} |")
            L += ['', '- 이 응수들도 증명이 고른 수입니다. 받은 쪽의 다른 응수는 미확인입니다.', '']
        else:
            L += ['| 받은 쪽의 수 | 제시자의 응수 | 근거 | 제시자의 다른 응수(미확인) |', '|---|---|---|---:|']
            for a in r['replies']:
                L.append(f"| {j(a['words'])} | {j(a['answer'])} | {how.get(a['how'], a['how'])} | {a.get('answer_alternatives_unconfirmed', '')} |")
            L.append('')
    return '\n'.join(L) + '\n'


if __name__ == '__main__':
    main()
