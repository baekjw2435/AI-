#!/usr/bin/env python3
"""Independent end-to-end check (reviewer's own code; shares nothing with the repo's model).

1. Word-level brute force straight from the rule text.
2. Pipeline: ModelV3.numeric_input -> solver_v5 -> v4 proof -> C++ verify_v4 (and Python verify_v4 on a sample).
3. Random mutation fuzz: any ACCEPTED mutated proof must still report the true value.
"""
import gzip, json, os, random, subprocess, sys, hashlib
from functools import lru_cache
from pathlib import Path

REV = Path(sys.argv[1]); BIN = Path(sys.argv[2]); WORK = Path(sys.argv[3])
NDICT = int(sys.argv[4]); SEED = int(sys.argv[5]); FUZZ = int(sys.argv[6])
sys.path.insert(0, str(REV / 'guopsaem_root' / 'verifier_v3'))
from verify_v3 import ModelV3, VerificationError  # only used to build solver input

CHO = 'ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ'
JUNG = 'ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ'


def split(s):
    o = ord(s) - 0xAC00
    return CHO[o // 588], JUNG[(o % 588) // 28], o % 28


def join(c, j, f):
    return chr(0xAC00 + CHO.index(c) * 588 + JUNG.index(j) * 28 + f)


def alt(s):
    """my own reading of the rule text"""
    c, j, f = split(s)
    if c == 'ㄹ' and j in 'ㅑㅕㅖㅛㅠㅣ':
        return join('ㅇ', j, f)
    if c == 'ㄹ' and j in 'ㅏㅐㅗㅚㅜㅡ':
        return join('ㄴ', j, f)
    if c == 'ㄴ' and j in 'ㅕㅛㅠㅣ':
        return join('ㅇ', j, f)
    return None


def brute(words, start, used0=()):
    n = len(words)
    firsts = [w[0] for w in words]
    lasts = [w[-1] for w in words]

    @lru_cache(maxsize=None)
    def win(x, mask):
        ok = {x, alt(x)}
        for i in range(n):
            if not (mask >> i) & 1 and firsts[i] in ok:
                if not win(lasts[i], mask | (1 << i)):
                    return True
        return False
    mask = 0
    for w in used0:
        mask |= 1 << words.index(w)
    return win(start, mask)


SPECIAL = list('락낙려녀여룽눙리니이라나료뇨요랴야')
PLAIN = list('가다마바사자')
FILL = list('거너더러머버서어저처커터퍼허')


def random_dict(rng):
    syl = rng.sample(SPECIAL, rng.randint(3, 6)) + rng.sample(PLAIN, rng.randint(0, 1))
    n = rng.randint(8, 18)
    words = set()
    tries = 0
    while len(words) < n and tries < 200:
        tries += 1
        a, b = rng.choice(syl), rng.choice(syl)
        if rng.random() < 0.15:
            b = a
        if rng.random() < 0.2:
            w = a + b if a != b else a + rng.choice(FILL) + b
        else:
            w = a + rng.choice(FILL) + b
        words.add(w)
    return sorted(words), syl


def run_pipeline(words, pos, tag):
    d = WORK / tag
    d.mkdir(parents=True, exist_ok=True)
    dic = d / 'dict.txt'
    dic.write_text('\n'.join(words) + '\n', encoding='utf-8')
    m = ModelV3(dic.read_bytes(), len(words))
    try:
        c, k, _ = m.position(pos)
    except VerificationError:
        return None
    (d / 'pos.json').write_text(json.dumps(pos, ensure_ascii=False), encoding='utf-8')
    (d / 'in.txt').write_bytes(m.numeric_input(c, k))
    proof = d / 'p.gz'
    if proof.exists():
        proof.unlink()
    s = subprocess.run([str(BIN / 'solver_v5'), str(d / 'in.txt'), '--seconds', '20', '--tt-mb', '1', '--threads', '1',
                        '--proof', str(proof), '--proof-format', 'v4', '--selfcheck', '1'], capture_output=True, text=True)
    sol = json.loads(s.stdout.strip().splitlines()[-1]) if s.stdout.strip() else {'result': 'error', 'err': s.stderr}
    if sol.get('result') not in ('win', 'loss') or sol.get('proof_error'):
        return {'solver': sol}
    v = verify(d, len(words))
    return {'solver': sol, 'verify': v, 'dir': d}


def verify(d, n, proof=None, py=False):
    cmd = ([sys.executable, str(REV / 'guopsaem_root' / 'verifier_v4' / 'verify_v4.py')] if py else [str(BIN / 'verify_v4')])
    cmd += ['--dictionary', str(d / 'dict.txt'), '--expected-word-count', str(n), '--position', str(d / 'pos.json'),
            '--proof', str(proof or d / 'p.gz'), '--input', str(d / 'in.txt')]
    r = subprocess.run(cmd, capture_output=True, text=True)
    try:
        j = json.loads(r.stdout)
    except ValueError:
        j = {'verified': False, 'error': 'unparsable: ' + (r.stdout + r.stderr)[-200:]}
    j['exit'] = r.returncode
    return j


def mutate(rng, lines):
    """lines: list of bytes (header + nodes). Returns mutated list."""
    L = [bytearray(x) for x in lines]
    kind = rng.randrange(9)
    i = rng.randrange(1, len(L)) if len(L) > 1 else 0
    if kind == 0:      # flip a result letter
        L[i] = bytearray(L[i].replace(b'"W"', b'"L"') if b'"W"' in L[i] else L[i].replace(b'"L"', b'"W"'))
    elif kind == 1:    # change one digit
        pos = [p for p, ch in enumerate(L[i]) if 48 <= ch <= 57]
        if pos:
            p = rng.choice(pos); L[i][p] = 48 + rng.randrange(10)
    elif kind == 2:    # drop a move
        node = json.loads(L[i])
        if node.get('m'):
            node['m'].pop(rng.randrange(len(node['m'])))
            L[i] = bytearray(json.dumps(node, separators=(',', ':')).encode())
    elif kind == 3:    # redirect a child id to another earlier node
        node = json.loads(L[i])
        if node.get('m') and node['id'] > 0:
            node['m'][rng.randrange(len(node['m']))][1] = rng.randrange(node['id'])
            L[i] = bytearray(json.dumps(node, separators=(',', ':')).encode())
    elif kind == 4:    # change a move group
        node = json.loads(L[i]); hdr = json.loads(L[0])
        if node.get('m'):
            node['m'][rng.randrange(len(node['m']))][0] = rng.randrange(hdr['groups'])
            L[i] = bytearray(json.dumps(node, separators=(',', ':')).encode())
    elif kind == 5:    # make a node a moveless leaf with a random result
        node = json.loads(L[i]); node['m'] = []; node['r'] = rng.choice('WL')
        L[i] = bytearray(json.dumps(node, separators=(',', ':')).encode())
    elif kind == 6:    # flip root result and keep only one move / or all
        node = json.loads(L[-1]); node['r'] = 'W' if node['r'] == 'L' else 'L'
        if node['m'] and rng.random() < 0.5:
            node['m'] = [rng.choice(node['m'])]
        L[-1] = bytearray(json.dumps(node, separators=(',', ':')).encode())
    elif kind == 7:    # truncate: new root = an earlier node (header root patched)
        if len(L) > 2:
            cut = rng.randrange(2, len(L))
            L = L[:cut]
            hdr = json.loads(L[0]); hdr['root'] = cut - 2
            L[0] = bytearray(json.dumps(hdr, separators=(',', ':')).encode())
    else:              # random byte change
        p = rng.randrange(len(L[i])); L[i][p] = rng.randrange(32, 127)
    return [bytes(x) for x in L]


def main():
    rng = random.Random(SEED)
    stats = {'dicts': 0, 'positions': 0, 'accepted': 0, 'mismatch': 0, 'not_decided': 0, 'shared_dicts': 0,
             'py_checked': 0, 'py_disagree': 0, 'fuzz': 0, 'fuzz_accepted': 0, 'fuzz_wrong_accepted': 0, 'multi_node_proofs': 0}
    problems = []
    fuzz_pool = []
    for di in range(NDICT):
        words, syl = random_dict(rng)
        if len(words) < 3:
            continue
        stats['dicts'] += 1
        m = ModelV3(('\n'.join(words)).encode(), len(words))
        if any(m.shared):
            stats['shared_dicts'] += 1
        starts = rng.sample(syl, min(3, len(syl)))
        for si, s in enumerate(starts):
            pos = {'initial_syllable': s, 'history': []}
            # sometimes a random legal prefix, sometimes initially used words
            used = []
            if rng.random() < 0.4:
                cur = s
                for _ in range(rng.randint(1, 3)):
                    ok = {cur, alt(cur)}
                    cand = [w for w in words if w not in used and w[0] in ok]
                    if not cand:
                        break
                    w = rng.choice(cand); used.append(w); cur = w[-1]
                pos['history'] = list(used)
            pre = []
            if rng.random() < 0.2:
                rest = [w for w in words if w not in used]
                pre = rng.sample(rest, min(len(rest), rng.randint(1, 2)))
                pos['initial_used_words'] = pre
            cur = pos['history'][-1][-1] if pos['history'] else s
            truth = brute(tuple(words), cur, tuple(used) + tuple(pre))
            res = run_pipeline(words, pos, f'd{di}_{si}')
            if res is None:
                continue
            stats['positions'] += 1
            if 'verify' not in res:
                stats['not_decided'] += 1
                problems.append(('not decided', words, pos, res['solver']))
                continue
            v = res['verify']
            want = 'W' if res['solver']['result'] == 'win' else 'L'
            acc = v.get('exit') == 0 and v.get('verified') is True and v.get('result_for_player_to_move') == want \
                and v.get('state_storage') == 'deflate-exact'
            if not acc:
                problems.append(('rejected', words, pos, v))
                continue
            stats['accepted'] += 1
            if (want == 'W') != truth:
                stats['mismatch'] += 1
                problems.append(('WRONG VERDICT ACCEPTED', words, pos, want, truth))
            if rng.random() < 0.15:
                pv = verify(res['dir'], len(words), py=True)
                stats['py_checked'] += 1
                if pv.get('verified') is not True or pv.get('result_for_player_to_move') != want:
                    stats['py_disagree'] += 1
                    problems.append(('python verifier disagrees', words, pos, pv))
            if v.get('certificate_nodes', 0) >= 4:
                stats['multi_node_proofs'] += 1
                fuzz_pool.append((res['dir'], len(words), truth))
    # mutation fuzz
    frng = random.Random(SEED + 1)
    for _ in range(FUZZ):
        if not fuzz_pool:
            break
        d, n, truth = frng.choice(fuzz_pool)
        lines = gzip.open(d / 'p.gz', 'rb').read().split(b'\n')
        if lines and lines[-1] == b'':
            lines.pop()
        orig = list(lines)
        for _k in range(frng.randint(1, 3)):
            try:
                lines = mutate(frng, lines)
            except (ValueError, KeyError, TypeError, IndexError):
                pass
        if lines == orig:
            continue
        mp = d / 'mut.gz'
        with gzip.open(mp, 'wb') as f:
            f.write(b'\n'.join(lines) + b'\n')
        v = verify(d, n, proof=mp)
        stats['fuzz'] += 1
        if v.get('exit') == 0 and v.get('verified') is True:
            stats['fuzz_accepted'] += 1
            if (v.get('result_for_player_to_move') == 'W') != truth:
                stats['fuzz_wrong_accepted'] += 1
                problems.append(('FUZZ: WRONG VERDICT ACCEPTED', str(d), [x.decode('utf-8', 'replace') for x in lines][:50]))
    print(json.dumps(stats, ensure_ascii=False))
    for p in problems[:10]:
        print(json.dumps(p, ensure_ascii=False, default=str)[:1500])


if __name__ == '__main__':
    main()
