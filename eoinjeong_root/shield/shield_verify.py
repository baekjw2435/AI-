#!/usr/bin/env python3
"""보호막 검증기: shield_calc.py가 낸 판정 근거(증명서, shield-cert-2)를 계산기 코드 없이 다시 확인한다.

usage: shield_verify.py CERT.json

자리 = (받은 음절 x, 보호막 t, 보호막 구간에서 쓴 단어 U).  쓴 단어 전체 = 질문의 --used ∪ U.
  * t > 0, 승: 적힌 단어가 지금 낼 수 있고(두음 포함, 안 쓴 단어, 끝 음절의 이을 단어 수 ≥ t), 그 뒤 자리가 패.
  * t > 0, 패: 지금 낼 수 있는 '모든' 단어 각각에 대해 그 뒤 자리가 증명서에 있고 승.
      그 뒤 자리의 U: 기록할 단어(루트 단어, 제자리 묶음, 왕복 쌍 묶음, 12개 이하 묶음)면 U에 더하고, 아니면 그대로.
      같은 묶음·같은 끝 음절의 기록 단어끼리는 바꿔 써도 같은 자리이므로, 그중 하나의 자리가 있으면 된다.
      기록 안 하는 단어는 묶음에 13개 이상이라 12수 안에 바닥나지 않는다(이것도 다시 확인).
  * t = 0(잎): 계산기와 다른 근거로 대조.
      루트 음절: 쓴 루트 단어가 없으면 확정 루트 결과(site/data.json)와 같아야 함.
        쓴 루트 단어가 있으면 CERT.json.route/ 의 증명서(solver_v5)를 verify_v4가 수락 조건 8개로 수락해야 함.
      루트 밖 순환 음절(증명서의 cycle): 단어를 하나씩 두어 보는 직접 탐색과 같아야 함(공격 목록은 안 믿음).
      그 밖: 사용자의 공격 목록(끝이 순환 음절인 단어는 빼고), 확정 루트 승, '제자리 단어·되돌려 보내는 단어를 실제로 두어 보는' 짧은 탐색으로
      승/패를 증명할 수 있어야 함.
  대조하지 못한 잎은 실패와 따로 센다.
"""
import collections
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT.parent / 'guopsaem_root' / 'verifier_v3'))
from verify_v3 import conv  # noqa: E402  (규칙: 엔진 표준두음법칙)
sys.path.insert(0, str(HERE))
import route_proof  # noqa: E402  (verify_v4 실행과 수락 조건 확인만 씀)


