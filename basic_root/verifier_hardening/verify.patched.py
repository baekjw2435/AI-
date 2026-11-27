#!/usr/bin/env python3
"""Independent verifier for route-proof-v1 certificates.

The source dictionary and literal game history, not an imported search cache,
define the position.  This module does not import any search/model-builder code.
Its certificate semantics are described in INTERFACE.md.
"""
from __future__ import annotations

import argparse
from array import array
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import sys
import time


class VerificationError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise VerificationError(message)


def integer(value):
    return type(value) is int


def dueum(syllable):
    """Apply the agreed standard initial-sound rule to one final syllable."""
    require(isinstance(syllable, str) and len(syllable) == 1,
            "a current syllable must be one Unicode character")
    offset = ord(syllable) - 0xAC00
    require(0 <= offset < 11172, "only precomposed Korean syllables are supported")
    initial, remainder = divmod(offset, 588)
    vowel = remainder // 28
    if initial == 5:  # rieul
        if vowel in (2, 6, 7, 12, 17, 20):    # 랴 려 례 료 류 리 -> ㅇ (맞춤법 제11항)
            initial = 11
        elif vowel in (0, 1, 8, 11, 13, 18):  # 라 래 로 뢰 루 르 -> ㄴ (제12항)
            initial = 2
        # every other rieul syllable (러 레 뤄 릐 ...) is not a Sino-Korean reading: unchanged
    elif initial == 2 and vowel in (6, 12, 17, 20):  # 녀 뇨 뉴 니 -> ㅇ (제10항)
        initial = 11
    return chr(0xAC00 + initial * 588 + remainder)


