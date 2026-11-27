#!/usr/bin/env python3
"""Build the 어인정 표준사전 루트단어 dictionary (621 words) from the given list.

usage: python3 eoinjeong_root/tools/build_dict.py [SOURCE] [OUT_DIR]
  SOURCE   default eoinjeong_root/source/어인정 표준사전 루트단어.txt
  OUT_DIR  default eoinjeong_root

Same checks as guopsaem_root/tools/merge_v2.py (any failure stops the build):
  all Hangul; a word is never in both parts; each word is listed only under a syllable it can follow
  (its first syllable is X or conv(X), the engine's standard dueum rule); each syllable line lists every
  non-pair word it can take; each pair line is a 2-cycle under conv() and also appears reversed.
Then the expected counts of this list: 173 syllable lines, 148 pair lines (74 pairs, each written from
both sides), 473 distinct words in syllable lines + 148 in pair lines = 621.

Writes (only into OUT_DIR):
  words_621.txt       every distinct word, sorted, joined by one space on ONE line (no newline)
  syllables_173.txt   the 173 start syllables in the order of the source, one per line
Prints the sha256 of both and of the source.  Nothing here is compared with the 817 or 3,683 lists.
"""
import collections
import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'guopsaem_root' / 'verifier_v3'))
from verify_v3 import conv, ModelV3  # noqa: E402

EXPECT = {'syllable_lines': 173, 'pair_lines': 148, 'pairs': 74, 'syllable_words': 473,
          'pair_words': 148, 'words': 621}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    here = Path(__file__).resolve().parents[1]
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else here / 'source' / '어인정 표준사전 루트단어.txt'
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else here
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
            assert len(set(ws)) == len(ws), f'line {ln}: a word repeated in one line'
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
    pairset = set(pairs)
    assert len(pairset) == len(pairs), 'a pair line is repeated'
    for a, b in pairs:
        assert b[0] in (a[-1], conv(a[-1])) and a[0] in (b[-1], conv(b[-1])), f'pair {a}, {b} is not a 2-cycle'
        assert (b, a) in pairset, f'pair {a}, {b} has no reverse line'
    for s, ws in syl.items():
        listed = set(ws)
        missing = [w for w in words if where[w] == {'syl'} and w[0] in (s, conv(s)) and w not in listed]
        assert not missing, f'syllable {s} misses {missing[:5]}'
    syl_words = [w for w in words if where[w] == {'syl'}]
    pair_words = [w for w in words if where[w] == {'pair'}]
    got = {'syllable_lines': len(syl), 'pair_lines': len(pairs), 'pairs': len({frozenset(p) for p in pairs}),
           'syllable_words': len(syl_words), 'pair_words': len(pair_words), 'words': len(words)}
    for k, v in EXPECT.items():
        assert got[k] == v, f'{k}: expected {v}, got {got[k]}'
    wpath = out / f'words_{len(words)}.txt'
    spath = out / f'syllables_{len(order)}.txt'
    wpath.write_bytes(' '.join(words).encode('utf-8'))
    spath.write_text('\n'.join(order) + '\n', encoding='utf-8')
    m = ModelV3(wpath.read_bytes(), len(words))
    assert sorted(m.words) == words
    print('source', src.name, 'sha256', sha(src))
    print('counts', got, '(all as expected)')
    print(f'{wpath.name}: {len(words)} words, one line, sha256 {sha(wpath)}')
    print(f'{spath.name}: {len(order)} start syllables, sha256 {sha(spath)}')
    print(f'ModelV3: {len(m.keys)} vertices, {len(m.edges)} groups, {sum(m.shared)} shared groups')
    no_line = sorted({w[0] for w in words} - set(syl) - {conv(x) for x in syl if conv(x)})
    print('first syllables with no line of their own (only pair words start there):', ' '.join(no_line))


if __name__ == '__main__':
    main()
