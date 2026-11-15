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
            else:
                after.append({'words': f, 'answer': None, 'how': {'static_lose': 'static', 'cancelled': 'pair/loop answer',
                                                                  'static_win': 'static?'}.get(cls, cls)})
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
            else:
                replies.append({'words': f, 'answer': None, 'how': {'static_lose': 'static', 'cancelled': 'pair/loop answer'}.get(cls, cls)})
        rec['replies'] = replies
    return rec


def main():
    cases_doc = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    work, out = Path(sys.argv[2]), Path(sys.argv[3])
    out.mkdir(parents=True, exist_ok=True)
    recs = [summarize(c, work / c['name']) for c in cases_doc['cases']]
    (out / 'summary.json').write_text(json.dumps({'batch': cases_doc['batch'], 'base_position': cases_doc['base_position'],
                                                  'cases': recs}, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(json.dumps([{k: r.get(k) for k in ('name', 'word', 'accepted', 'verdict')} for r in recs], ensure_ascii=False))


if __name__ == '__main__':
    main()
