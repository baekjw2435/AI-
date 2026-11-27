#!/usr/bin/env python3
"""Pairing proofs against exhaustive search on small random dictionaries (2026-11-07).

For random dictionaries of 5-13 words over syllables with initial-sound pairs (라/나, 락/낙, 려/여, 녀/여,
류/유, 뉴/유, 리/이, 니/이), and positions after 0-3 legal words:
  * every position is solved by plain exhaustive search on the raw words (its own small implementation of
    the rule: after receiving X, a word may start with X or conv(X); no word twice);
  * the finder (CP-SAT) looks for a raw and a canonical pairing; every certificate it returns must pass
    verify_pairing.py, and every position a certificate proves must be a loss for the player to move;
  * mutated certificates (a pair removed, a word swapped, S changed, partners exchanged) and random
    certificates are checked too: whenever the verifier accepts one, the position must be a loss.
Reports how many losses each mode proves.
usage: test_pairing.py [DICTIONARIES] [SEED] [MIN_WORDS] [MAX_WORDS]
"""
import hashlib
import json
from functools import lru_cache
from pathlib import Path
import random
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[0] / 'verifier_v3'))
from verify_v3 import ModelV3, VerificationError, conv  # noqa: E402
import find_pairing  # noqa: E402
import verify_pairing  # noqa: E402

SYL = ['라', '나', '락', '낙', '려', '여', '녀', '류', '유', '뉴', '리', '이', '니', '가', '다']
FILL = ['고', '구', '기', '도', '두', '디', '보', '부', '소', '수']


def random_dictionary(rng, lo=5, hi=13):
    sy = rng.sample(SYL, rng.randint(3, 6))
    words = set()
    for _ in range(rng.randint(lo, hi)):
        for _try in range(20):
            w = rng.choice(sy) + ''.join(rng.choice(FILL) for _ in range(rng.randint(0, 2))) + rng.choice(sy)
            if w not in words:
                words.add(w)
                break
    return sorted(words)


def exhaustive(words):
    idx = {w: i for i, w in enumerate(words)}

    @lru_cache(maxsize=None)
    def win(received, used):
        allowed = {received, conv(received)}
        for w in words:
            i = idx[w]
            if not used >> i & 1 and w[0] in allowed:
                if not win(w[-1], used | 1 << i):
                    return True
        return False
    return win, idx


def positions(rng, words):
    syls = sorted({w[0] for w in words} | {w[-1] for w in words})
    out = []
    for _ in range(4):
        init = rng.choice(syls)
        hist, cur = [], init
        for _ply in range(rng.randint(0, 3)):
            opts = [w for w in words if w not in hist and w[0] in {cur, conv(cur)}]
            if not opts:
                break
            w = rng.choice(opts)
            hist.append(w)
            cur = w[-1]
        out.append({'initial_syllable': init, 'history': hist})
    return out


def verify_obj(tmp, cert):
    p = Path(tmp) / 'cert.json'
    p.write_text(json.dumps(cert, ensure_ascii=False), encoding='utf-8')
    try:
        verify_pairing.verify(Path(tmp) / 'dict.txt', 0, Path(tmp) / 'pos.json', p)
        return True
    except VerificationError:
        return False


def mutations(rng, cert, words, names):
    out = []
    pairs = cert['pairs']
    if pairs:
        c = json.loads(json.dumps(cert)); c['pairs'].pop(rng.randrange(len(pairs))); out.append(c)
        c = json.loads(json.dumps(cert)); i = rng.randrange(len(pairs)); c['pairs'][i][rng.randrange(2)] = rng.choice(words); out.append(c)
        if len(pairs) > 1:
            c = json.loads(json.dumps(cert)); i, j = rng.sample(range(len(pairs)), 2)
            c['pairs'][i][1], c['pairs'][j][1] = c['pairs'][j][1], c['pairs'][i][1]; out.append(c)
    if len(cert['S']) > 1:
        c = json.loads(json.dumps(cert)); c['S'].pop(rng.randrange(len(c['S']))); out.append(c)
    extra = [n for n in names if n not in cert['S']]
    if extra:
        c = json.loads(json.dumps(cert)); c['S'].append(rng.choice(extra)); out.append(c)
    return out


