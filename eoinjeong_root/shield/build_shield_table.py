#!/usr/bin/env python3
"""보호막 표: 끝 음절마다 '이을 수 있는 단어 수'(= 그 음절로 끝나는 단어를 쓸 수 있는 보호막의 상한).

usage: python3 eoinjeong_root/shield/build_shield_table.py
  source/표준사전_어인정_전체단어.txt   전체 사전(한 줄에 한 단어, 482,556단어)
  source/공격단어_목록.txt               [음절] 다음 줄에 '깊이 N : 단어, 단어, …' (깊이는 1 = 한방만 씀)
writes
  syllable_shield_table.tsv   끝음절, 이을 수 있는 단어 수(두음 포함), 두음 빼면, 쓸 수 있는 보호막
  attack_words_shield.tsv     공격단어마다 끝 음절, 이을 수 있는 단어 수, 쓸 수 있는 보호막

규칙(사용자 설명): 단어 w는 지금 보호막 s가 cont(w의 끝 음절) 이하일 때만 쓸 수 있다.
  cont(x) = 사전에서 x 또는 x의 두음 음절(엔진 표준두음법칙, verify_v3.conv)로 시작하는 단어 수.
  한방(cont 0)은 보호막 0에서만. 보호막은 한 수마다 1씩 준다.
두음을 넣는 근거: 공격 목록의 '가재무릇'은 깊이 3이다(릇으로 시작하는 단어는 0개, 두음 늣은 1개).
"""
import collections
import hashlib
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / 'guopsaem_root' / 'verifier_v3'))
from verify_v3 import conv  # noqa: E402


def main():
    dic = HERE / 'source' / '표준사전_어인정_전체단어.txt'
    atk = HERE / 'source' / '공격단어_목록.txt'
    words = [w.strip() for w in dic.read_text(encoding='utf-8-sig').splitlines() if w.strip()]
    first = collections.Counter(w[0] for w in words)

    def c0(s):
        return first.get(s, 0)

    def c1(s):
        a = conv(s)
        return first.get(s, 0) + (first.get(a, 0) if a else 0)

    def cap(n):
        return '0' if n == 0 else f'0~{n}'

    ends = sorted({w[-1] for w in words})
    with open(HERE / 'syllable_shield_table.tsv', 'w', encoding='utf-8') as f:
        f.write('끝음절\t이을수있는단어수(두음포함)\t두음빼면\t쓸수있는보호막\n')
        for s in sorted(ends, key=lambda s: (c1(s), s)):
            f.write(f'{s}\t{c1(s)}\t{c0(s)}\t{cap(c1(s))}\n')
    att, cur = [], None
    for line in atk.read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        m = re.match(r'^\[(.+)\]$', line)
        if m:
            cur = m.group(1)
            continue
        m = re.match(r'^깊이\s*(\d+)\s*:\s*(.*)$', line)
        if m:
            att += [(cur, int(m.group(1)), w.strip()) for w in m.group(2).split(',') if w.strip()]
    with open(HERE / 'attack_words_shield.tsv', 'w', encoding='utf-8') as f:
        f.write('시작음절\t공격단어\t한방\t끝음절\t이을수있는단어수\t쓸수있는보호막\n')
        for s, d, w in att:
            f.write(f"{s}\t{w}\t{'한방' if d == 1 else ''}\t{w[-1]}\t{c1(w[-1])}\t{cap(c1(w[-1]))}\n")
    d1 = [w for _, d, w in att if d == 1]
    print(f'dictionary {len(words)} words sha256 {hashlib.sha256(dic.read_bytes()).hexdigest()}')
    print(f'attack list {len(att)} words in {len({s for s, _, _ in att})} syllables sha256 {hashlib.sha256(atk.read_bytes()).hexdigest()}')
    print(f'end syllables {len(ends)}; depth-1 words {len(d1)}, of them with a continuation: {sum(1 for w in d1 if c1(w[-1]))}')


if __name__ == '__main__':
    main()
