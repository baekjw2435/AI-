#!/usr/bin/env python3
"""Independent route-proof-v3 checker for the asymmetric standard initial-sound rule.

Rule (the word engine's "표준두음법칙", independent of the final consonant):
  ㄹ + ㅑㅕㅖㅛㅠㅣ  may also be played as  ㅇ + same vowel/final
  ㄹ + ㅏㅐㅗㅚㅜㅡ  may also be played as  ㄴ + same vowel/final
  ㄴ + ㅕㅛㅠㅣ      may also be played as  ㅇ + same vowel/final
A player who receives syllable X may play any unused word whose first syllable
is X or conv(X). Conversion is one step only and never runs backwards: after
낙 a word starting with 락 is not legal, after 락 both 락- and 낙-words are.

Model. A vertex is the set of first syllables a receiver may use (raw received
syllables with the same set are the same vertex). A word group is all words with
the same set of source vertices (from its first syllable) and the same target
vertex (from its last syllable). A group with two or more sources is "shared":
one word, usable from several vertices.

Canonical form (each step preserves the game value; see README_KO.md):
 1. pair cancellation only between single-source groups u->v and v->u, and
    single-source loops modulo 2; shared groups are never cancelled;
 2. drop groups none of whose sources is reachable from the current vertex;
 3. least-fixed-point static labels: W if some successor is L; otherwise, when
    every non-loop successor is W, the single-source loop decides (W with a
    loop, L without) - but a vertex with an available shared loop stays unknown;
 4. keep only groups with a source reachable through unknown vertices and an
    unknown target.

No search code, C++ code or v1/v2 verifier code is imported.
"""
from array import array
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import sys
import time

RULE_NAME = "engine-standard-dueum (ㄹ:ㅑㅕㅖㅛㅠㅣ→ㅇ, ㅏㅐㅗㅚㅜㅡ→ㄴ; ㄴ:ㅕㅛㅠㅣ→ㅇ; one-way)"


class VerificationError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise VerificationError(message)


def integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def conv(syllable):
    """The alternative first syllable allowed after receiving `syllable`, or None."""
    offset = ord(syllable) - 0xAC00
    require(0 <= offset < 11172, "only precomposed Korean syllables are supported")
    initial, remainder = divmod(offset, 588)
    vowel = remainder // 28
    if initial == 5 and vowel in (2, 6, 7, 12, 17, 20):   # ㄹ + ㅑㅕㅖㅛㅠㅣ -> ㅇ
        return chr(0xAC00 + 11 * 588 + remainder)
    if initial == 5 and vowel in (0, 1, 8, 11, 13, 18):   # ㄹ + ㅏㅐㅗㅚㅜㅡ -> ㄴ
        return chr(0xAC00 + 2 * 588 + remainder)
    if initial == 2 and vowel in (6, 12, 17, 20):         # ㄴ + ㅕㅛㅠㅣ -> ㅇ
        return chr(0xAC00 + 11 * 588 + remainder)
    return None


