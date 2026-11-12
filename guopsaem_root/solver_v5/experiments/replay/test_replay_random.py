#!/usr/bin/env python3
"""Random check of solver_v5_replay: a replayed position must still get the true value, whatever the old file is.

usage: test_replay_random.py SOLVER REPLAY_SOLVER VERIFY_V4 WORKDIR DICTS SEED [lib]

For random small dictionaries (many ㄹ/ㄴ/ㅇ syllables, so shared groups occur):
  1. solve 'syllable s received' with SOLVER and keep its v4 certificate (the old strategy);
  2. take the same position with one or two words already used, or after one legal move, and run
     REPLAY_SOLVER --replay OLD --selfcheck 1 with a tiny stuck budget;
     every third time the old certificate is one of ANOTHER start syllable (a useless hint);
     with the last argument 'lib', the certificates of the other start syllables are also given as --replay-lib
     (every second time under a WRONG vertex number, which must be harmless too);
  3. the new certificate must pass VERIFY_V4 with the solver's result, and that result must equal a word-level
     brute force written from the rule text (no model code).
Replay may only change how fast the result is found, never the result.
"""
import json
import random
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

SOLVER, REPLAY, VERIFY, WORK = sys.argv[1], sys.argv[2], sys.argv[3], Path(sys.argv[4])
NDICT, SEED = int(sys.argv[5]), int(sys.argv[6])
USE_LIB = len(sys.argv) > 7 and sys.argv[7] == 'lib'
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'verifier_v3'))
from verify_v3 import ModelV3, VerificationError  # noqa: E402  (only to write solver inputs)

CHO = 'ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ'
JUNG = 'ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ'
SPECIAL = list('락낙려녀여룽눙리니이라나료뇨요랴야')
PLAIN = list('가다마바사자')
FILL = list('거너더러머버서어저처커터퍼허')


