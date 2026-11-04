#!/usr/bin/env python3
"""Brute-force check of the v3 model against the plain word game.

For random small dictionaries built from syllables where the one-way rule matters
(락/낙, 려/여/녀, 룽/눙, ...), every random position is solved twice:
  * raw: words and syllables only, exactly the rule text (no model, no reduction);
  * model: ModelV3 states, re-normalized after every move.
It also checks every static label of the reduced state against the raw value.
Usage: test_v3_bruteforce.py [DICTIONARIES] [SEED]
"""
from functools import lru_cache
from pathlib import Path
import random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_v3 import ModelV3, conv  # noqa: E402

POOL = list("락낙라나녀여려룽눙렌넨가다마") + ["륜", "윤", "녓", "엿", "렷"]
FILL = [chr(0xAC00 + i) for i in range(0, 11172, 97)]


def random_dictionary(rng):
    syllables = rng.sample(POOL, rng.randint(3, 7))
    words = set()
    target = rng.randint(4, 13)
    while len(words) < target:
        first, last = rng.choice(syllables), rng.choice(syllables)
        if rng.random() < 0.08:
            word = first
        else:
            word = first + "".join(rng.choice(FILL) for _ in range(rng.randint(0, 2))) + last
        words.add(word)
    return sorted(words)


def raw_solver(words):
    index = {w: i for i, w in enumerate(words)}

    @lru_cache(maxsize=None)
    def value(received, used):
        alternative = conv(received)
        for w in words:
            bit = 1 << index[w]
            if used & bit:
                continue
            if w[0] == received or (alternative is not None and w[0] == alternative):
                if not value(w[-1], used | bit):
                    return True
        return False
    return index, value


def model_solver(model):
    @lru_cache(maxsize=None)
    def value(current, counts):
        normalized, static = model.normalize(current, counts)
        if static != -1:
            return bool(static)
        for group in model.available[current]:
            if normalized[group]:
                target, child, child_static = model.child(current, normalized, group)
                child_value = bool(child_static) if child_static != -1 else value(target, child)
                if not child_value:
                    return True
        return False
    return value


def main():
    dictionaries = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
    rng = random.Random(int(sys.argv[2]) if len(sys.argv) > 2 else 1)
    positions = labels_checked = shared_dicts = 0
    for _ in range(dictionaries):
        words = random_dictionary(rng)
        model = ModelV3(" ".join(words).encode(), 0)
        if any(model.shared):
            shared_dicts += 1
        index, raw = raw_solver(words)
        mval = model_solver(model)
        representative = {}
        for x in sorted(model.starts | {w[-1] for w in words}):
            representative.setdefault(model.vertex_of(x), x)
        receivable = sorted(set(POOL) | {w[-1] for w in words})
        for _ in range(6):
            initial = rng.choice(receivable)
            key = model.key(initial)
            if key not in model.vertex:
                continue
            used_words = [w for w in words if rng.random() < 0.25]
            used = sum(1 << index[w] for w in used_words)
            current, counts, _ = model.position({"initial_syllable": initial, "history": [],
                                                 "initial_used_words": used_words})
            expected = raw(initial, used)
            got = mval(current, counts)
            assert got == expected, (words, initial, used_words, expected, got)
            paired = model.reduce(current, counts)
            labels = model.static_labels(paired)
            reach = {current}
            queue = [current]
            for s in queue:
                for g in model.available[s]:
                    if paired[g] and model.edges[g][1] not in reach:
                        reach.add(model.edges[g][1])
                        queue.append(model.edges[g][1])
            for u in reach:
                if labels[u] != -1:
                    assert raw(representative[u], used) == bool(labels[u]), (words, used_words, model.names[u], labels[u])
                    labels_checked += 1
            positions += 1
    print({"dictionaries": dictionaries, "with_shared_groups": shared_dicts,
           "positions": positions, "static_labels_checked": labels_checked, "ok": True})


if __name__ == "__main__":
    main()
