#!/usr/bin/env python3
"""route-proof-v4 checker (moves only; every state is re-derived by replay).

The game model, the initial-sound rule, the canonical form and the position
replay are imported unchanged from ../verifier_v3/verify_v3.py (ModelV3, conv).
See FORMAT.md for the certificate format and README_KO.md for a summary.

A v4 node line is {"id":i,"r":"W"|"L","m":[[group,child_id],...]} (optional
"k":"static", which is then checked).  There are no vertices and no counts in
the file: the root state is the normalized requested position, and the state of
every other node is model.child(parent state, group) along the edges, found by an
iterative depth-first search from the root.  The first arrival at a node records
its derived state (deflate-compressed with the root state as preset dictionary, or a
SHA-256 digest with --digest-only); every
later arrival must derive a byte-identical state.  At expansion each reached node
gets exactly the v3 node checks (its state must be a fixed point of normalize; the
static label decides static nodes; W has one move to an L child; L lists every
legal group once and all children are W).  Nodes never reached from the root are
only checked syntactically and are reported as unreached.
"""
from array import array
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys
import time
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "verifier_v3"))
from verify_v3 import ModelV3, VerificationError, RULE_NAME, conv  # noqa: E402,F401

FORMAT = "route-proof-v4"
HEADER_KEYS = {"format", "groups", "vertices", "root", "input_sha256"}
NODE_KEYS = {"id", "r", "m", "k"}

# Fast path: the exact compact form the solver writes.  Every line it matches is valid
# JSON that json.loads would turn into {"id": int, "r": "W"|"L", "m": [[int, int], ...]}
# with no duplicate keys, so the fast path accepts nothing the slow path would refuse.
_NUM = rb"(?:0|[1-9][0-9]*)"
_FAST = re.compile(rb'\{"id":(' + _NUM + rb'),"r":"([WL])","m":\[((?:\[' + _NUM + rb',' + _NUM +
                   rb'\](?:,\[' + _NUM + rb',' + _NUM + rb'\])*)?)\]\}\r?')
_DIGITS = re.compile(rb"[0-9]+")


def require(condition, message):
    if not condition:
        raise VerificationError(message)


def integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _parse_json_line(raw, line_number):
    try:
        text = raw.decode("utf-8")
        result = json.loads(text, object_pairs_hook=_unique_keys)
    except (ValueError, TypeError, RecursionError) as exc:   # UnicodeDecodeError is a ValueError
        raise VerificationError(f"invalid JSON on line {line_number}: {exc}") from exc
    require(isinstance(result, dict), f"line {line_number} is not an object")
    return result


def _strip_newline(line):
    return line[:-1] if line.endswith(b"\n") else line


def _open_proof(path):
    with open(path, "rb") as source:
        magic = source.read(2)
    return gzip.open(path, "rb") if magic == b"\x1f\x8b" else open(path, "rb")


