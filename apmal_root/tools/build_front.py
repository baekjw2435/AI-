#!/usr/bin/env python3
"""앞말잇기 자료를 '모든 단어를 거꾸로 뒤집은' 끝말잇기 자료로 만든다.

앞말잇기: 다음 단어는 앞 단어의 첫 음절(또는 그 표준 두음 음절)로 끝나야 한다.
단어를 모두 뒤집으면 '다음 단어는 앞 단어의 끝 음절(또는 두음 음절)로 시작' = 끝말잇기이고,
두음 함수도 같은 verify_v3.conv(한 방향)를 그대로 쓴다. 그래서 끝말잇기 도구(ModelV3, solver_v5, verify_v4,
보호막 계산기·검증기)를 고치지 않고 뒤집은 파일만 넣어 쓴다. 화면·표에 낼 때만 단어를 다시 뒤집는다.

usage: python3 apmal_root/tools/build_front.py

읽는 것(받은 원본 그대로, apmal_root/source/)
  standard_words.txt (저장소 맨 위)   표준사전 291,652단어(한 줄에 한 단어)
  루트단어_음절1.txt, 루트단어_음절2.txt  '음절 : 그 음절(두음 포함)로 끝나는 루트 단어들'
  루트단어_짝.txt                     '단어, 짝 단어' (서로 주고받는 짝, 양쪽 방향 줄)
  공격단어_목록.txt                   '[음절]' 다음 줄에 '깊이 N : 단어, …' (그 음절로 끝나는 단어)

쓰는 것
  reversed/표준사전_뒤집음.txt     사전의 모든 단어를 뒤집어 정렬, 한 줄에 한 단어
  reversed/루트단어_뒤집음.txt     끝말잇기 루트 원본과 같은 형식(음절 줄, 그다음 짝 줄), 단어는 뒤집음
  reversed/공격단어_뒤집음.txt     같은 형식, 단어만 뒤집음
  words_534.txt                  뒤집은 루트 단어 534개를 정렬해 공백 하나로 이음(줄바꿈 없음, ModelV3 사전)
  syllables_113.txt              음절 줄의 음절(가나다순), 한 줄에 하나
  build_front.json               셈과 sha256

검사(하나라도 틀리면 멈춤) — eoinjeong_root/tools/build_dict.py와 같은 검사 + 사전 대조
  모두 한글, 사전에 있음, 한 단어가 음절 줄과 짝 줄에 함께 있지 않음, 음절 줄의 단어는 그 음절(또는 두음 음절)로 끝남,
  음절 줄마다 받을 수 있는 (짝이 아닌) 루트 단어가 빠짐없이 있음, 짝 줄은 conv()로 서로 주고받고 반대 줄도 있음,
  공격 단어는 모두 사전에 있고 [음절](또는 두음 음절)로 끝남.
"""
import collections
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parent
sys.path.insert(0, str(REPO / 'guopsaem_root' / 'verifier_v3'))
from verify_v3 import conv, ModelV3  # noqa: E402

EXPECT = {'syllable_lines': 113, 'pair_lines': 104, 'pairs': 52, 'syllable_words': 430, 'pair_words': 104,
          'words': 534}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rev(w):
    return w[::-1]


def hangul(w):
    return all(0xAC00 <= ord(c) <= 0xD7A3 for c in w)


def can_follow(w, s):
    """앞말잇기: s로 시작하는 단어 다음에 w를 낼 수 있음 = w의 끝 음절이 s 또는 conv(s)."""
    return w[-1] in (s, conv(s))