class IndependentModel:
    def __init__(self, dictionary_bytes, expected_word_count=817):
        try:
            self.words = dictionary_bytes.decode("utf-8-sig").split()
        except UnicodeDecodeError as exc:
            raise VerificationError("dictionary is not UTF-8") from exc
        require(self.words, "empty dictionary")
        require(len(set(self.words)) == len(self.words), "duplicate dictionary word")
        if expected_word_count:
            require(len(self.words) == expected_word_count,
                    f"expected {expected_word_count} words, got {len(self.words)}")
        require(all(all(0xAC00 <= ord(c) <= 0xD7A3 for c in w) for w in self.words),
                "dictionary contains a non-Hangul token")
        # The requested 817-word dictionary meets this constraint. A dictionary
        # with such starts needs a model for asymmetric alternate initial forms.
        require(all(dueum(w[0]) == w[0] for w in self.words),
                "dictionary contains a dueum-changing initial syllable; unsupported model")
        syllables = sorted({w[0] for w in self.words} | {dueum(w[-1]) for w in self.words})
        self.syllables = syllables
        self.vertex = {s: i for i, s in enumerate(syllables)}
        self.word_endpoints = {
            w: (self.vertex[w[0]], self.vertex[dueum(w[-1])]) for w in self.words
        }
        populations = Counter(self.word_endpoints.values())
        self.edges = sorted(populations)
        self.group = {edge: i for i, edge in enumerate(self.edges)}
        self.full_counts = bytes(populations[e] for e in self.edges)
        self.outgoing = [[] for _ in syllables]
        for index, (source, _) in enumerate(self.edges):
            self.outgoing[source].append(index)
        self.pairs = []
        self.loops = []
        for index, (source, target) in enumerate(self.edges):
            if source == target:
                self.loops.append(index)
            elif source < target and (target, source) in self.group:
                self.pairs.append((index, self.group[target, source]))

    def position(self, manifest):
        require(isinstance(manifest, dict), "position must be an object")
        require("initial_syllable" in manifest, "missing initial_syllable")
        current_syllable = dueum(manifest["initial_syllable"])
        require(current_syllable in self.vertex, "initial syllable is outside the model")
        current = self.vertex[current_syllable]
        history = manifest.get("history")
        require(isinstance(history, list), "history must be an explicit list")
        initially_used = manifest.get("initial_used_words", [])
        require(isinstance(initially_used, list), "initial_used_words must be a list")
        used = set()
        counts = bytearray(self.full_counts)
        for word in initially_used:
            require(isinstance(word, str) and word in self.word_endpoints,
                    f"unknown initially used word: {word!r}")
            require(word not in used, f"reused initially used word: {word}")
            counts[self.group[self.word_endpoints[word]]] -= 1
            used.add(word)
        for ply, word in enumerate(history, 1):
            require(isinstance(word, str) and word in self.word_endpoints,
                    f"unknown history word at ply {ply}: {word!r}")
            require(word not in used, f"reused history word at ply {ply}: {word}")
            source, target = self.word_endpoints[word]
            require(source == current,
                    f"illegal history connection at ply {ply}: {word}; expected {self.syllables[current]}")
            counts[self.group[source, target]] -= 1
            current = target
            used.add(word)
        return current, bytes(counts), used

    def reduce(self, current, counts):
        """Pair cancellation, followed by directed reachability pruning."""
        remaining = bytearray(counts)
        for first, reverse in self.pairs:
            amount = min(remaining[first], remaining[reverse])
            remaining[first] -= amount
            remaining[reverse] -= amount
        for loop in self.loops:
            remaining[loop] %= 2
        reachable = bytearray(len(self.syllables))
        reachable[current] = 1
        queue = [current]
        for source in queue:
            for group in self.outgoing[source]:
                if remaining[group]:
                    target = self.edges[group][1]
                    if not reachable[target]:
                        reachable[target] = 1
                        queue.append(target)
        for source, outgoing in enumerate(self.outgoing):
            if not reachable[source]:
                for group in outgoing:
                    remaining[group] = 0
        return bytes(remaining)

    def child(self, current, counts, move):
        source, target = self.edges[move]
        require(source == current and counts[move] > 0, "illegal certificate move")
        remaining = bytearray(counts)
        remaining[move] -= 1
        return target, self.reduce(target, remaining)

    def check_numeric_input(self, input_path, current, counts):
        try:
            data = Path(input_path).read_bytes()
            fields = [int(field) for field in data.decode("ascii").split()]
        except (OSError, UnicodeError, ValueError) as exc:
            raise VerificationError("invalid numeric solver input") from exc
        expected = [len(self.syllables), len(self.edges), current]
        for (source, target), count in zip(self.edges, counts):
            expected.extend((source, target, count))
        require(fields == expected, "numeric solver input differs from dictionary/history")
        return hashlib.sha256(data).hexdigest()


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _parse_line(line, line_number):
    try:
        result = json.loads(line, object_pairs_hook=_unique_keys)
    except (ValueError, TypeError, RecursionError) as exc:
        raise VerificationError(f"invalid JSON on line {line_number}: {exc}") from exc
    require(isinstance(result, dict), f"line {line_number} is not an object")
    return result


