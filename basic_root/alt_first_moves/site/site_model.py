#!/usr/bin/env python3
"""Shared pieces for putting v4 certificates on the route site (basic_root/route-site).

The site's model (model.json, route-site-1) and ModelV3 (the model behind every v4 certificate) are the same game on
the 817-word list: no shared groups, the same 718 groups word for word, the same pairs, self-loops and counts, and
the same canonical form (checked on 6,000 random positions, 0 differences). This module maps one onto the other.

  load(model_json)              -> SiteMap with g3[v3 group] = site group, v3v[v3 vertex] = site vertex
  SiteMap.root(pos)             -> (site cur, site counts) of a position {"initial_syllable", "history"}
  SiteMap.write_numeric(path)   -> the numeric model read by cert2site (site numbering)
"""
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / 'guopsaem_root' / 'verifier_v3'))
from verify_v3 import ModelV3  # noqa: E402

DICT = HERE.parents[1] / 'words_817.txt'


class SiteMap:
    def __init__(self, site):
        self.site = site
        self.m = ModelV3(DICT.read_bytes(), 817)
        m = self.m
        assert not any(m.shared), 'shared groups: the site model cannot represent this dictionary'
        owner = {w: g for g, ws in enumerate(site['words']) for w in ws}
        words3 = [[] for _ in m.edges]
        for w in m.words:
            words3[m.word_group(w)].append(w)
        self.g3 = []
        for ws in words3:
            s = {owner[w] for w in ws}
            assert len(s) == 1 and set(site['words'][min(s)]) == set(ws)
            self.g3.append(s.pop())
        assert sorted(self.g3) == list(range(len(site['edges'])))
        self.v3v = {}
        for g, (src, dst) in enumerate(m.edges):
            e = site['edges'][self.g3[g]]
            for a, b in ((src[0], e[0]), (dst, e[1])):
                assert self.v3v.setdefault(a, b) == b
        assert len(self.v3v) == len(m.keys)
        assert all(m.full_counts[g] == site['full'][self.g3[g]] for g in range(len(m.edges)))
        assert {frozenset((self.g3[a], self.g3[b])) for a, b in m.pairs} == {frozenset(p) for p in site['pairs']}
        assert {self.g3[x] for x in m.loops} == set(site['loops'])

    def root(self, pos):
        cur, counts, _ = self.m.position(pos)
        c = [0] * len(self.g3)
        for g, x in enumerate(counts):
            c[self.g3[g]] = x
        return self.v3v[cur], c

    def write_numeric(self, path):
        s = self.site
        V, G = len(s['syllables']), len(s['edges'])
        L = [f'{V} {G}', ' '.join(f'{a} {b}' for a, b in s['edges']), ' '.join(map(str, s['full'])),
             str(len(s['pairs'])) + ' ' + ' '.join(f'{a} {b}' for a, b in s['pairs']),
             str(len(s['loops'])) + ' ' + ' '.join(map(str, s['loops'])),
             ' '.join(map(str, self.g3))]                       # v3 group -> site group (certificate moves are v3 ids)
        Path(path).write_text('\n'.join(L) + '\n', encoding='utf-8')


def load(model_json):
    return SiteMap(json.loads(Path(model_json).read_text(encoding='utf-8')))
