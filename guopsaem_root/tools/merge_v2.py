#!/usr/bin/env python3
"""Build the 구없샘 word list from the combined list given on 2026-11-13.

usage: python3 tools/merge_v2.py [SOURCE] [OUT_DIR]
  SOURCE   default source/list_2026-11-13_combined.txt
  OUT_DIR  default . (writes words_<N>.txt, syllables_<M>.txt there)

The source has two parts:
  "X : w1, w2, ..."  one line per start syllable X: the words a player who receives X may play
                     (words starting with X or with conv(X), the engine's dueum rule)
  "a, b"             a pair of words that answer each other (a ends where b may start and the
                     reverse); every pair is listed twice, once from each side
The word list is every distinct word. Checks (any failure stops the build):
  all Hangul; a word is never in both parts; each word is listed only under a syllable it can follow;
  each syllable line lists every non-pair word it can take; each pair line is a 2-cycle under conv()
  and also appears reversed. Then it prints what changed against words_3436.txt / syllables_470.txt.
"""
import collections
import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'verifier_v3'))
from verify_v3 import conv  # noqa: E402


def main():
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'source' / 'list_2026-11-13_combined.txt'
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT
    syl, order, pairs, where = {}, [], [], collections.defaultdict(set)
    for ln, line in enumerate(src.read_text(encoding='utf-8-sig').splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        if ':' in line:
            s, rest = line.split(':', 1)
            s = s.strip()
            ws = [w.strip() for w in rest.split(',') if w.strip()]
            assert len(s) == 1 and s not in syl, f'line {ln}: bad or repeated syllable {s!r}'
            syl[s] = ws
            order.append(s)
            for w in ws:
                where[w].add('syl')
                assert w[0] in (s, conv(s)), f'line {ln}: {w} cannot follow {s}'
        else:
            ws = [w.strip() for w in line.split(',') if w.strip()]
            assert len(ws) == 2, f'line {ln}: a pair line needs two words: {line}'
            pairs.append(tuple(ws))
            for w in ws:
                where[w].add('pair')
    words = sorted(where)
    assert all(all(0xAC00 <= ord(c) <= 0xD7A3 for c in w) for w in words), 'non-Hangul word'
    assert not [w for w in words if len(where[w]) > 1], 'a word is in both parts'
    for a, b in pairs:
        assert b[0] in (a[-1], conv(a[-1])) and a[0] in (b[-1], conv(b[-1])), f'pair {a}, {b} is not a 2-cycle'
        assert (b, a) in set(pairs), f'pair {a}, {b} has no reverse line'
    for s, ws in syl.items():
        listed = set(ws)
        missing = [w for w in words if where[w] == {'syl'} and w[0] in (s, conv(s)) and w not in listed]
        assert not missing, f'syllable {s} misses {missing[:5]}'
    pair_words = [w for w in words if where[w] == {'pair'}]
    wpath = out / f'words_{len(words)}.txt'
    spath = out / f'syllables_{len(order)}.txt'
    wpath.write_text('\n'.join(words) + '\n', encoding='utf-8')
    spath.write_text('\n'.join(order) + '\n', encoding='utf-8')
    print(f'{wpath.name}: {len(words)} words (sha256 {hashlib.sha256(wpath.read_bytes()).hexdigest()})')
    print(f'{spath.name}: {len(order)} start syllables')
    print(f'source: {len(syl)} syllable lines, {len(pairs)} pair lines ({len(pairs) // 2} pairs), '
          f'{len(pair_words)} words only in pair lines')
    no_line = sorted({w[0] for w in words} - set(syl) - {conv(x) for x in syl if conv(x)})
    print('first syllables with no line of their own (reachable only by receiving exactly that syllable):',
          ' '.join(no_line))
    old_w = ROOT / 'words_3436.txt'
    old_s = ROOT / 'syllables_470.txt'
    if old_w.exists() and old_s.exists():
        ow = set(old_w.read_text(encoding='utf-8').split())
        os_ = old_s.read_text(encoding='utf-8').split()
        add, rem = sorted(set(words) - ow), sorted(ow - set(words))
        print(f'against words_3436.txt: +{len(add)} words, -{len(rem)} words')
        print('  removed:', ' '.join(rem))
        print('  added (not in pair lines):', ' '.join(w for w in add if where[w] == {'syl'}))
        print(f'  added in pair lines: {sum(1 for w in add if where[w] == {"pair"})}')
        print('  start syllables added:', ' '.join(s for s in order if s not in os_),
              '| removed:', ' '.join(s for s in os_ if s not in syl))


if __name__ == '__main__':
    main()
