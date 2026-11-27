#!/usr/bin/env python3
"""Independent route-proof-v2 checker with static retrograde certification.

Imports only the v1 verifier's independent dictionary and history parser. No
search, model-builder, legacy lookup, or C++ code is imported. The static rule
uses fixed-point sweeps, independently of the searcher's reverse-edge queue.
"""
from array import array
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys
import time

from verify import (IndependentModel, VerificationError, _parse_line,
                    _unique_keys, integer, require)


class IndependentModelV2(IndependentModel):
    def static_labels(self, counts):
        # Multiplicities do not change existential/universal successor tests.
        # A single remaining loop is dealt with only after ALL nonloop exits W.
        labels = [-1] * len(self.syllables)
        successors = [[] for _ in self.syllables]
        has_loop = bytearray(len(self.syllables))
        for group, count in enumerate(counts):
            if count:
                source, target = self.edges[group]
                if source == target:
                    has_loop[source] = 1
                else:
                    successors[source].append(target)
        pending = list(range(len(self.syllables)))
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
                elif all_winning:
                    labels[source] = int(has_loop[source])
                    changed = True
                else:
                    remaining.append(source)
            if not changed:
                break
            pending = remaining
        return labels

    def normalize(self, current, counts):
        paired = super().reduce(current, counts)
        labels = self.static_labels(paired)
        if labels[current] != -1:
            return paired, labels[current]
        seen = {current}
        queue = [current]
        for source in queue:
            for group in self.outgoing[source]:
                if paired[group]:
                    target = self.edges[group][1]
                    if labels[target] == -1 and target not in seen:
                        seen.add(target)
                        queue.append(target)
        core = bytearray(len(paired))
        for source in seen:
            for group in self.outgoing[source]:
                if paired[group] and labels[self.edges[group][1]] == -1:
                    core[group] = paired[group]
        return bytes(core), -1

    def child_v2(self, current, counts, move):
        source, target = self.edges[move]
        require(source == current and counts[move] > 0, "illegal certificate move")
        remaining = bytearray(counts)
        remaining[move] -= 1
        normalized, static = self.normalize(target, remaining)
        return target, normalized, static


def verify_v2(dictionary_path, position_path, proof_path, input_path=None,
              expected_word_count=817):
    started = time.monotonic()
    dictionary_bytes = Path(dictionary_path).read_bytes()
    position_bytes = Path(position_path).read_bytes()
    try:
        position = json.loads(position_bytes, object_pairs_hook=_unique_keys)
    except (ValueError, UnicodeError) as exc:
        raise VerificationError(f"invalid position JSON: {exc}") from exc
    model = IndependentModelV2(dictionary_bytes, expected_word_count)
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
        require(header.get("format") == "route-proof-v2", "unknown proof format")
        require(integer(header.get("groups")) and header["groups"] == len(model.edges),
                "proof group count differs from independently reconstructed model")
        require(integer(header.get("vertices")) and header["vertices"] == len(model.syllables),
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
            require(integer(current) and 0 <= current < len(model.syllables),
                    f"node {identifier}: invalid vertex")
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
                require(result == ("W" if static else "L"),
                        f"node {identifier}: static label is false")
                static_leaves += 1
            else:
                require(node.get("k") != "static", f"node {identifier}: false static claim")
                if result == "W":
                    require(len(moves) == 1, f"node {identifier}: W needs one witness")
                legal = {group for group in model.outgoing[current] if counts[group]}
                seen = set()
                for move in moves:
                    require(isinstance(move, list) and len(move) == 2 and all(integer(x) for x in move),
                            f"node {identifier}: malformed move")
                    group, child_id = move
                    require(group in legal, f"node {identifier}: illegal move group")
                    require(group not in seen, f"node {identifier}: duplicate move group")
                    seen.add(group)
                    require(0 <= child_id < identifier, f"node {identifier}: child must precede parent")
                    child_vertex, child_counts, _ = model.child_v2(current, counts, group)
                    require(vertices[child_id] == child_vertex and states[child_id] == child_counts,
                            f"node {identifier}: incorrect child state")
                    require(outcomes[child_id] == (0 if result == "W" else 1),
                            f"node {identifier}: child verdict contradicts minimax")
                    checked_moves += 1
                if result == "L":
                    require(seen == legal, f"node {identifier}: losing node omits legal move")
            states.append(counts)
            vertices.append(current)
            outcomes.append(result == "W")
    require(states, "empty certificate")
    require(header["root"] == len(states) - 1, "root must be last node")
    require(vertices[-1] == root_vertex and states[-1] == expected_root,
            "root does not match exact requested history")
    digest = hashlib.sha256()
    with proof_path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"verified": True, "format": "route-proof-v2",
            "result_for_player_to_move": "W" if outcomes[-1] else "L",
            "current_syllable": model.syllables[root_vertex],
            "history": position["history"],
            "initial_used_words": position.get("initial_used_words", []),
            "dictionary_words": len(model.words), "used_words": len(used),
            "checked_certificate_states": len(states), "checked_certificate_moves": checked_moves,
            "checked_static_leaves": static_leaves, "reduced_root_word_count": sum(expected_root),
            "dictionary_sha256": hashlib.sha256(dictionary_bytes).hexdigest(),
            "position_sha256": hashlib.sha256(position_bytes).hexdigest(),
            "proof_sha256": digest.hexdigest(), "input_sha256": input_digest,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "legacy_lookup_trusted": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dictionary", required=True)
    parser.add_argument("--position", required=True)
    parser.add_argument("--proof", required=True)
    parser.add_argument("--input")
    parser.add_argument("--expected-word-count", type=int, default=817)
    args = parser.parse_args()
    try:
        result = verify_v2(args.dictionary, args.position, args.proof, args.input, args.expected_word_count)
    except (VerificationError, OSError, EOFError, UnicodeError) as exc:
        print(json.dumps({"verified": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