def verify(dictionary_path, position_path, proof_path, input_path=None,
           expected_word_count=817):
    started = time.monotonic()
    dictionary_bytes = Path(dictionary_path).read_bytes()
    position_bytes = Path(position_path).read_bytes()
    try:
        position = json.loads(position_bytes, object_pairs_hook=_unique_keys)
    except (ValueError, UnicodeError) as exc:
        raise VerificationError(f"invalid position JSON: {exc}") from exc
    model = IndependentModel(dictionary_bytes, expected_word_count)
    root_vertex, initial_counts, used = model.position(position)
    expected_root = model.reduce(root_vertex, initial_counts)
    input_digest = None
    if input_path is not None:
        input_digest = model.check_numeric_input(input_path, root_vertex, initial_counts)
    vertices = array("I")
    outcomes = bytearray()
    states = []
    checked_moves = 0
    proof_path = Path(proof_path)
    with proof_path.open("rb") as source:
        magic = source.read(2)
    opener = gzip.open if magic == b"\x1f\x8b" else open
    with opener(proof_path, "rt", encoding="utf-8") as stream:
        header = _parse_line(stream.readline(), 1)
        require(header.get("format") == "route-proof-v1", "unknown proof format")
        require(integer(header.get("groups")) and header["groups"] == len(model.edges),
                "proof group count differs from independently reconstructed model")
        require(integer(header.get("vertices")) and header["vertices"] == len(model.syllables),
                "proof vertex count differs from independently reconstructed model")
        require(integer(header.get("root")) and header["root"] >= 0, "invalid proof root id")
        if "input_sha256" in header:
            require(input_digest is not None,
                    "proof declares input_sha256; --input is required to check it")
            require(header["input_sha256"] == input_digest, "proof input hash mismatch")
        for line_number, line in enumerate(stream, 2):
            node = _parse_line(line, line_number)
            node_id = len(states)
            require(integer(node.get("id")) and node["id"] == node_id,
                    f"line {line_number}: ids must be contiguous from zero")
            current = node.get("v")
            require(integer(current) and 0 <= current < len(model.syllables),
                    f"node {node_id}: invalid current vertex")
            encoded = node.get("c")
            require(isinstance(encoded, str) and len(encoded) == 2 * len(model.edges),
                    f"node {node_id}: wrong count encoding length")
            try:
                counts = bytes.fromhex(encoded)
            except ValueError as exc:
                raise VerificationError(f"node {node_id}: invalid hex counts") from exc
            require(len(counts) == len(model.edges), f"node {node_id}: wrong count byte length")
            require(all(c <= bound for c, bound in zip(counts, model.full_counts)),
                    f"node {node_id}: more words than dictionary contains")
            require(model.reduce(current, counts) == counts,
                    f"node {node_id}: state is not canonically reduced")
            result = node.get("r")
            require(result in ("W", "L"), f"node {node_id}: unknown result")
            moves = node.get("m")
            require(isinstance(moves, list), f"node {node_id}: missing move list")
            if result == "W":
                require(len(moves) == 1, f"node {node_id}: a win needs exactly one witness")
            legal = {group for group in model.outgoing[current] if counts[group]}
            seen = set()
            for move in moves:
                require(isinstance(move, list) and len(move) == 2
                        and all(integer(x) for x in move), f"node {node_id}: invalid move record")
                group, child_id = move
                require(group in legal, f"node {node_id}: illegal move group")
                require(group not in seen, f"node {node_id}: duplicate move group")
                seen.add(group)
                require(0 <= child_id < node_id,
                        f"node {node_id}: child must be an earlier certificate node")
                child_vertex, child_counts = model.child(current, counts, group)
                require(vertices[child_id] == child_vertex and states[child_id] == child_counts,
                        f"node {node_id}: child state does not match the consumed word")
                require(outcomes[child_id] == (0 if result == "W" else 1),
                        f"node {node_id}: child result contradicts minimax rule")
                checked_moves += 1
            if result == "L":
                require(seen == legal, f"node {node_id}: losing node omits a legal move")
            states.append(counts)
            vertices.append(current)
            outcomes.append(result == "W")
    require(states, "empty certificate")
    require(header["root"] == len(states) - 1, "root must be the final certificate node")
    require(vertices[-1] == root_vertex and states[-1] == expected_root,
            "root does not match the requested exact history")
    digest = hashlib.sha256()
    with proof_path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "verified": True,
        "format": "route-proof-v1",
        "result_for_player_to_move": "W" if outcomes[-1] else "L",
        "current_syllable": model.syllables[root_vertex],
        "history": position["history"],
        "initial_used_words": position.get("initial_used_words", []),
        "dictionary_words": len(model.words),
        "used_words": len(used),
        "checked_certificate_states": len(states),
        "checked_certificate_moves": checked_moves,
        "reduced_root_word_count": sum(expected_root),
        "dictionary_sha256": hashlib.sha256(dictionary_bytes).hexdigest(),
        "position_sha256": hashlib.sha256(position_bytes).hexdigest(),
        "proof_sha256": digest.hexdigest(),
        "input_sha256": input_digest,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "legacy_cache_used": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dictionary", required=True)
    parser.add_argument("--position", required=True)
    parser.add_argument("--proof", required=True)
    parser.add_argument("--input")
    parser.add_argument("--expected-word-count", type=int, default=817,
                        help="default 817; use 0 for an unrestricted test dictionary")
    args = parser.parse_args()
    try:
        report = verify(args.dictionary, args.position, args.proof, args.input,
                        args.expected_word_count)
    except (VerificationError, OSError, EOFError, UnicodeError) as exc:
        print(json.dumps({"verified": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