class ModelV3:
    def __init__(self, dictionary_bytes, expected_word_count):
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
        self.starts = {w[0] for w in self.words}
        raw = self.starts | {w[-1] for w in self.words}
        self.keys = sorted({self.key(x) for x in raw})
        self.vertex = {k: i for i, k in enumerate(self.keys)}
        self.names = ["/".join(k) if k else "-" for k in self.keys]
        sources_of = {s: tuple(i for i, k in enumerate(self.keys) if s in k) for s in self.starts}
        self.word_group_key = {w: (sources_of[w[0]], self.vertex[self.key(w[-1])]) for w in self.words}
        populations = Counter(self.word_group_key.values())
        self.edges = sorted(populations)               # (sources tuple, target)
        self.group = {e: i for i, e in enumerate(self.edges)}
        require(len(self.edges) <= 65535, "too many groups")
        require(max(populations.values()) <= 255, "group population above 255")
        self.full_counts = bytes(populations[e] for e in self.edges)
        self.available = [[] for _ in self.keys]
        for index, (sources, _) in enumerate(self.edges):
            for source in sources:
                self.available[source].append(index)
        self.shared = [len(sources) > 1 for sources, _ in self.edges]
        self.pairs = []
        self.loops = []
        for index, (sources, target) in enumerate(self.edges):
            if len(sources) != 1:
                continue
            (source,) = sources
            if source == target:
                self.loops.append(index)
            elif source < target and ((target,), source) in self.group:
                self.pairs.append((index, self.group[(target,), source]))

    def key(self, syllable):
        alternative = conv(syllable)
        return tuple(sorted(s for s in {syllable, alternative} if s is not None and s in self.starts))

    def vertex_of(self, syllable):
        key = self.key(syllable)
        require(key in self.vertex, f"syllable {syllable} is outside the model")
        return self.vertex[key]

    def word_group(self, word):
        return self.group[self.word_group_key[word]]

    def position(self, manifest):
        require(isinstance(manifest, dict), "position must be an object")
        require("initial_syllable" in manifest, "missing initial_syllable")
        initial = manifest["initial_syllable"]
        require(isinstance(initial, str) and len(initial) == 1, "initial_syllable must be one syllable")
        current = self.vertex_of(initial)
        history = manifest.get("history")
        require(isinstance(history, list), "history must be an explicit list")
        initially_used = manifest.get("initial_used_words", [])
        require(isinstance(initially_used, list), "initial_used_words must be a list")
        used = set()
        counts = bytearray(self.full_counts)
        for word in initially_used:
            require(isinstance(word, str) and word in self.word_group_key,
                    f"unknown initially used word: {word!r}")
            require(word not in used, f"reused initially used word: {word}")
            counts[self.word_group(word)] -= 1
            used.add(word)
        for ply, word in enumerate(history, 1):
            require(isinstance(word, str) and word in self.word_group_key,
                    f"unknown history word at ply {ply}: {word!r}")
            require(word not in used, f"reused history word at ply {ply}: {word}")
            require(word[0] in self.keys[current],
                    f"illegal history connection at ply {ply}: {word}; expected {self.names[current]}")
            counts[self.word_group(word)] -= 1
            current = self.vertex_of(word[-1])
            used.add(word)
        return current, bytes(counts), used

    def reduce(self, current, counts):
        remaining = bytearray(counts)
        for first, reverse in self.pairs:
            amount = min(remaining[first], remaining[reverse])
            remaining[first] -= amount
            remaining[reverse] -= amount
        for loop in self.loops:
            remaining[loop] %= 2
        reachable = bytearray(len(self.keys))
        reachable[current] = 1
        queue = [current]
        for source in queue:
            for group in self.available[source]:
                if remaining[group]:
                    target = self.edges[group][1]
                    if not reachable[target]:
                        reachable[target] = 1
                        queue.append(target)
        for group, (sources, _) in enumerate(self.edges):
            if remaining[group] and not any(reachable[s] for s in sources):
                remaining[group] = 0
        return remaining

    def static_labels(self, counts):
        n = len(self.keys)
        labels = [-1] * n
        successors = [set() for _ in range(n)]
        single_loop = bytearray(n)
        shared_loop = bytearray(n)
        for group, count in enumerate(counts):
            if not count:
                continue
            sources, target = self.edges[group]
            for source in sources:
                if source == target:
                    if len(sources) == 1:
                        single_loop[source] = 1
                    else:
                        shared_loop[source] = 1
                else:
                    successors[source].add(target)
        pending = list(range(n))
        while pending:
            remaining = []
            changed = False
            for source in pending:
                all_winning = True
                has_losing = False
                for target in successors[source]:
                    if labels[target] == 0:
                        has_losing = True
                        break
                    if labels[target] != 1:
                        all_winning = False
                if has_losing:
                    labels[source] = 1
                    changed = True
                elif all_winning and not shared_loop[source]:
                    labels[source] = int(single_loop[source])
                    changed = True
                else:
                    remaining.append(source)
            if not changed:
                break
            pending = remaining
        return labels

    def normalize(self, current, counts):
        paired = self.reduce(current, counts)
        labels = self.static_labels(paired)
        if labels[current] != -1:
            return bytes(paired), labels[current]
        seen = bytearray(len(self.keys))
        seen[current] = 1
        queue = [current]
        for source in queue:
            for group in self.available[source]:
                if paired[group]:
                    target = self.edges[group][1]
                    if labels[target] == -1 and not seen[target]:
                        seen[target] = 1
                        queue.append(target)
        core = bytearray(len(paired))
        for group, (sources, target) in enumerate(self.edges):
            if paired[group] and labels[target] == -1 and any(seen[s] for s in sources):
                core[group] = paired[group]
        return bytes(core), -1

    def child(self, current, counts, move):
        sources, target = self.edges[move]
        require(current in sources and counts[move] > 0, "illegal certificate move")
        remaining = bytearray(counts)
        remaining[move] -= 1
        normalized, static = self.normalize(target, remaining)
        return target, normalized, static

    def numeric_input(self, current, counts):
        lines = [f"{len(self.keys)} {len(self.edges)} {current}"]
        for (sources, target), count in zip(self.edges, counts):
            lines.append(" ".join(map(str, (len(sources), *sources, target, count))))
        return ("\n".join(lines) + "\n").encode("ascii")

    def check_numeric_input(self, input_path, current, counts):
        try:
            data = Path(input_path).read_bytes()
            fields = [int(field) for field in data.decode("ascii").split()]
        except (OSError, UnicodeError, ValueError) as exc:
            raise VerificationError("invalid numeric solver input") from exc
        expected = [int(x) for x in self.numeric_input(current, counts).decode("ascii").split()]
        require(fields == expected, "numeric solver input differs from dictionary/history")
        return hashlib.sha256(data).hexdigest()


