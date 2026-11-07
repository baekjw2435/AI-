#!/usr/bin/env python3
"""Independent checker for pairing-proof-v1 certificates (2026-11-07).

This is a different kind of proof from route-proof-v4. A v4 certificate lists the game tree move by move.
A pairing certificate lists no tree. It gives a strategy for the player NOT to move, together with the
conditions that make it work against every reply.

Claim: the player to move in the given position LOSES.

Certificate: a set S of vertices that contains the current vertex, and a list of disjoint word pairs.
A vertex is the set of first syllables allowed after receiving a syllable, named as verify_v3 names it
(e.g. "낙/락"). Conditions, checked on the remaining words. In mode "raw" these are the actual unused
words. In mode "canonical" they are the canonical counts of verify_v3.ModelV3.normalize.
 1. Every word in a pair is an unused dictionary word, and no word is in two pairs.
 2. A word group (verify_v3's grouping) is used at most as many times as its count.
 3. Every word that can be played from a vertex of S is in a pair. In raw mode that means every unused
    word. In canonical mode it means the group's whole canonical count.
 4. Take any pair {a, b} and any word x of it that can be played from S, and let y be the other word.
    Then y can be played right after x (its first syllable is allowed after x's last syllable), and
    y's last syllable leads back into S.
Why this proves the claim. The player to move (A) stands on a vertex of S, and every remaining word
playable from S is paired with a remaining partner. A's word x is playable from S, so its partner y is
still there. The other player (B) answers with y, which is legal by condition 4 and puts A back on S.
Pairs are disjoint and consumed whole, so after each answer the same holds again. A therefore always
stands on S and B always has an answer. Words run out, so A is the one who finally has no move.
In raw mode this rests on the game rules alone. In canonical mode the argument is applied to the
canonical game. Its value equals the real position's by the canonical-form equivalence that
route-proof-v3/v4 also rely on.

A certificate that cannot be found proves nothing: it is not evidence that the player to move wins.

Imports from verify_v3.py only (the rule, the dictionary/position parsing, the canonical form). No solver
or finder code is used.
usage: verify_pairing.py --dictionary D --expected-word-count N --position POS.json --certificate CERT.json
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'verifier_v3'))
from verify_v3 import ModelV3, VerificationError, require  # noqa: E402

FORMAT = 'pairing-proof-v1'


def check_groups(model, current, counts, S, group_pairs):
    """Group-level core. counts: the remaining count of each group (raw or canonical). S: set of vertex ids.
    group_pairs: list of (group a, group b) - one entry per word pair. Raises VerificationError if any
    condition fails; returns a small summary otherwise."""
    require(current in S, 'the current vertex is not in S')
    playable = [any(s in S for s in model.edges[g][0]) for g in range(len(model.edges))]
    use = Counter()
    for a, b in group_pairs:
        use[a] += 1
        use[b] += 1
    for g, n in use.items():
        require(n <= counts[g], f'group {g} used {n} times but only {counts[g]} remain')
    for g, c in enumerate(counts):
        if c and playable[g]:
            require(use[g] == c, f'group {g} ({c} remaining) can be played from S but only {use[g]} of its words are paired')
    for a, b in group_pairs:
        for x, y in ((a, b), (b, a)):
            if playable[x]:
                require(model.edges[x][1] in model.edges[y][0],
                        f'pair ({x}, {y}): the partner cannot be played after group {x}')
                require(model.edges[y][1] in S, f'pair ({x}, {y}): the partner does not lead back into S')
    return {'pairs': len(group_pairs), 'S_size': len(S),
            'covered_words': sum(c for g, c in enumerate(counts) if c and playable[g])}


def verify(dictionary_path, expected_word_count, position_path, certificate_path):
    dictionary_bytes = Path(dictionary_path).read_bytes()
    position_bytes = Path(position_path).read_bytes()
    certificate_bytes = Path(certificate_path).read_bytes()
    model = ModelV3(dictionary_bytes, expected_word_count)
    cert = json.loads(certificate_bytes.decode('utf-8'))
    require(isinstance(cert, dict) and cert.get('format') == FORMAT, f'not a {FORMAT} certificate')
    require(cert.get('claim') == 'player_to_move_loses', 'unknown claim')
    mode = cert.get('mode')
    require(mode in ('raw', 'canonical'), 'mode must be raw or canonical')
    dsha = hashlib.sha256(dictionary_bytes).hexdigest()
    psha = hashlib.sha256(position_bytes).hexdigest()
    require(cert.get('dictionary_sha256') == dsha, 'dictionary hash mismatch')
    require(cert.get('position_sha256') == psha, 'position hash mismatch')
    current, raw_counts, used = model.position(json.loads(position_bytes.decode('utf-8')))
    if mode == 'raw':
        counts = raw_counts
    else:
        counts, static = model.normalize(current, raw_counts)
        require(static == -1, 'the canonical form already decides this position (static); no pairing needed')
    names = {name: v for v, name in enumerate(model.names)}
    S_names = cert.get('S')
    require(isinstance(S_names, list) and S_names, 'S must be a non-empty list of vertex names')
    require(len(set(S_names)) == len(S_names), 'S lists a vertex twice')
    for n in S_names:
        require(isinstance(n, str) and n in names, f'unknown vertex name {n!r}')
    S = {names[n] for n in S_names}
    pairs = cert.get('pairs')
    require(isinstance(pairs, list), 'pairs must be a list')
    seen = set()
    group_pairs = []
    for i, p in enumerate(pairs):
        require(isinstance(p, list) and len(p) == 2 and all(isinstance(w, str) for w in p), f'pair {i} is not two words')
        for w in p:
            require(w in model.word_group_key, f'pair {i}: {w!r} is not a dictionary word')
            require(w not in used, f'pair {i}: {w} was already played')
            require(w not in seen, f'pair {i}: {w} is in two pairs')
            seen.add(w)
        group_pairs.append((model.word_group(p[0]), model.word_group(p[1])))
    summary = check_groups(model, current, counts, S, group_pairs)
    return {
        'format': FORMAT, 'verified': True, 'claim': 'player_to_move_loses', 'mode': mode,
        'current_vertex': model.names[current], **summary,
        'dictionary_sha256': dsha, 'position_sha256': psha,
        'certificate_sha256': hashlib.sha256(certificate_bytes).hexdigest(),
        'note': 'separate proof method from route-proof-v4: a pairing strategy, not a game tree',
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--dictionary', required=True)
    ap.add_argument('--expected-word-count', type=int, required=True)
    ap.add_argument('--position', required=True)
    ap.add_argument('--certificate', required=True)
    a = ap.parse_args()
    try:
        r = verify(a.dictionary, a.expected_word_count, a.position, a.certificate)
    except (VerificationError, ValueError, KeyError, OSError) as e:
        print(json.dumps({'format': FORMAT, 'verified': False, 'error': str(e)}, ensure_ascii=False))
        sys.exit(1)
    print(json.dumps(r, ensure_ascii=False))


if __name__ == '__main__':
    main()