def alt(s):
    o = ord(s) - 0xAC00
    c, j, f = CHO[o // 588], JUNG[(o % 588) // 28], o % 28
    def join(c2):
        return chr(0xAC00 + CHO.index(c2) * 588 + JUNG.index(j) * 28 + f)
    if c == 'ㄹ' and j in 'ㅑㅕㅖㅛㅠㅣ':
        return join('ㅇ')
    if c == 'ㄹ' and j in 'ㅏㅐㅗㅚㅜㅡ':
        return join('ㄴ')
    if c == 'ㄴ' and j in 'ㅕㅛㅠㅣ':
        return join('ㅇ')
    return None


def brute(words, start, used):
    firsts, lasts, n = [w[0] for w in words], [w[-1] for w in words], len(words)

    @lru_cache(maxsize=None)
    def win(x, mask):
        ok = {x, alt(x)}
        return any(not (mask >> i) & 1 and firsts[i] in ok and not win(lasts[i], mask | (1 << i)) for i in range(n))
    mask = 0
    for w in used:
        mask |= 1 << words.index(w)
    return win(start, mask)


def random_dict(rng):
    syl = rng.sample(SPECIAL, rng.randint(3, 6)) + rng.sample(PLAIN, rng.randint(0, 1))
    words = set()
    for _ in range(200):
        if len(words) >= rng.randint(9, 18):
            break
        a, b = rng.choice(syl), rng.choice(syl)
        if rng.random() < 0.15:
            b = a
        words.add(a + b if a != b and rng.random() < 0.2 else a + rng.choice(FILL) + b)
    return sorted(words), syl


def last_json(text):
    lines = text.strip().splitlines()
    return json.loads(lines[-1]) if lines else {'result': 'error'}


def main():
    rng = random.Random(SEED)
    WORK.mkdir(parents=True, exist_ok=True)
    st = {'dicts': 0, 'replays': 0, 'accepted': 0, 'wrong': 0, 'not_accepted': 0, 'foreign_hint': 0, 'root_by_replay': 0,
          'stuck_states': 0, 'local_solved': 0, 'replay_nodes': 0, 'selfchecks': 0}
    problems = []
    for di in range(NDICT):
        words, syl = random_dict(rng)
        if len(words) < 5:
            continue
        dic = WORK / 'dict.txt'
        dic.write_text('\n'.join(words) + '\n', encoding='utf-8')
        m = ModelV3(dic.read_bytes(), len(words))
        olds = {}
        for s in rng.sample(syl, min(3, len(syl))):
            pos = {'initial_syllable': s, 'history': []}
            try:
                c, k, _ = m.position(pos)
            except VerificationError:
                continue
            (WORK / f'old_{s}.in').write_bytes(m.numeric_input(c, k))
            r = subprocess.run([SOLVER, str(WORK / f'old_{s}.in'), '--seconds', '20', '--tt-mb', '1', '--proof', str(WORK / f'old_{s}.gz'),
                                '--proof-format', 'v4'], capture_output=True, text=True)
            if last_json(r.stdout).get('result') in ('win', 'loss') and (WORK / f'old_{s}.gz').exists():
                olds[s] = WORK / f'old_{s}.gz'
        if not olds:
            continue
        st['dicts'] += 1
        for s in list(olds):
            # a nearby position: words missing, or one move made
            pos = {'initial_syllable': s, 'history': []}
            used, cur = [], s
            kind = rng.randrange(3)
            if kind == 0:
                pos['initial_used_words'] = used = rng.sample(words, rng.randint(1, 2))
            else:
                cand = [w for w in words if w[0] in {s, alt(s)}]
                if not cand:
                    continue
                w = rng.choice(cand)
                pos['history'], used, cur = [w], [w], w[-1]
                if kind == 2:
                    rest = [x for x in words if x != w]
                    extra = rng.sample(rest, 1)
                    pos['initial_used_words'] = extra
                    used = used + extra
            try:
                c, k, _ = m.position(pos)
            except VerificationError:
                continue
            hint = olds[s]
            if st['replays'] % 3 == 2 and len(olds) > 1:
                hint = olds[rng.choice([x for x in olds if x != s])]
                st['foreign_hint'] += 1
            (WORK / 'pos.json').write_text(json.dumps(pos, ensure_ascii=False), encoding='utf-8')
            (WORK / 'new.in').write_bytes(m.numeric_input(c, k))
            proof = WORK / 'new.gz'
            if proof.exists():
                proof.unlink()
            libs = []
            if USE_LIB:
                for j, (ls, lp) in enumerate(olds.items()):
                    v = m.vertex_of(ls) if (st['replays'] + j) % 2 == 0 else rng.randrange(len(m.keys))
                    libs += ['--replay-lib', f'{v}={lp}']
            r = subprocess.run([REPLAY, str(WORK / 'new.in'), '--seconds', '20', '--tt-mb', '1', '--proof', str(proof), '--proof-format', 'v4',
                                '--replay', str(hint), '--replay-stuck-nodes', str(rng.choice([0, 1024, 200000])), '--selfcheck', '1'] + libs,
                               capture_output=True, text=True)
            sol = last_json(r.stdout)
            st['replays'] += 1
            truth = brute(tuple(words), cur, tuple(used))
            if sol.get('result') not in ('win', 'loss') or sol.get('proof_error') or not proof.exists():
                st['not_accepted'] += 1
                problems.append(('no certificate', words, pos, sol, r.stderr[-300:]))
                continue
            v = subprocess.run([VERIFY, '--dictionary', str(dic), '--expected-word-count', str(len(words)), '--position', str(WORK / 'pos.json'),
                                '--proof', str(proof), '--input', str(WORK / 'new.in')], capture_output=True, text=True)
            try:
                vj = json.loads(v.stdout)
            except ValueError:
                vj = {'verified': False}
            want = 'W' if sol['result'] == 'win' else 'L'
            if v.returncode != 0 or vj.get('verified') is not True or vj.get('result_for_player_to_move') != want:
                st['not_accepted'] += 1
                problems.append(('rejected', words, pos, vj))
                continue
            st['accepted'] += 1
            if (want == 'W') != truth:
                st['wrong'] += 1
                problems.append(('WRONG VERDICT ACCEPTED', words, pos, want, truth))
            st['root_by_replay'] += sol.get('replay_root', -2) in (0, 1)
            st['stuck_states'] += sum(sol.get(k, 0) for k in ('replay_stuck_old_leaf', 'replay_stuck_witness_gone', 'replay_stuck_witness_static',
                                                             'replay_stuck_witness_refuted', 'replay_stuck_new_move'))
            st['local_solved'] += sol.get('replay_local_solved', 0)
            st['lib_tries'] = st.get('lib_tries', 0) + sol.get('replay_lib_tries', 0)
            st['lib_solved'] = st.get('lib_solved', 0) + sol.get('replay_lib_solved', 0)
            st['replay_nodes'] += sol.get('replay_nodes', 0)
            st['selfchecks'] += sol.get('selfchecks', 0)
    print(json.dumps(st, ensure_ascii=False))
    for p in problems[:8]:
        print(json.dumps(p, ensure_ascii=False, default=str)[:1200])


if __name__ == '__main__':
    main()