class Certificate:
    """All node lines in compact arrays (no states)."""

    def __init__(self, path, groups, vertices, input_digest):
        self.results = bytearray()           # 1 = W, 0 = L
        self.static_claims = set()           # ids with "k": "static"
        self.offsets = array("Q", [0])       # moves of node i: flat[2*offsets[i] : 2*offsets[i+1]]
        self.flat = array("I")               # group, child, group, child, ...
        with _open_proof(path) as stream:
            header = _parse_json_line(_strip_newline(stream.readline()), 1)
            require(set(header) <= HEADER_KEYS, f"unknown header key(s): {sorted(set(header) - HEADER_KEYS)}")
            require(header.get("format") == FORMAT, "unknown proof format")
            require(integer(header.get("groups")) and header["groups"] == groups,
                    "proof group count differs from independently reconstructed model")
            require(integer(header.get("vertices")) and header["vertices"] == vertices,
                    "proof vertex count differs from independently reconstructed model")
            require(integer(header.get("root")) and header["root"] >= 0, "invalid proof root id")
            if "input_sha256" in header:
                require(input_digest is not None, "input_sha256 requires --input")
                require(header["input_sha256"] == input_digest, "proof input hash mismatch")
            self.header = header
            results, flat, offsets = self.results, self.flat, self.offsets
            for line_number, line in enumerate(stream, 2):
                line = _strip_newline(line)
                identifier = len(results)
                fast = _FAST.fullmatch(line)
                if fast is not None:
                    require(int(fast.group(1)) == identifier,
                            f"line {line_number}: ids must be contiguous from zero")
                    result = fast.group(2) == b"W"
                    numbers = [int(x) for x in _DIGITS.findall(fast.group(3))]
                else:
                    node = _parse_json_line(line, line_number)
                    require(set(node) <= NODE_KEYS, f"node {identifier}: unknown key(s)")
                    require(integer(node.get("id")) and node["id"] == identifier,
                            f"line {line_number}: ids must be contiguous from zero")
                    require(node.get("r") in ("W", "L"), f"node {identifier}: unknown result")
                    result = node["r"] == "W"
                    if "k" in node:
                        require(node["k"] == "static", f"node {identifier}: unknown kind")
                        self.static_claims.add(identifier)
                    moves = node.get("m")
                    require(isinstance(moves, list), f"node {identifier}: missing moves")
                    numbers = []
                    for move in moves:
                        require(isinstance(move, list) and len(move) == 2 and all(integer(x) for x in move),
                                f"node {identifier}: malformed move")
                        numbers.extend(move)
                groups_here = numbers[0::2]
                for group, child in zip(groups_here, numbers[1::2]):
                    require(0 <= group < groups, f"node {identifier}: group out of range")
                    require(0 <= child < identifier, f"node {identifier}: child must precede parent")
                require(len(set(groups_here)) == len(groups_here), f"node {identifier}: duplicate move group")
                results.append(result)
                flat.extend(numbers)
                offsets.append(len(flat) // 2)
        require(results, "empty certificate")
        require(header["root"] == len(results) - 1, "root must be last node")

    def __len__(self):
        return len(self.results)


class StateStore:
    """State recorded at the first arrival at each node, compared exactly on later arrivals.

    Exact mode keeps each state as a raw-deflate stream (level 6) with the root state as
    preset dictionary and compares by decompressing and comparing all bytes; --digest-only
    keeps a SHA-256 per recorded state."""

    def __init__(self, size, digest_only, dictionary):
        self.digest_only = digest_only
        self.dictionary = dictionary
        self.vertex = array("I", bytes(4 * size))
        self.start = array("Q", bytes(8 * size))
        self.length = array("H", bytes(2 * size))
        self.blob = bytearray()
        self.pending = {}      # digest mode: packed state of nodes waiting for expansion

    def _pack(self, counts):
        packer = zlib.compressobj(6, zlib.DEFLATED, -15, zdict=self.dictionary)
        return packer.compress(counts) + packer.flush()

    def _unpack(self, packed):
        unpacker = zlib.decompressobj(-15, zdict=self.dictionary)
        result = unpacker.decompress(packed) + unpacker.flush()
        require(unpacker.eof and not unpacker.unused_data, "state storage failure")
        return result

    def record(self, node, vertex, counts):
        self.vertex[node] = vertex
        self.start[node] = len(self.blob)
        if self.digest_only:
            self.blob += hashlib.sha256(counts).digest()
            self.pending[node] = self._pack(counts)
        else:
            packed = self._pack(counts)
            self.length[node] = len(packed)
            self.blob += packed

    def same(self, node, vertex, counts):
        if self.vertex[node] != vertex:
            return False
        start = self.start[node]
        if self.digest_only:
            return self.blob[start:start + 32] == hashlib.sha256(counts).digest()
        return self._unpack(bytes(self.blob[start:start + self.length[node]])) == counts   # exact bytes

    def take(self, node):
        if self.digest_only:
            return self.vertex[node], self._unpack(self.pending.pop(node))
        start = self.start[node]
        return self.vertex[node], self._unpack(bytes(self.blob[start:start + self.length[node]]))


def verify_v4(dictionary_path, position_path, proof_path, input_path, expected_word_count, digest_only=False):
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
    cert = Certificate(proof_path, len(model.edges), len(model.keys), input_digest)
    total = len(cert)
    results, offsets, flat = cert.results, cert.offsets, cert.flat
    store = StateStore(total, digest_only, expected_root)
    reached = bytearray(total)
    root = total - 1
    reached[root] = 1
    store.record(root, root_vertex, expected_root)
    stack = [root]
    reached_count = 1
    checked_moves = static_leaves = 0
    available = model.available
    while stack:
        identifier = stack.pop()
        current, counts = store.take(identifier)
        canonical, static = model.normalize(current, counts)
        require(canonical == counts, f"node {identifier}: not canonically reduced")
        result_w = results[identifier]
        lo, hi = 2 * offsets[identifier], 2 * offsets[identifier + 1]
        if static != -1:
            require(lo == hi, f"node {identifier}: static node must be a leaf")
            require(result_w == static, f"node {identifier}: static label is false")
            static_leaves += 1
            continue
        require(identifier not in cert.static_claims, f"node {identifier}: false static claim")
        if result_w:
            require(hi - lo == 2, f"node {identifier}: W needs one witness")
        legal = {group for group in available[current] if counts[group]}
        seen = set()
        for position_in_flat in range(lo, hi, 2):
            group, child_id = flat[position_in_flat], flat[position_in_flat + 1]
            require(group in legal, f"node {identifier}: illegal move group")
            require(group not in seen, f"node {identifier}: duplicate move group")
            seen.add(group)
            require(child_id < identifier, f"node {identifier}: child must precede parent")
            child_vertex, child_counts, _ = model.child(current, counts, group)
            if reached[child_id]:
                require(store.same(child_id, child_vertex, child_counts),
                        f"node {identifier}: incorrect child state (node {child_id} reached with a different state)")
            else:
                reached[child_id] = 1
                reached_count += 1
                store.record(child_id, child_vertex, child_counts)
                stack.append(child_id)
            require(results[child_id] == (0 if result_w else 1),
                    f"node {identifier}: child verdict contradicts minimax")
            checked_moves += 1
        if not result_w:
            require(seen == legal, f"node {identifier}: losing node omits legal move")
    digest = hashlib.sha256()
    with open(proof_path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"verified": True, "format": FORMAT, "rule": RULE_NAME,
            "result_for_player_to_move": "W" if results[root] else "L",
            "initial_syllable": position["initial_syllable"],
            "current_vertex": model.names[root_vertex],
            "history": position["history"],
            "initial_used_words": position.get("initial_used_words", []),
            "dictionary_words": len(model.words), "used_words": len(used),
            "model_vertices": len(model.keys), "model_groups": len(model.edges),
            "shared_groups": sum(model.shared),
            "checked_certificate_states": reached_count, "checked_certificate_moves": checked_moves,
            "checked_static_leaves": static_leaves, "reduced_root_word_count": sum(expected_root),
            "certificate_nodes": total, "unreached_nodes": total - reached_count,
            "state_storage": "sha256" if digest_only else "deflate-exact",
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
    parser.add_argument("--digest-only", action="store_true",
                        help="keep SHA-256 digests of recorded states instead of exact compressed states")
    args = parser.parse_args()
    try:
        result = verify_v4(args.dictionary, args.position, args.proof, args.input,
                           args.expected_word_count, args.digest_only)
    except (VerificationError, OSError, EOFError, ValueError, zlib.error, MemoryError) as exc:
        print(json.dumps({"verified": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
