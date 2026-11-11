#!/usr/bin/env python3
"""Target list for 'the winner's other first moves' in the 817-word (한기사) study (2026-11-11).

For each of the 64 syllables whose receiver wins (first-presentation positions, SOLVED_KO.md):
  1. list every legal first word (the ORIGINAL words, before any simplification of the root position);
  2. build the exact position after playing it, with the verifier's model (verify_v3.ModelV3.position):
     the current vertex and the remaining count of every word group; words whose positions are identical
     (byte-identical solver input) are merged into one target;
  3. attach the verdicts that already exist, with the kind of evidence:
       verified    - a proof checked by the original verify_v2.py in the earlier study (sha256 recorded in
                     route-site/catalog.json): each root's winning move, and the 격/역 moves solved one by one;
       relayed     - Astra's record only (catalog notes); never verified in this repository;
       solver_only - mentioned in a write-up as decided by the solver, no verification record;
       none        - nothing.
  4. assign every syllable to the tuning set or to the final comparison set (fixed before any result).
Also checked here: the original 817 model (verify.py IndependentModel, used by verify_v2) and the model used
now (verify_v3.ModelV3, the model of verify_v4) describe the same game for this dictionary.

usage: build_targets.py [OUT_DIR]     (writes targets.json, TARGETS_KO.md, TARGETS_LIST_KO.md)
"""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
BASIC = HERE.parent
sys.path.insert(0, str(BASIC.parent / 'guopsaem_root' / 'verifier_v3'))
sys.path.insert(0, str(BASIC / 'verifier' / 'route-verifier-v2'))
from verify_v3 import ModelV3  # noqa: E402
from verify import IndependentModel, dueum  # noqa: E402  (the original 817 model)

DICT = BASIC / 'words_817.txt'
CATALOG = BASIC / 'route-site' / 'catalog.json'
SOLVED = BASIC / 'SOLVED_KO.md'
SPLIT_SALT = 'alt817-split-v1:'
SOLVER_ONLY = {('탑', '탑승권'): ('lose', 'scan/RESULTS_SCAN.md: "탑승권은 지는 수(22초에 확정)" - 탐색기 결과만, 검증 기록 없음')}


def h(s):
    return hashlib.sha256(s.encode('utf-8')).hexdigest()


def model_check(dbytes, m3):
    """The v2 model and the v3 model must be the same game on this dictionary."""
    m2 = IndependentModel(dbytes, 817)
    assert not any(m3.shared), 'a shared group: the v2 model cannot express this dictionary'
    assert all(len(k) <= 1 for k in m3.keys)
    out2 = {s for s, v in m2.vertex.items() if m2.outgoing[v]}
    f = {s: m3.vertex_of(s) for s in m2.syllables}
    live = [f[s] for s in out2]
    assert len(set(live)) == len(live), 'two v2 vertices with words map to one v3 vertex'
    dead = {f[s] for s in m2.syllables if s not in out2}
    assert len(dead) <= 1 and not (dead & set(live)), 'dead-end vertices are not merged into one'
    for w in m3.words:
        s2, t2 = m2.word_endpoints[w]
        (s3,), t3 = m3.word_group_key[w]
        assert f[m2.syllables[s2]] == s3 and f[m2.syllables[t2]] == t3, f'endpoints differ for {w}'
    return {'v2_vertices': len(m2.syllables), 'v2_groups': len(m2.edges), 'v3_vertices': len(m3.keys),
            'v3_groups': len(m3.edges), 'v2_dead_end_vertices': len(m2.syllables) - len(out2),
            'same_game': True}


def solved_ko_roots():
    """Syllables and winning words listed in SOLVED_KO.md (cross-check of the catalog)."""
    txt = SOLVED.read_text(encoding='utf-8')
    sec = txt.split('## 받는 쪽이 이기는 음절')[1].split('\n## ')[0]
    out = {}
    for line in sec.splitlines():
        if not line.startswith('| ') or line.startswith('| 음절') or line.startswith('|---'):
            continue
        cells = [c.strip() for c in line.strip('|').split('|')]
        syl = cells[0][0]
        main = re.sub(r'\(.*?\)', '', cells[1])
        out[syl] = [w for w in re.split(r'[,·\s]+', main) if w]
    return out


