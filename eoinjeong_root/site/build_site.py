#!/usr/bin/env python3
"""Build site/data.json for the 어인정 수순 지도 page from the committed results.

usage: python3 eoinjeong_root/site/build_site.py

Sources (all in the repository):
  words_621.txt, syllables_173.txt
  results/{roots,first,second}/res/*.json         and results/archive_index.json
  results/{winner_w,winner_l}/records.jsonl.gz    and results/archive_index_{winner_w,winner_l}.json.gz
Only ACCEPTED positions (every verify_v4 acceptance condition) are written.

data.json:
  words      the 621 words in dictionary order (index = word id)
  syllables  [{"s": syllable, "r": "W"|"L", "v": vertex}] in source order (index = syllable id); r is the receiver's result
  model      ModelV3 of the dictionary for the browser solver: vertices, groups [[source, target, words]], word_group
  tags       release tags; certs [[tag index, sha256]] the certificate files
  nodes      one string per confirmed position: "<syllable id>[.<word id>]... <W|L><cert index>"
             W/L is the result for the player to move after that history.
Checks: every position is accepted; where a position and all its children are known, the position is W
exactly when some child is L.
"""
import gzip
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE.parent / 'guopsaem_root' / 'verifier_v3'))
from verify_v3 import ModelV3  # noqa: E402


def main():
    words = (HERE / 'words_621.txt').read_text(encoding='utf-8').split()
    wid = {w: i for i, w in enumerate(words)}
    syls = (HERE / 'syllables_173.txt').read_text(encoding='utf-8').split()
    sid = {s: i for i, s in enumerate(syls)}
    index = json.loads((HERE / 'results' / 'archive_index.json').read_text(encoding='utf-8'))
    for st in ('winner_w', 'winner_l'):
        with gzip.open(HERE / 'results' / f'archive_index_{st}.json.gz', 'rt', encoding='utf-8') as f:
            index.update(json.load(f))

    def recs():
        for st in ('roots', 'first', 'second'):
            for p in sorted((HERE / 'results' / st / 'res').glob('*.json')):
                yield json.loads(p.read_text(encoding='utf-8'))
        for st in ('winner_w', 'winner_l'):
            with gzip.open(HERE / 'results' / st / 'records.jsonl.gz', 'rt', encoding='utf-8') as f:
                for line in f:
                    yield json.loads(line)

    tags, certs, cert_ix, nodes = [], [], {}, {}
    for r in recs():
        assert r['accepted'] and all(r['verify']['acceptance'].values()), r['id']
        e = index[r['id']]
        assert e['proof_sha256'] == r['proof_sha256']
        if e['release_tag'] not in tags:
            tags.append(e['release_tag'])
        c = (tags.index(e['release_tag']), e['proof_sha256'])
        if c not in cert_ix:
            cert_ix[c] = len(certs)
            certs.append(list(c))
        key = (sid[r['position']['initial_syllable']],) + tuple(wid[w] for w in r['position']['history'])
        val = r['result_for_player_to_move']
        assert nodes.get(key, (val,))[0] == val, key
        nodes[key] = (val, cert_ix[c])
    children = {}
    for k in nodes:
        if len(k) > 1:
            children.setdefault(k[:-1], []).append(k)
    checked = 0
    for k, (val, _) in nodes.items():
        ks = children.get(k)
        if not ks:
            continue
        cur = syls[k[0]] if len(k) == 1 else words[k[-1]][-1]
        used = {words[i] for i in k[1:]}
        from_ok = {cur}
        o = ord(cur) - 0xAC00
        ini, rem = divmod(o, 588)
        vow = rem // 28
        if ini == 5 and vow in (2, 6, 7, 12, 17, 20):
            from_ok.add(chr(0xAC00 + 11 * 588 + rem))
        elif ini == 5 and vow in (0, 1, 8, 11, 13, 18):
            from_ok.add(chr(0xAC00 + 2 * 588 + rem))
        elif ini == 2 and vow in (6, 12, 17, 20):
            from_ok.add(chr(0xAC00 + 11 * 588 + rem))
        legal = [w for w in words if w[0] in from_ok and w not in used]
        if len(ks) == len(legal):
            assert (val == 'W') == any(nodes[c][0] == 'L' for c in ks), k
            checked += 1
    m = ModelV3((HERE / 'words_621.txt').read_bytes(), 621)
    assert m.words == words and not any(m.shared)
    model = {'vertices': len(m.keys), 'groups': [[s[0], t, c] for (s, t), c in zip(m.edges, m.full_counts)],
             'word_group': [m.word_group(w) for w in words]}
    syl_out = [{'s': s, 'r': nodes[(i,)][0], 'v': m.vertex_of(s)} for i, s in enumerate(syls)]
    lines = sorted(nodes.items())
    data = {
        'format': 'eoin621-site-1',
        'dictionary': 'eoinjeong_root/words_621.txt',
        'dictionary_sha256': hashlib.sha256((HERE / 'words_621.txt').read_bytes()).hexdigest(),
        'release_base': 'https://github.com/baekjw2435/AI-/releases/download/',
        'words': words, 'syllables': syl_out, 'model': model, 'tags': tags, 'certs': certs,
        'nodes': ['.'.join(map(str, k)) + ' ' + v + str(c) for k, (v, c) in lines],
    }
    out = HERE / 'site' / 'data.json'
    text = json.dumps({k: v for k, v in data.items() if k != 'nodes'}, ensure_ascii=False)[:-1]
    text += ',\n"nodes":[\n' + ',\n'.join(json.dumps(n) for n in data['nodes']) + '\n]}\n'
    out.write_text(text, encoding='utf-8')
    json.loads(out.read_text(encoding='utf-8'))
    print(f'{out}: {len(nodes)} positions, {len(certs)} certificates, {len(tags)} tags, '
          f'{checked} positions checked against all their children, {out.stat().st_size} bytes')


if __name__ == '__main__':
    main()