def main():
    cert = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    q = cert['query']
    qused = frozenset(w.strip() for w in q['used'].split(',') if w.strip())
    words = [w.strip() for w in (HERE / 'source' / '표준사전_어인정_전체단어.txt').read_text(encoding='utf-8-sig').splitlines() if w.strip()]
    assert qused <= set(words) and set(cert['used']) == qused, 'used words'
    first_n = collections.Counter(w[0] for w in words)
    by_first = collections.defaultdict(list)
    for w in words:
        by_first[w[0]].append(w)
    starts = set(by_first)

    def firsts(x):
        a = conv(x)
        return {x} | ({a} if a else set())

    def cont(x):
        return sum(first_n.get(f, 0) for f in firsts(x))

    # 묶음(남은 사전 기준): 시작 꼭짓점들 = 그 첫 음절을 낼 수 있는 '받은 음절의 첫 음절 집합'들, 끝 = 끝 음절의 집합
    remaining = [w for w in words if w not in qused]
    recv = {w[-1] for w in remaining}

    def key(x):
        return tuple(sorted(f for f in firsts(x) if f in starts))
    keys = {key(x) for x in recv}
    srcs_of = collections.defaultdict(list)
    for k in keys:
        for f in k:
            srcs_of[f].append(k)
    group = {}
    gcount = collections.Counter()
    for w in remaining:
        if not srcs_of[w[0]]:
            continue
        g = (tuple(sorted(srcs_of[w[0]])), key(w[-1]))
        group[w] = g
        gcount[g] += 1
    route_words = set((ROOT / 'words_621.txt').read_text(encoding='utf-8').split())

    def tracked(w):
        if w in route_words:
            return True
        g = group.get(w)
        if g is None:
            return False
        srcs, t = g
        loop = t in srcs
        paired = len(srcs) == 1 and srcs[0] != t and ((t,), srcs[0]) in gcount
        return loop or paired or gcount[g] <= 12

    heads = collections.defaultdict(set)
    cur = None
    for line in (HERE / 'source' / '공격단어_목록.txt').read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        m = re.match(r'^\[(.+)\]$', line)
        if m:
            cur = m.group(1)
            continue
        m = re.match(r'^깊이\s*(\d+)\s*:\s*(.*)$', line)
        if m:
            heads[cur] |= {w.strip() for w in m.group(2).split(',') if w.strip()}
    data = json.loads((ROOT / 'site' / 'data.json').read_text(encoding='utf-8'))
    route = {s['s']: s['r'] for s in data['syllables']}

    def playable(x, used):
        return [w for f in firsts(x) for w in by_first.get(f, []) if w not in used]

    def is_loop(x, w):
        return key(w[-1]) == key(x)

    C = frozenset(cert.get('cycle', []))   # 루트 밖 순환 음절: 공격 목록을 믿지 않고 직접 탐색으로만 판정

    def head_ok(h, used):
        """공격 목록 단어 h가 증거가 되려면: 끝 음절이 순환 음절이 아니고, 루트 음절이면 확정 루트 패."""
        y = h[-1]
        if y in C:
            return False
        if y in route:
            return route[y] == 'L' and not (used & route_words)
        return True

    rmemo = {}

    def route_formal(x, used):
        """쓴 루트 단어가 있는 루트 음절: solver_v5 증명서를 (없으면 만들고) verify_v4 수락 조건 8개로 확인한 값, 아니면 None."""
        ru = frozenset(used & route_words)
        k = (x, ru)
        if k not in rmemo:
            d = Path(sys.argv[1] + '.route')
            rec = route_proof.prove(x, ru, d)
            ok = rec.get('result') in ('W', 'L') and route_proof.check(x, ru, rec['result'], d)[0]
            rmemo[k] = rec['result'] if ok else None
        return rmemo[k]

    def pw(x, used, d, back=None):
        """x를 받은 쪽이 이김을 짧게 증명: 공격 목록의 단어가 남아 있음, 확정 루트 승(쓴 루트 단어 없음),
        순환 음절이면 직접 탐색, 또는 제자리 단어나 방금 온 음절(back)로 되돌려 보내는 단어를 두면 상대가 짐(d수까지)."""
        if x in C:
            return cyc(x, used) == 'W'
        if any(head_ok(h, used) for h in heads.get(x, set()) - used):
            return True
        if route.get(x) == 'W' and not (used & route_words):
            return True
        if x in route and used & route_words and route_formal(x, used) == 'W':
            return True
        if d > 0:
            for w in playable(x, used):
                if (is_loop(x, w) or (back is not None and key(w[-1]) == key(back))) and pl(w[-1], used | {w}, d - 1):
                    return True
        return False

    def pl(x, used, d):
        """x를 받은 쪽이 짐을 짧게 증명: 낼 수 있는 모든 단어 각각에 대해 상대가 이김(pw)."""
        if x in C:
            return cyc(x, used) == 'L'
        if x in route and not (used & route_words):
            return route[x] == 'L'
        if x in route and route_formal(x, used) == 'L':
            return True
        return all(pw(w[-1], used | {w}, d - 1, back=x) for w in playable(x, used))

    cyc_memo = {}

    def cyc(x, used):
        """순환 음절 x: 단어를 하나씩 실제로 둔다. 밖으로 나가는 단어는 끝 음절을 pw/pl로 증명."""
        k = (x, used)
        if k not in cyc_memo:
            res, unknown = 'L', False
            for w in playable(x, used):
                y, u = w[-1], used | {w}
                if y in C:
                    c = cyc(y, u)
                elif pw(y, u, 3):
                    c = 'W'
                elif pl(y, u, 3):
                    c = 'L'
                else:
                    c = None
                if c == 'L':
                    res = 'W'
                    break
                if c != 'W':
                    unknown = True
            cyc_memo[k] = None if (res == 'L' and unknown) else res
        return cyc_memo[k]

    nodes = cert['nodes']
    if q['mode'] == 'present' and cont(q['syllable']) < q['shield']:
        # ~X는 보호막 cont(X) 이하에서만 낼 수 있다: 이 질문의 답은 '제시할 수 없음'이어야 한다
        ok = cert.get('illegal') is True and not nodes
        print(json.dumps({'query': q, 'result': '제시할 수 없음', 'cont': cont(q['syllable']), 'verified': ok,
                          'problem_count': 0 if ok else 1,
                          'problems': [] if ok else ['제시할 수 없는 자리인데 승패가 적혀 있음']}, ensure_ascii=False, indent=1))
        sys.exit(0 if ok else 1)
    if cert.get('illegal'):
        print(json.dumps({'query': q, 'verified': False, 'problems': ['낼 수 있는 자리인데 제시 불가로 적혀 있음']}, ensure_ascii=False))
        sys.exit(1)

    def ckey(y, t, u):
        return f"{y}|{t}|{','.join(sorted(u))}"

    def child_of(w, t, u):
        """w를 둔 뒤 자리 key 후보들(같은 묶음·같은 끝 음절의 기록 단어는 서로 바꿔 써도 됨)."""
        if not tracked(w):
            return [ckey(w[-1], t - 1, u)]
        if w in route_words:
            return [ckey(w[-1], t - 1, u | {w})]
        same = [v for v in by_first[w[0]] if group.get(v) == group.get(w) and v[-1] == w[-1] and v not in u and v not in qused]
        return [ckey(w[-1], t - 1, u | {v}) for v in same]

    s = q['shield']
    t0 = max(0, s - 1) if q['mode'] == 'present' else s
    problems, leaves, counts, unchecked = [], collections.Counter(), collections.Counter(), []
    if cert['root'] != ckey(q['syllable'], t0, frozenset()):
        problems.append('시작 자리가 질문과 다름')
    abundant_bad = 0
    for k, n in nodes.items():
        x, t, u = n['x'], n['t'], frozenset(n['used'])
        if k != ckey(x, t, u):
            problems.append(f'{k}: key mismatch')
        counts[n['v']] += 1
        used = qused | u
        if t > 0:
            legal = [w for w in playable(x, used) if cont(w[-1]) >= t]
            if n['v'] == 'W':
                w = n.get('word')
                c = nodes.get(n.get('child'))
                if w not in legal:
                    problems.append(f'{k}: 승 수 {w}는 낼 수 없음')
                elif n.get('child') not in child_of(w, t, u) or not c or c['v'] != 'L':
                    problems.append(f'{k}: {w} 뒤 자리가 패가 아님')
            elif n['v'] == 'L':
                for w in legal:
                    if not tracked(w) and gcount[group.get(w)] <= 12:
                        abundant_bad += 1
                    if not any(nodes.get(ck, {}).get('v') == 'W' for ck in child_of(w, t, u)):
                        problems.append(f'{k}: {w} 뒤 자리가 승으로 적혀 있지 않음')
                        break
            else:
                problems.append(f'{k}: 미정')
            continue
        if x in route and n['why'].startswith('루트'):
            if used & route_words:
                ok, msg = route_proof.check(x, used & route_words, n['v'], Path(sys.argv[1] + '.route'))
                leaves['루트(쓴 루트 단어 있음): solver_v5 증명서 verify_v4 수락' if ok else '루트(쓴 루트 단어 있음): 대조 안 됨'] += 1
                if not ok:
                    unchecked.append(f'{k} ({msg})')
            elif route[x] == n['v']:
                leaves['루트 확정 결과와 같음'] += 1
            else:
                problems.append(f'{k}: 루트 확정 결과 {route[x]}와 다름')
        elif x in C:
            ok = cyc(x, used) == n['v']
            leaves['순환 음절: 직접 탐색으로 같음' if ok else '순환 음절: 대조 안 됨'] += 1
            if not ok:
                unchecked.append(k)
        elif n['v'] == 'W':
            ok = pw(x, used, 4)
            leaves['승: 공격 목록/제자리 단어로 증명' if ok else '승: 대조 안 됨'] += 1
            if not ok:
                unchecked.append(k)
        elif n['v'] == 'L':
            if not playable(x, used):
                leaves['패: 낼 단어 없음'] += 1
            else:
                ok = pl(x, used, 4)
                leaves['패: 공격 목록/제자리 단어로 증명' if ok else '패: 대조 안 됨'] += 1
                if not ok:
                    unchecked.append(k)
        else:
            problems.append(f'{k}: 잎이 미정')
    if abundant_bad:
        problems.append(f'기록 안 한 단어 중 묶음이 12개 이하인 것 {abundant_bad}개')
    rv = nodes.get(cert['root'], {}).get('v')
    res = {'present': {'L': '제시한 쪽 승', 'W': '제시한 쪽 패'}, 'receive': {'W': '받은 쪽 승', 'L': '받은 쪽 패'}}[q['mode']].get(rv, '미정')
    report = {'query': q, 'result': res, 'nodes': len(nodes), 'values': dict(counts), 'leaves': dict(leaves),
              'problem_count': len(problems), 'problems': problems[:20], 'unchecked_leaves': unchecked[:20],
              'verified': not problems and not any('대조 안 됨' in kk for kk in leaves)}
    print(json.dumps(report, ensure_ascii=False, indent=1))
    sys.exit(0 if not problems else 1)


if __name__ == '__main__':
    main()