def main():
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE
    dbytes = DICT.read_bytes()
    m = ModelV3(dbytes, 817)
    m2 = IndependentModel(dbytes, 817)
    check = model_check(dbytes, m)
    cat = json.loads(CATALOG.read_text(encoding='utf-8'))
    assert cat['dictionary_sha256'] == hashlib.sha256(dbytes).hexdigest()
    entries = {e['id']: e for e in cat['entries'] if e['kind'] == 'fresh'}
    roots = [s for s, e in entries.items() if e['receiverWins']]
    sk = solved_ko_roots()
    assert sorted(sk) == sorted(roots) and len(roots) == 64, 'SOLVED_KO.md and the site catalog list different roots'
    # split: syllables in hash order, alternately tuning / final  (fixed rule, independent of any result)
    order = sorted(roots, key=lambda s: h(SPLIT_SALT + s))
    split = {s: ('tune' if i % 2 == 0 else 'final') for i, s in enumerate(order)}
    words_of = {}
    for w in m.words:
        words_of.setdefault(m.word_group(w), []).append(w)
    targets = []
    total_words = 0
    for s in sorted(roots):
        e = entries[s]
        cur, raw, _ = m.position({'initial_syllable': s, 'history': []})
        red = m.reduce(cur, raw)
        canon, st = m.normalize(cur, raw)
        assert st == -1
        first_words = [w for w in m.words if w[0] in m.keys[cur]]
        total_words += len(first_words)
        states = {}
        for w in first_words:
            c2, k2, _ = m.position({'initial_syllable': s, 'history': [w]})
            states.setdefault(m.numeric_input(c2, k2), []).append(w)
        # the same grouping with the ORIGINAL 817 model (verify.py), counted independently
        st2 = {}
        for w in first_words:
            st2.setdefault(m2.position({'initial_syllable': s, 'history': [w]})[:2], []).append(w)
        assert sorted(sorted(v) for v in st2.values()) == sorted(sorted(v) for v in states.values()), f'{s}: v2 and v3 models group first words differently'
        assert sorted(first_words) == sorted(w for w in m2.words if m2.word_endpoints[w][0] == m2.vertex[dueum(s)])
        cat_moves = {tuple(sorted(mv['words'])): mv for mv in e['root']['moves']}
        assert sorted(cat_moves) == sorted(tuple(sorted(v)) for v in states.values()), f'{s}: the site catalog groups first words differently'
        proofs1 = {}
        for p in e['proofs']:
            if len(p['history']) == 1:
                proofs1[p['history'][0]] = p
        notes = e.get('notes') or {}
        for inp, ws in sorted(states.items(), key=lambda kv: sorted(kv[1])):
            ws = sorted(ws)
            g = m.word_group(ws[0])
            assert all(m.word_group(w) == g for w in ws) and sorted(words_of[g]) == ws
            t = m.edges[g][1]
            child = bytearray(raw); child[g] -= 1
            _, cst = m.normalize(t, bytes(child))
            form = 'pair_cancelled' if not canon[g] else ('kept' if canon[g] == raw[g] else 'kept_partly_cancelled')
            assert canon[g] or (red[g] == 0 and t != cur), 'a first move removed for another reason than pair cancellation'
            mv = cat_moves[tuple(ws)]
            ex = {'verdict': None, 'evidence': 'none'}
            if mv['how'] == '증명':
                ex = {'verdict': mv['status'], 'evidence': 'verified', 'verifier': 'verify_v2.py (원본)'}
                pw = next((w for w in ws if w in proofs1), None)
                p = proofs1[pw] if pw else e['proof']
                ex['proof'] = {'position': [s] + ([pw] if pw else []), 'nodes': p['nodes'], 'sha256': p['sha256'],
                               'kind': '첫 수 따로 증명' if pw else '시작 음절 증명(이기는 첫 수 포함)'}
                assert pw or (mv['status'] == 'win' and sorted(e['root']['best']['words']) == ws)
                assert not pw or (p['result'] == 'L') == (mv['status'] == 'win')
                if mv.get('reply'):
                    ex['reply'] = mv['reply']['word']
            else:
                assert mv['status'] == '?'
                rel = [notes[w] for w in ws if w in notes]
                if rel and all('아스트라 기록상' in r for r in rel):
                    v = {'이기는': 'win', '지는': 'lose'}
                    vs = {v[k] for r in rel for k in v if k + ' 수' in r}
                    assert len(vs) == 1 and len(rel) == len(ws)
                    ex = {'verdict': vs.pop(), 'evidence': 'relayed', 'source': '아스트라 기록 (이 저장소에서 검증한 적 없음)'}
                elif any((s, w) in SOLVER_ONLY for w in ws):
                    v, src = SOLVER_ONLY[(s, ws[0])]
                    ex = {'verdict': v, 'evidence': 'solver_only', 'source': src}
                elif rel:
                    ex = {'verdict': None, 'evidence': 'none', 'note': rel[0]}
            targets.append({
                'id': f'{s}/{ws[0]}', 'syllable': s, 'words': ws, 'target': m.names[t],
                'input_sha256': hashlib.sha256(inp).hexdigest(), 'root_form': form, 'child_static': cst,
                'existing': ex, 'split': split[s],
            })
        # SOLVED_KO winning words must be verified wins here
        for w in sk[s]:
            tt = next(x for x in targets if x['syllable'] == s and w in x['words'])
            assert tt['existing'] == dict(tt['existing'], verdict='win', evidence='verified'), f'{s} {w}: SOLVED_KO win not verified in catalog'
    by = Counter((t['existing']['evidence'], t['existing']['verdict']) for t in targets)
    forms = Counter(t['root_form'] for t in targets)
    unverified = [t for t in targets if t['existing']['evidence'] != 'verified']
    counts = {
        'winning_syllables': len(roots), 'legal_first_words': total_words, 'distinct_positions': len(targets),
        'root_form': dict(forms),
        'canonical_first_moves_438': forms['kept'] + forms['kept_partly_cancelled'],
        'verified_win': by[('verified', 'win')], 'verified_lose': by[('verified', 'lose')],
        'relayed_win': by[('relayed', 'win')], 'relayed_lose': by[('relayed', 'lose')],
        'solver_only': sum(v for (e, _), v in by.items() if e == 'solver_only'),
        'no_record': by[('none', None)],
        'not_verified_total': len(unverified),
        'not_verified_canonical': sum(1 for t in unverified if t['root_form'] != 'pair_cancelled'),
        'not_verified_pair_cancelled': sum(1 for t in unverified if t['root_form'] == 'pair_cancelled'),
        'child_static': sum(1 for t in targets if t['child_static'] != -1),
        'split_syllables': dict(Counter(split.values())),
        'split_not_verified': dict(Counter(t['split'] for t in unverified)),
    }
    assert total_words == sum(len(t['words']) for t in targets)
    # 적: the root verdict itself is Astra's record (not verified here), so it is kept apart from the 64
    je = next(e for e in cat['entries'] if e['kind'] == 'astra' and e['syllable'] == '적')
    jcur, _, _ = m.position({'initial_syllable': '적', 'history': []})
    jwords = [w for w in m.words if w[0] in m.keys[jcur]]
    jwin = [mv for mv in je['root']['moves'] if mv['status'] == 'win']
    assert sum(len(mv['words']) for mv in je['root']['moves']) == len(jwords) and all(mv['how'] == '아스트라 증명' for mv in jwin)
    jeok = {'words': len(jwords), 'positions': len(je['root']['moves']), 'relayed_win': len(jwin),
            'relayed_win_words': ['·'.join(mv['words']) for mv in jwin],
            'unknown': sum(1 for mv in je['root']['moves'] if mv['status'] == '?'), 'source': je['proof']['source']}
    doc = {'format': 'alt817-targets-1', 'dictionary_sha256': hashlib.sha256(dbytes).hexdigest(), 'model_check': check, 'jeok': jeok,
           'split_rule': f'syllables sorted by sha256("{SPLIT_SALT}" + syllable), alternately tune / final',
           'counts': counts, 'targets': targets}
    (out_dir / 'targets.json').write_text(json.dumps(doc, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(json.dumps({'model_check': check, 'counts': counts}, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
