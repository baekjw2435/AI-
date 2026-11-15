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
           'position': c['position'], 'parent': c.get('parent'), 'untried': run.get('untried', False),
           'allotted_seconds': run.get('allotted_seconds'),
           'search_seconds': run.get('solver', {}).get('total_search_seconds') or run.get('solver', {}).get('seconds'), 'this_run_search_seconds': run.get('solver', {}).get('seconds'), 'earlier_runs': run.get('earlier_runs', 0), 'proof_seconds': run.get('solver', {}).get('emit_seconds'),
           'verify_seconds': run.get('verify_wall_seconds'), 'proof_nodes': run.get('solver', {}).get('proof_nodes'),
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
                    rm3 = real_moves(pos3)
                    af = next(x for g3, x, _ in rm3 if g3 == ag)
                    after.append({'words': f, 'answer': af, 'how': 'certificate',
                                  'answer_alternatives': [x for g3, x, c3 in rm3 if g3 != ag and c3 != 'static_lose']})
                else:
                    after.append({'words': f, 'answer': None, 'how': 'static (the next position is statically won)'})
            elif cls == 'cancelled':
                pos3 = {**pos2, 'history': pos2['history'] + [f[0]]}
                pw = partner(pos3, gg)
                after.append({'words': f, 'answer': pw, 'how': 'pair/loop answer',
                              'answer_alternatives': [x for g3, x, c3 in real_moves(pos3) if (not pw or pw[0] not in x) and c3 != 'static_lose']})
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
                    replies.append({'words': f, 'answer': af, 'how': 'certificate', 'answer_alternatives': others})
                else:
                    replies.append({'words': f, 'answer': None, 'how': 'static (the position after it is statically won)'})
            elif cls == 'cancelled':
                pos2 = {**pos, 'history': pos['history'] + [f[0]]}
                pw = partner(pos2, gg)
                replies.append({'words': f, 'answer': pw, 'how': 'pair/loop answer',
                                'answer_alternatives': [x for g3, x, c3 in real_moves(pos2) if (not pw or pw[0] not in x) and c3 != 'static_lose']})
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
    opens = open_choices(recs)
    (out / 'open.json').write_text(json.dumps(opens, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    (out / 'OPEN_KO.md').write_text(open_markdown(cases_doc, opens), encoding='utf-8')
    print(json.dumps([{k: r.get(k) for k in ('name', 'word', 'accepted', 'verdict')} for r in recs], ensure_ascii=False))


def side(hist):
    """who is to move after `hist`: the player of hist[0] (the presenter of this study's position) or the other."""
    return '제시자' if len(hist) % 2 == 0 else '받은 쪽'


def line(hist, n0):
    return ' → '.join(hist[n0:]) if len(hist) > n0 else ''


def open_choices(recs):
    """the winning side's choices the certificates did not decide, as positions with their full history"""
    out = []
    for r in recs:
        if not r.get('accepted'):
            continue
        h = r['position']['history']
        if r['mover_result'] == 'W':
            out.append({'from': r['name'], 'at': h, 'who': side(h), 'choices': [x['words'] for x in r['mover_other'] if x['class'] == 'unconfirmed'],
                        'kind': 'the winner\'s other moves where the certificate chose ' + '·'.join(r['reply']['words'])})
            for a in r['after_reply']:
                if a.get('answer_alternatives'):
                    at = h + [r['reply']['words'][0], a['words'][0]]
                    out.append({'from': r['name'], 'at': at, 'who': side(at), 'choices': a['answer_alternatives'],
                                'kind': 'the winner\'s other answers where the certificate chose ' + '·'.join(a['answer'] or [])})
        else:
            for a in r['replies']:
                if a.get('answer_alternatives'):
                    at = h + [a['words'][0]]
                    out.append({'from': r['name'], 'at': at, 'who': side(at), 'choices': a['answer_alternatives'],
                                'kind': 'the winner\'s other answers where the certificate chose ' + '·'.join(a['answer'] or [])})
    for o in out:
        o['ply_of_choice'] = len(o['at']) + 1
    return out


def markdown(doc, recs):
    j = lambda ws: '·'.join(ws) if ws else '-'
    how = {'certificate': '증명서', 'pair/loop answer': '되받기(짝 단어)', 'static': '정적 판정'}
    base = doc['base_position']
    n0 = len(base['history'])
    first = recs[0]['position']['history'] if recs else base['history']
    L = [f"# 후속 갈래 {doc['batch']}: {' → '.join(base['history'])} 뒤 ({doc.get('created', '')})", '']
    if doc.get('question'):
        L += [f"질문: {doc['question']}", '']
    L += [f"용어: 제시자 = {first[0]}을(를) 낸 사람, 받은 쪽 = 상대. '지는 수'는 그 단어를 낸 사람이 지는 수, '이기는 수'는 이기는 수입니다.", '',
          '## 판정', '',
          '| 수순(앞 자리 뒤) | 고른 사람 | 판정 | 이긴 쪽의 다음 수(증명서) | 탐색·증명서 작성·검증(초) | 증명 국면 |', '|---|---|---|---|---|---:|']
    for k, v in doc.get('already_known', {}).items():
        L.append(f'| {k} | | 이기는 수 | - | 기존 증명 | |')
    for r in recs:
        h = r['position']['history']
        who = side(h[:-1])
        seq = line(h[:-1], n0) + (' → ' if len(h) - 1 > n0 else '') + j(r['group_words'])
        if not r['accepted']:
            t = '미시도(예산 소진)' if r.get('untried') else '시도 후 미확정'
            s_ = '-' if r.get('untried') else f"{r['search_seconds'] or 0:.1f} · - · -"
            L.append(f"| {seq} | {who} | {t} | | {s_} | |")
            continue
        v = '지는 수' if r['verdict'] == 'lose' else '이기는 수'
        nxt = j(r['reply']['words']) + f" ({side(h)})" if r['verdict'] == 'lose' else f"({side(h)}의 모든 수가 짐)"
        L.append(f"| {seq} | {who} | {v} | {nxt} | {r['search_seconds']:.1f} · {r['proof_seconds']:.1f} · {r['verify_seconds']:.1f} | {r['proof_nodes']:,} |")
    L += ['', '- 같은 칸의 단어(·로 이음)는 한 묶음입니다. 어느 단어를 써도 같은 국면입니다.',
          '- 각 판정은 그 국면(앞의 모든 단어와 그 선택까지 쓴 이력)의 v4 증명서가 바꾸지 않은 verify_v4를 수락 조건 모두로 통과한 것입니다.', '']
    for r in recs:
        if not r['accepted']:
            continue
        h = r['position']['history']
        mover, other = side(h), side(h[:-1])
        L += [f"## {line(h, n0) or j(r['group_words'])}", '']
        if r['verdict'] == 'lose':
            L += [f"- {mover}의 승리수: **{j(r['reply']['words'])}** (증명서)",
                  f"- {mover}의 다른 수: " + (', '.join(j(x['words']) + (' (정적으로 짐)' if x['class'] == 'static_lose' else '') for x in r['mover_other']) or '없음')
                  + ' → **미확인**', '',
                  f"| {j(r['reply']['words'])} 뒤 {other}의 수 | {mover}의 응수 | 근거 | {mover}의 다른 응수(미확인) |", '|---|---|---|---|']
            for a in r['after_reply']:
                L.append(f"| {j(a['words'])} | {j(a['answer'])} | {how.get(a['how'], a['how'])} | {', '.join(j(x) for x in a.get('answer_alternatives', [])) or '-'} |")
        else:
            L += [f"- {mover}의 모든 수가 집니다(검증된 판정).", '',
                  f"| {mover}의 수 | {other}의 응수 | 근거 | {other}의 다른 응수(미확인) |", '|---|---|---|---|']
            for a in r['replies']:
                L.append(f"| {j(a['words'])} | {j(a['answer'])} | {how.get(a['how'], a['how'])} | {', '.join(j(x) for x in a.get('answer_alternatives', [])) or '-'} |")
        L.append('')
    return '\n'.join(L) + '\n'


def open_markdown(doc, opens):
    j = lambda ws: '·'.join(ws) if ws else '-'
    n0 = len(doc['base_position']['history'])
    L = [f"# 더 깊은 미확인 선택 ({doc['batch']} 뒤에 남은 것)", '',
         '이기는 쪽이 증명서와 다르게 둘 수 있는 수입니다. 아직 풀지 않았습니다(자동으로 내려가지 않음). 수순은 '
         + ' → '.join(doc['base_position']['history']) + ' 뒤부터 적습니다.', '']
    by = {}
    for o in opens:
        by.setdefault(o['ply_of_choice'], []).append(o)
    total = sum(len(o['choices']) for o in opens)
    L += [f"모두 {total}묶음, 자리 {len(opens)}곳.", '']
    for ply in sorted(by):
        L += [f"## {ply}번째 수의 선택 ({sum(len(o['choices']) for o in by[ply])}묶음)", '', '| 자리(앞 수순) | 고르는 사람 | 미확인 선택 |', '|---|---|---|']
        for o in by[ply]:
            L.append(f"| {line(o['at'], n0)} | {o['who']} | {', '.join(j(c) for c in o['choices'])} |")
        L.append('')
    return '\n'.join(L) + '\n'


if __name__ == '__main__':
    main()