def main():
    src = HERE / 'source'
    dict_src = REPO / 'standard_words.txt'
    words = [w.strip() for w in dict_src.read_text(encoding='utf-8-sig').splitlines() if w.strip()]
    assert len(set(words)) == len(words), '사전에 같은 단어가 두 번'
    assert all(hangul(w) and len(w) >= 2 for w in words), '사전에 한글 두 글자 이상이 아닌 단어'
    dset = set(words)

    syl, pairs, where = {}, [], collections.defaultdict(set)
    for name in ('루트단어_음절1.txt', '루트단어_음절2.txt'):
        for ln, line in enumerate((src / name).read_text(encoding='utf-8-sig').splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            s, rest = line.split(':', 1)
            s = s.strip()
            ws = [w.strip() for w in rest.split(',') if w.strip()]
            assert len(s) == 1 and s not in syl, f'{name} {ln}: 음절이 이상하거나 두 번 {s!r}'
            assert len(set(ws)) == len(ws), f'{name} {ln}: 한 줄에 같은 단어'
            syl[s] = ws
            for w in ws:
                where[w].add('syl')
                assert can_follow(w, s), f'{name} {ln}: {w}는 {s}로 시작하는 단어 다음에 못 냄'
    for ln, line in enumerate((src / '루트단어_짝.txt').read_text(encoding='utf-8-sig').splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        ws = [w.strip() for w in line.split(',') if w.strip()]
        assert len(ws) == 2, f'짝 {ln}: 단어 두 개가 아님: {line}'
        pairs.append(tuple(ws))
        for w in ws:
            where[w].add('pair')
    route = sorted(where)
    assert all(hangul(w) for w in route), '한글이 아닌 루트 단어'
    assert not [w for w in route if w not in dset], f'사전에 없는 루트 단어 {[w for w in route if w not in dset]}'
    assert not [w for w in route if len(where[w]) > 1], '음절 줄과 짝 줄에 함께 있는 단어'
    pairset = set(pairs)
    assert len(pairset) == len(pairs), '같은 짝 줄이 두 번'
    for a, b in pairs:
        # 앞말잇기: a 다음에 b(b가 a의 첫 음절로 끝남), b 다음에 a
        assert can_follow(b, a[0]) and can_follow(a, b[0]), f'짝 {a}, {b}는 서로 주고받지 못함'
        assert (b, a) in pairset, f'짝 {a}, {b}의 반대 줄이 없음'
    for s, ws in syl.items():
        listed = set(ws)
        missing = [w for w in route if where[w] == {'syl'} and can_follow(w, s) and w not in listed]
        assert not missing, f'음절 {s} 줄에 빠진 단어 {missing[:5]}'
    syl_words = [w for w in route if where[w] == {'syl'}]
    pair_words = [w for w in route if where[w] == {'pair'}]
    got = {'syllable_lines': len(syl), 'pair_lines': len(pairs), 'pairs': len({frozenset(p) for p in pairs}),
           'syllable_words': len(syl_words), 'pair_words': len(pair_words), 'words': len(route)}
    for k, v in EXPECT.items():
        assert got[k] == v, f'{k}: {v}개여야 하는데 {got[k]}개'

    # 공격 목록
    att, cur, heads = [], None, []
    for ln, line in enumerate((src / '공격단어_목록.txt').read_text(encoding='utf-8-sig').splitlines(), 1):
        t = line.strip()
        if not t:
            continue
        m = re.match(r'^\[(.+)\]$', t)
        if m:
            cur = m.group(1)
            heads.append(cur)
            continue
        m = re.match(r'^깊이\s*(\d+)\s*:\s*(.*)$', t)
        assert m and cur, f'공격 목록 {ln}: 형식이 다름: {t[:40]}'
        ws = [w.strip() for w in m.group(2).split(',') if w.strip()]
        for w in ws:
            assert w in dset, f'공격 목록 {ln}: 사전에 없는 단어 {w}'
            assert can_follow(w, cur), f'공격 목록 {ln}: {w}는 [{cur}]로 끝나지 않음'
        att.append((cur, int(m.group(1)), ws))
    assert len(set(heads)) == len(heads), '같은 [음절]이 두 번'

    # 뒤집은 파일 쓰기
    out = HERE / 'reversed'
    out.mkdir(exist_ok=True)
    rwords = sorted(rev(w) for w in words)
    (out / '표준사전_뒤집음.txt').write_text('\n'.join(rwords) + '\n', encoding='utf-8')
    lines = [f'{s} : ' + ', '.join(sorted(rev(w) for w in syl[s])) for s in sorted(syl)]
    lines += [f'{rev(a)}, {rev(b)}' for a, b in pairs]
    (out / '루트단어_뒤집음.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    alines, prev = [], None
    for s, d, ws in att:
        if s != prev:
            if prev is not None:
                alines.append('')
            alines.append(f'[{s}]')
            prev = s
        alines.append(f'깊이 {d} : ' + ', '.join(rev(w) for w in ws))
    (out / '공격단어_뒤집음.txt').write_text('\n'.join(alines) + '\n', encoding='utf-8')
    rroute = sorted(rev(w) for w in route)
    wpath, spath = HERE / f'words_{len(rroute)}.txt', HERE / f'syllables_{len(syl)}.txt'
    wpath.write_bytes(' '.join(rroute).encode('utf-8'))
    spath.write_text('\n'.join(sorted(syl)) + '\n', encoding='utf-8')

    # 뒤집은 루트 원본을 끝말잇기 검사(eoinjeong_root/tools/build_dict.py와 같은 내용)로 다시 확인
    rs = {s: [rev(w) for w in ws] for s, ws in syl.items()}
    for s, ws in rs.items():
        assert all(w[0] in (s, conv(s)) for w in ws)
    for a, b in pairs:
        ra, rb = rev(a), rev(b)
        assert rb[0] in (ra[-1], conv(ra[-1])) and ra[0] in (rb[-1], conv(rb[-1]))
    m = ModelV3(wpath.read_bytes(), len(rroute))
    assert sorted(m.words) == rroute
    for s in syl:
        m.vertex_of(s)          # 음절 줄의 음절은 모두 모형 안의 꼭짓점

    # 깊이 1(한방) 확인: 앞말잇기에서 첫 음절(두음 포함)로 끝나는 사전 단어가 없어야 함
    ends = collections.Counter(w[-1] for w in words)

    def cont(x):
        a = conv(x)
        return ends[x] + (ends[a] if a else 0)
    d1 = [w for s, d, ws in att if d == 1 for w in ws]
    not_kill = sorted({w for w in d1 if cont(w[0]) > 0})
    info = {
        'dictionary': 'standard_words.txt', 'dictionary_words': len(words), 'dictionary_sha256': sha(dict_src),
        'sources': {p.name: sha(p) for p in sorted(src.iterdir())},
        'route_counts': got, 'attack': {'syllables': len(heads), 'entries': sum(len(ws) for _, _, ws in att),
                                        'distinct_words': len({w for _, _, ws in att for w in ws}),
                                        'depth1_entries': len(d1), 'depth1_not_one_shot': not_kill},
        'outputs': {str(p.relative_to(HERE)): sha(p) for p in (out / '표준사전_뒤집음.txt', out / '루트단어_뒤집음.txt',
                                                               out / '공격단어_뒤집음.txt', wpath, spath)},
        'model_v3': {'vertices': len(m.keys), 'groups': len(m.edges), 'shared_groups': sum(m.shared)},
        'pair_only_first_syllables': sorted({w[0] for w in rroute} - set(syl) - {conv(x) for x in syl if conv(x)}),
    }
    (HERE / 'build_front.json').write_text(json.dumps(info, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(json.dumps(info, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