def _digest(counts):
    # Earlier states are kept as SHA-256 digests (2,613 count bytes per state would not fit in
    # memory for multi-million-state certificates); equality of digests stands for equality.
    return hashlib.sha256(counts).digest()


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _parse_line(line, line_number):
    try:
        result = json.loads(line, object_pairs_hook=_unique_keys)
    except (ValueError, TypeError) as exc:
        raise VerificationError(f"invalid JSON on line {line_number}: {exc}") from exc
    require(isinstance(result, dict), f"line {line_number} is not an object")
    return result


def verify_v3(dictionary_path, position_path, proof_path, input_path, expected_word_count):
    started = time.monotonic()
    dictionary_bytes = Path(dictionary_path).read_bytes()
    position_bytes = Path(position_path).read_bytes()
    try:
        position = json.loads(position_bytes, object_pairs_hook=_unique_keys)
    except (ValueError, UnicodeError) as exc:
        raise VerificationError(f"invalid position JSON: {exc}") from exc
    model = ModelV3(dictionary_bytes, expected_word_count)
    root_vertex, initial_counts, used = model.position(position)
    expected_root, _ = model.normalize(root_vertex, initial_counts)
    input_digest = (model.check_numeric_input(input_path, root_vertex, initial_counts)
                    if input_path is not None else None)
    vertices = array("I")
    outcomes = bytearray()
    states = []
    checked_moves = static_leaves = 0
    proof_path = Path(proof_path)
    with proof_path.open("rb") as source:
        magic = source.read(2)
    opener = gzip.open if magic == b"\x1f\x8b" else open
    with opener(proof_path, "rt", encoding="utf-8") as stream:
        header = _parse_line(stream.readline(), 1)
        require(header.get("format") == "route-proof-v3", "unknown proof format")
        require(integer(header.get("groups")) and header["groups"] == len(model.edges),
                "proof group count differs from independently reconstructed model")
        require(integer(header.get("vertices")) and header["vertices"] == len(model.keys),
                "proof vertex count differs from independently reconstructed model")
        require(integer(header.get("root")) and header["root"] >= 0, "invalid proof root id")
        if "input_sha256" in header:
            require(input_digest is not None, "input_sha256 requires --input")
            require(header["input_sha256"] == input_digest, "proof input hash mismatch")
        for line_number, line in enumerate(stream, 2):
            node = _parse_line(line, line_number)
            identifier = len(states)
            require(integer(node.get("id")) and node["id"] == identifier,
                    f"line {line_number}: ids must be contiguous from zero")
            current = node.get("v")
            require(integer(current) and 0 <= current < len(model.keys), f"node {identifier}: invalid vertex")
            encoded = node.get("c")
            require(isinstance(encoded, str) and len(encoded) == 2 * len(model.edges),
                    f"node {identifier}: wrong count encoding length")
            try:
                counts = bytes.fromhex(encoded)
            except ValueError as exc:
                raise VerificationError(f"node {identifier}: invalid hex counts") from exc
            require(len(counts) == len(model.edges), f"node {identifier}: count length mismatch")
            require(all(c <= bound for c, bound in zip(counts, model.full_counts)),
                    f"node {identifier}: counts exceed dictionary")
            canonical, static = model.normalize(current, counts)
            require(canonical == counts, f"node {identifier}: not canonically reduced")
            result = node.get("r")
            require(result in ("W", "L"), f"node {identifier}: unknown result")
            moves = node.get("m")
            require(isinstance(moves, list), f"node {identifier}: missing moves")
            if static != -1:
                require(not moves, f"node {identifier}: static node must be a leaf")
                require(result == ("W" if static else "L"), f"node {identifier}: static label is false")
                static_leaves += 1
            else:
                require(node.get("k") != "static", f"node {identifier}: false static claim")
                if result == "W":
                    require(len(moves) == 1, f"node {identifier}: W needs one witness")
                legal = {group for group in model.available[current] if counts[group]}
                seen = set()
                for move in moves:
                    require(isinstance(move, list) and len(move) == 2 and all(integer(x) for x in move),
                            f"node {identifier}: malformed move")
                    group, child_id = move
                    require(group in legal, f"node {identifier}: illegal move group")
                    require(group not in seen, f"node {identifier}: duplicate move group")
                    seen.add(group)
                    require(0 <= child_id < identifier, f"node {identifier}: child must precede parent")
                    child_vertex, child_counts, _ = model.child(current, counts, group)
                    require(vertices[child_id] == child_vertex and states[child_id] == _digest(child_counts),
                            f"node {identifier}: incorrect child state")
                    require(outcomes[child_id] == (0 if result == "W" else 1),
                            f"node {identifier}: child verdict contradicts minimax")
                    checked_moves += 1
                if result == "L":
                    require(seen == legal, f"node {identifier}: losing node omits legal move")
            states.append(_digest(counts))
            vertices.append(current)
            outcomes.append(result == "W")
    require(states, "empty certificate")
    require(header["root"] == len(states) - 1, "root must be last node")
    require(vertices[-1] == root_vertex and states[-1] == _digest(expected_root),
            "root does not match exact requested history")
    digest = hashlib.sha256()
    with proof_path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"verified": True, "format": "route-proof-v3", "rule": RULE_NAME,
            "result_for_player_to_move": "W" if outcomes[-1] else "L",
            "initial_syllable": position["initial_syllable"],
            "current_vertex": model.names[root_vertex],
            "history": position["history"],
            "initial_used_words": position.get("initial_used_words", []),
            "dictionary_words": len(model.words), "used_words": len(used),
            "model_vertices": len(model.keys), "model_groups": len(model.edges),
            "shared_groups": sum(model.shared),
            "checked_certificate_states": len(states), "checked_certificate_moves": checked_moves,
            "checked_static_leaves": static_leaves, "reduced_root_word_count": sum(expected_root),
            "dictionary_sha256": hashlib.sha256(dictionary_bytes).hexdigest(),
            "position_sha256": hashlib.sha256(position_bytes).hexdigest(),
            "proof_sha256": digest.hexdigest(), "input_sha256": input_digest,
            "elapsed_seconds": round(time.monotonic() - started, 3)}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dictionary", required=True)
    parser.add_argument("--position", required=True)
    parser.add_argument("--proof", required=True)
    parser.add_argument("--input")
    parser.add_argument("--expected-word-count", type=int, required=True,
                        help="number of words the dictionary must contain (0 disables the check)")
    args = parser.parse_args()
    try:
        result = verify_v3(args.dictionary, args.position, args.proof, args.input, args.expected_word_count)
    except (VerificationError, OSError, EOFError, UnicodeError) as exc:
        print(json.dumps({"verified": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