def main():
    ndict = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    rng = random.Random(int(sys.argv[2]) if len(sys.argv) > 2 else 1)
    lo = int(sys.argv[3]) if len(sys.argv) > 3 else 5
    hi = int(sys.argv[4]) if len(sys.argv) > 4 else 13
    stats = dict(positions=0, losses=0, static=0, raw_found=0, canon_found=0, either=0, losses_core=0,
                 core_raw_found=0, core_canon_found=0, core_either=0,
                 mutated=0, mutated_accepted=0, random_certs=0, random_accepted=0)
    with tempfile.TemporaryDirectory() as tmp:
        for _ in range(ndict):
            words = random_dictionary(rng, lo, hi)
            dbytes = ('\n'.join(words) + '\n').encode('utf-8')
            (Path(tmp) / 'dict.txt').write_bytes(dbytes)
            model = ModelV3(dbytes, 0)
            win, idx = exhaustive(tuple(words))
            for pos in positions(rng, words):
                pbytes = json.dumps(pos, ensure_ascii=False).encode('utf-8')
                (Path(tmp) / 'pos.json').write_bytes(pbytes)
                received = pos['history'][-1][-1] if pos['history'] else pos['initial_syllable']
                used = sum(1 << idx[w] for w in pos['history'])
                lose = not win(received, used)
                stats['positions'] += 1
                stats['losses'] += lose
                current, raw, usedset = model.position(pos)
                canon, static = model.normalize(current, raw)
                if static != -1:
                    stats['static'] += 1
                    assert static == (0 if lose else 1), 'canonical static label disagrees with exhaustive search'
                elif lose:
                    stats['losses_core'] += 1
                found_any = False
                for mode, counts in (('raw', raw), ('canonical', canon)):
                    if mode == 'canonical' and static != -1:
                        continue
                    r = find_pairing.find(model, current, counts, seconds=5.0)
                    if r['status'] != 'found':
                        continue
                    cert = find_pairing.certificate(model, dbytes, pbytes, mode, r['S'], r['group_pairs'])
                    assert verify_obj(tmp, cert), f'finder output rejected by the verifier: {words} {pos} {cert}'
                    assert lose, f'pairing "proves" a loss but the player to move wins: {words} {pos} {cert}'
                    stats['raw_found' if mode == 'raw' else 'canon_found'] += 1
                    if static == -1:
                        stats['core_raw_found' if mode == 'raw' else 'core_canon_found'] += 1
                    found_any = True
                    for c in mutations(rng, cert, words, model.names):
                        stats['mutated'] += 1
                        if verify_obj(tmp, c):
                            stats['mutated_accepted'] += 1
                            assert lose, f'mutated certificate accepted for a winning position: {words} {pos} {c}'
                stats['either'] += found_any
                if static == -1:
                    stats['core_either'] += found_any
                # random certificates
                for _r in range(3):
                    unused = [w for w in words if w not in usedset]
                    rng.shuffle(unused)
                    k = rng.randint(0, len(unused) // 2)
                    S = rng.sample(model.names, rng.randint(1, len(model.names)))
                    if model.names[current] not in S and rng.random() < 0.8:
                        S.append(model.names[current])
                    cert = {'format': 'pairing-proof-v1', 'claim': 'player_to_move_loses',
                            'mode': rng.choice(['raw', 'canonical']),
                            'dictionary_sha256': hashlib.sha256(dbytes).hexdigest(),
                            'position_sha256': hashlib.sha256(pbytes).hexdigest(),
                            'S': S, 'pairs': [[unused[2 * i], unused[2 * i + 1]] for i in range(k)]}
                    stats['random_certs'] += 1
                    if verify_obj(tmp, cert):
                        stats['random_accepted'] += 1
                        assert lose, f'random certificate accepted for a winning position: {words} {pos} {cert}'
    print(json.dumps(stats, ensure_ascii=False))
    print('all checks passed')


if __name__ == '__main__':
    main()
