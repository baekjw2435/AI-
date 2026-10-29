#!/usr/bin/env python3
"""Streaming, hardened route-proof-v2 checker (second independent implementation).

Written from INTERFACE_v2.md / model_audit.md only. It imports neither verify.py,
verify_v2.py nor any solver code; standard library only.

Differences from verify_v2.py (see README in this folder):
  * certificate nodes are remembered by a keyed BLAKE2b-128 digest of
    (vertex, counts) under a fresh random 256-bit key, 17 bytes per node instead
    of a 718-byte bytes object; the root is still compared byte for byte;
  * normalization uses vertex bitsets and memoized per-vertex successor masks;
  * the proof SHA-256 is computed from the same single read that is verified
    (verify_v2 re-opens the path afterwards);
  * dueum follows the standard rule exactly (ㄹ+ㅏㅐㅗㅚㅜㅡ->ㄴ, ㄹ+ㅑㅕㅖㅛㅠㅣ->ㅇ,
    ㄴ+ㅕㅛㅠㅣ->ㅇ, every other syllable unchanged); --legacy-dueum reproduces
    verify.py's mapping (all other ㄹ -> ㄴ);
  * hardened mode (default) pins the 817-word dictionary hash, rejects unknown
    position keys, checks informational position keys, and refuses
    initial_used_words unless --allow-initial-used is given.  --compat turns
    those position/dictionary policies off to match verify_v2's acceptance.
"""
from __future__ import annotations

import argparse
from bisect import bisect_left
import ctypes
from collections import Counter
import gzip
import hashlib
import io
from itertools import compress
import json
import os
from pathlib import Path
import sys
import time

PINNED_DICTIONARY_SHA256 = "aa37031019f1e2a95b422ffc2f8d8d1b76b03ca88163b03b17af16ff90c79273"
FORMAT = "route-proof-v2"


class VerificationError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise VerificationError(message)


def is_int(value):
    return type(value) is int  # rejects bool, float, str


# --------------------------------------------------------------------------
# 두음법칙 (한글 맞춤법 제10항-제12항), applied to one syllable.
# Vowel indices: ㅏ0 ㅐ1 ㅑ2 ㅒ3 ㅓ4 ㅔ5 ㅕ6 ㅖ7 ㅗ8 ㅘ9 ㅙ10 ㅚ11 ㅛ12 ㅜ13 ㅝ14
#                ㅞ15 ㅟ16 ㅠ17 ㅡ18 ㅢ19 ㅣ20.  Initials: ㄴ2 ㄹ5 ㅇ11.
_R_TO_IEUNG = frozenset((2, 6, 7, 12, 17, 20))  # 랴 려 례 료 류 리 (제11항)
_R_TO_NIEUN = frozenset((0, 1, 8, 11, 13, 18))  # 라 래 로 뢰 루 르 (제12항)
_N_TO_IEUNG = frozenset((6, 12, 17, 20))        # 녀 뇨 뉴 니 (제10항)


def _decompose(syllable):
    require(isinstance(syllable, str) and len(syllable) == 1,
            "a syllable must be one Unicode character")
    offset = ord(syllable) - 0xAC00
    require(0 <= offset < 11172, "only precomposed Korean syllables are supported")
    return offset // 588, (offset % 588) // 28, offset % 28


def dueum_standard(syllable):
    initial, vowel, final = _decompose(syllable)
    if initial == 5:
        if vowel in _R_TO_IEUNG:
            initial = 11
        elif vowel in _R_TO_NIEUN:
            initial = 2
    elif initial == 2 and vowel in _N_TO_IEUNG:
        initial = 11
    return chr(0xAC00 + (initial * 21 + vowel) * 28 + final)


def dueum_legacy(syllable):
    """verify.py's mapping: every ㄹ whose vowel is not in the ㅇ list becomes ㄴ."""
    initial, vowel, final = _decompose(syllable)
    if initial == 5:
        initial = 11 if vowel in _R_TO_IEUNG else 2
    elif initial == 2 and vowel in _N_TO_IEUNG:
        initial = 11
    return chr(0xAC00 + (initial * 21 + vowel) * 28 + final)


_NONZERO = bytes([0] + [1] * 255)
_AT_LEAST_TWO = bytes([0, 0] + [1] * 254)


class Model:
    """Independent dictionary model: syllables in Python sort order, groups by (src,dst)."""

    def __init__(self, dictionary_bytes, expected_word_count=817, dueum=dueum_standard):
        try:
            words = dictionary_bytes.decode("utf-8-sig").split()
        except UnicodeDecodeError as exc:
            raise VerificationError("dictionary is not UTF-8") from exc
        require(words, "empty dictionary")
        require(len(set(words)) == len(words), "duplicate dictionary word")
        if expected_word_count:
            require(len(words) == expected_word_count,
                    f"expected {expected_word_count} words, got {len(words)}")
        require(all(0xAC00 <= ord(ch) <= 0xD7A3 for word in words for ch in word),
                "dictionary contains a non-Hangul token")
        # A dictionary word starting with a dueum-changing syllable would need the
        # two-variant ("either form") rule on the incoming side; not modelled.
        require(all(dueum(word[0]) == word[0] for word in words),
                "dictionary contains a dueum-changing initial syllable; unsupported model")
        self.dueum = dueum
        self.words = words
        syllables = sorted({w[0] for w in words} | {dueum(w[-1]) for w in words})
        self.syllables = syllables
        self.vertex = {s: i for i, s in enumerate(syllables)}
        self.endpoints = {w: (self.vertex[w[0]], self.vertex[dueum(w[-1])]) for w in words}
        population = Counter(self.endpoints.values())
        self.edges = sorted(population)
        self.group = {edge: i for i, edge in enumerate(self.edges)}
        self.full_counts = bytes(population[e] for e in self.edges)
        require(max(self.full_counts) <= 255, "group multiplicity above 255")
        V, G = len(syllables), len(self.edges)
        self.V, self.G = V, G
        self.src = [s for s, _ in self.edges]
        self.dst = [t for _, t in self.edges]
        # Groups are sorted by source, so each vertex owns one contiguous range.
        self.lo = [bisect_left(self.src, v) for v in range(V)]
        self.hi = [bisect_left(self.src, v + 1) for v in range(V)]
        self.pairs = [(g, self.group[t, s]) for g, (s, t) in enumerate(self.edges)
                      if s < t and (t, s) in self.group]
        self.loops = [g for g, (s, t) in enumerate(self.edges) if s == t]
        lanes = bytearray(2 * G)
        lanes[0::2] = self.full_counts
        lanes[1::2] = b"\x01" * G
        self._full_lanes = int.from_bytes(lanes, "little")
        self._guard = int.from_bytes(b"\x00\x01" * G, "little")
        self._lanes = bytearray(2 * G)
        self._memo = [dict() for _ in range(V)]
        self._memo_size = 0

    # -- position --------------------------------------------------------
    def position(self, manifest, allow_initial_used=True):
        require(isinstance(manifest, dict), "position must be an object")
        require("initial_syllable" in manifest, "missing initial_syllable")
        start = self.dueum(manifest["initial_syllable"])
        require(start in self.vertex, "initial syllable is outside the model")
        current = self.vertex[start]
        history = manifest.get("history")
        require(isinstance(history, list), "history must be an explicit list")
        initially_used = manifest.get("initial_used_words", [])
        require(isinstance(initially_used, list), "initial_used_words must be a list")
        if not allow_initial_used:
            require(not initially_used,
                    "initial_used_words is not a game history; pass --allow-initial-used")
        counts = bytearray(self.full_counts)
        used = set()
        for word in initially_used:
            require(isinstance(word, str) and word in self.endpoints,
                    f"unknown initially used word: {word!r}")
            require(word not in used, f"reused initially used word: {word}")
            counts[self.group[self.endpoints[word]]] -= 1
            used.add(word)
        for ply, word in enumerate(history, 1):
            require(isinstance(word, str) and word in self.endpoints,
                    f"unknown history word at ply {ply}: {word!r}")
            require(word not in used, f"reused history word at ply {ply}: {word}")
            source, target = self.endpoints[word]
            require(source == current, f"illegal history connection at ply {ply}: {word}")
            counts[self.group[source, target]] -= 1
            current = target
            used.add(word)
        return current, bytes(counts), used

    def check_numeric_input(self, data, current, counts):
        try:
            fields = [int(field) for field in data.decode("ascii").split()]
        except (UnicodeError, ValueError) as exc:
            raise VerificationError("invalid numeric solver input") from exc
        expected = [self.V, self.G, current]
        for (s, t), c in zip(self.edges, counts):
            expected.extend((s, t, c))
        require(fields == expected, "numeric solver input differs from dictionary/history")

    # -- normalization -------------------------------------------------------
    def _successors(self, vertex, pattern):
        base, dst = self.lo[vertex], self.dst
        mask, loop = 0, False
        for offset, nonzero in enumerate(pattern):
            if nonzero:
                target = dst[base + offset]
                if target == vertex:
                    loop = True
                else:
                    mask |= 1 << target
        return mask, loop

    def counts_within_dictionary(self, counts):
        """counts[g] <= full_counts[g] for every g, using 16-bit lanes of one big integer.

        Lane g of _full_lanes holds full[g] + 256 and lane g of the subtrahend holds
        counts[g] < 256, so no borrow crosses lanes and bit 8 of lane g survives iff
        counts[g] <= full[g]."""
        lanes = self._lanes
        lanes[0::2] = counts
        rest = self._full_lanes - int.from_bytes(lanes, "little")
        return rest & self._guard == self._guard

    def normalize(self, current, counts):
        """Return (canonical counts, static label 0/1, or -1 for an unresolved core)."""
        c = bytearray(counts)
        # 1. reciprocal pair cancellation and self-loop parity
        for first, reverse in self.pairs:
            a = c[first]
            if a:
                b = c[reverse]
                if b:
                    if a <= b:
                        c[first] = 0
                        c[reverse] = b - a
                    else:
                        c[first] = a - b
                        c[reverse] = 0
        for g in self.loops:
            if c[g] > 1:
                c[g] &= 1
        # 2. forward reachability from the current vertex (bitset BFS)
        pattern = c.translate(_NONZERO)
        lo, hi, memo = self.lo, self.hi, self._memo
        succ = {}
        reached = 1 << current
        order = [current]
        index = 0
        while index < len(order):
            s = order[index]
            index += 1
            key = bytes(pattern[lo[s]:hi[s]])
            entry = memo[s].get(key)
            if entry is None:
                entry = self._successors(s, key)
                if self._memo_size > 4_000_000:
                    for table in memo:
                        table.clear()
                    self._memo_size = 0
                memo[s][key] = entry
                self._memo_size += 1
            succ[s] = entry
            fresh = entry[0] & ~reached
            while fresh:
                low = fresh & -fresh
                reached |= low
                order.append(low.bit_length() - 1)
                fresh ^= low
        # 3. least fixed point of the static rules, restricted to reachable vertices
        #    (reachable vertices only have reachable successors)
        losing = winning = 0
        pending = order
        while pending:
            rest = []
            for s in pending:
                mask, loop = succ[s]
                if mask & losing:
                    winning |= 1 << s
                elif not mask & ~winning:
                    if loop:
                        winning |= 1 << s
                    else:
                        losing |= 1 << s
                else:
                    rest.append(s)
            if len(rest) == len(pending):
                break
            pending = rest
        known = losing | winning
        here = 1 << current
        out = bytearray(len(c))
        if known & here:
            for s in order:
                out[lo[s]:hi[s]] = c[lo[s]:hi[s]]
            return bytes(out), (1 if winning & here else 0)
        # 4. unknown core: unknown vertices reachable by unknown->unknown edges
        seen = here
        stack = [current]
        core = []
        while stack:
            s = stack.pop()
            core.append(s)
            fresh = succ[s][0] & ~known & ~seen
            while fresh:
                low = fresh & -fresh
                seen |= low
                stack.append(low.bit_length() - 1)
                fresh ^= low
        dst = self.dst
        for s in core:
            a, b = lo[s], hi[s]
            if succ[s][0] & known:
                for g in range(a, b):
                    if c[g] and not (known >> dst[g]) & 1:
                        out[g] = c[g]
            else:
                out[a:b] = c[a:b]
        return bytes(out), -1


class CEngine:
    """ctypes wrapper around fastnorm.c (same canonicalization, compiled)."""

    def __init__(self, model, library=None):
        library = library or str(Path(__file__).resolve().with_name("fastnorm.so"))
        lib = ctypes.CDLL(library)
        def ints(values):
            return (ctypes.c_int * max(1, len(values)))(*values)
        self._keep = [ints(model.src), ints(model.dst), ints(model.lo), ints(model.hi),
                      ints([a for a, _ in model.pairs]), ints([b for _, b in model.pairs]),
                      ints(model.loops)]
        src, dst, lo, hi, pa, pb, loops = self._keep
        require(lib.fn_init(model.V, model.G, src, dst, lo, hi, len(model.pairs), pa, pb,
                            len(model.loops), loops) == 0, "C engine initialisation failed")
        self._fn = lib.fn_normalize
        self._fn.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_char_p)
        self._fn.restype = ctypes.c_int
        self._out = ctypes.create_string_buffer(model.G)
        self._G = model.G

    def normalize(self, current, counts):
        out = self._out
        label = self._fn(current, bytes(counts), out)
        return out.raw, label


# --------------------------------------------------------------------------
class _HashingRaw(io.RawIOBase):
    """Raw reader that hashes exactly the bytes handed to the parser."""

    def __init__(self, handle, digest):
        self._handle, self._digest, self.size = handle, digest, 0

    def readable(self):
        return True

    def readinto(self, buffer):
        n = self._handle.readinto(buffer)
        if n:
            self._digest.update(memoryview(buffer)[:n])
            self.size += n
        return n


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


_DECODER = json.JSONDecoder(object_pairs_hook=_unique_keys)


def _parse(text, what, max_chars=None):
    if max_chars is not None:
        require(len(text) <= max_chars, f"{what}: line longer than {max_chars} characters")
    try:
        value = _DECODER.decode(text)
    except (ValueError, TypeError, RecursionError) as exc:
        raise VerificationError(f"invalid JSON in {what}: {exc}") from exc
    return value


INFORMATIONAL_POSITION_KEYS = {"dictionary_sha256", "current_syllable", "next_player",
                               "remaining_words", "legal_words"}
POSITION_KEYS = {"initial_syllable", "history", "initial_used_words"} | INFORMATIONAL_POSITION_KEYS


def _check_position_metadata(model, position, current, used, dictionary_sha256):
    unknown = set(position) - POSITION_KEYS
    require(not unknown, f"unknown position keys: {sorted(unknown)}")
    if "dictionary_sha256" in position:
        require(position["dictionary_sha256"] == dictionary_sha256,
                "position dictionary_sha256 does not match the dictionary")
    if "current_syllable" in position:
        require(position["current_syllable"] == model.syllables[current],
                "position current_syllable does not match the history")
    if "next_player" in position:
        require(position["next_player"] == ("A" if len(position["history"]) % 2 == 0 else "B"),
                "position next_player does not match the history parity")
    if "remaining_words" in position:
        value = position["remaining_words"]
        require(is_int(value) and value == len(model.words) - len(used),
                "position remaining_words is wrong")
    if "legal_words" in position:
        value = position["legal_words"]
        legal = sorted(w for w in model.words
                       if w not in used and model.endpoints[w][0] == current)
        require(isinstance(value, list) and all(isinstance(w, str) for w in value)
                and sorted(value) == legal, "position legal_words is wrong")


def verify_fast(dictionary_path, position_path, proof_path, input_path=None,
                expected_word_count=817, *, hardened=True, legacy_dueum=False,
                allow_initial_used=False, dictionary_sha256=PINNED_DICTIONARY_SHA256,
                max_line_chars=1 << 20, engine="python", crosscheck_every=64):
    started = time.monotonic()
    dictionary_bytes = Path(dictionary_path).read_bytes()
    dict_digest = hashlib.sha256(dictionary_bytes).hexdigest()
    if hardened and dictionary_sha256:
        require(dict_digest == dictionary_sha256,
                f"dictionary sha256 {dict_digest} is not the pinned {dictionary_sha256}")
    position_bytes = Path(position_path).read_bytes()
    try:
        position = json.loads(position_bytes, object_pairs_hook=_unique_keys)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise VerificationError(f"invalid position JSON: {exc}") from exc
    model = Model(dictionary_bytes, expected_word_count,
                  dueum_legacy if legacy_dueum else dueum_standard)
    root_vertex, initial_counts, used = model.position(
        position, allow_initial_used=(allow_initial_used or not hardened))
    if hardened:
        _check_position_metadata(model, position, root_vertex, used, dict_digest)
    expected_root, _ = model.normalize(root_vertex, initial_counts)
    normalize = model.normalize
    crosschecked = [0]
    if engine == "c":
        c_engine = CEngine(model)
        require(c_engine.normalize(root_vertex, initial_counts)[0] == expected_root,
                "C engine disagrees with the Python engine on the root")
        fast = c_engine.normalize
        if crosscheck_every:
            calls = [0]

            def normalize(current, counts):
                result = fast(current, counts)
                calls[0] += 1
                if calls[0] % crosscheck_every == 0:
                    require(model.normalize(current, counts) == result,
                            "C engine disagrees with the Python engine")
                    crosschecked[0] += 1
                return result
        else:
            normalize = fast
    else:
        require(engine == "python", f"unknown engine {engine!r}")
    input_digest = None
    if input_path is not None:
        data = Path(input_path).read_bytes()
        model.check_numeric_input(data, root_vertex, initial_counts)
        input_digest = hashlib.sha256(data).hexdigest()

    V, G, lo, hi = model.V, model.G, model.lo, model.hi
    key = os.urandom(32)
    template = hashlib.blake2b(digest_size=16, key=key)

    vertex_tag = [v.to_bytes(2, "little") for v in range(V)]

    def digest_of(vertex, counts):
        h = template.copy()
        h.update(counts + vertex_tag[vertex])
        return h.digest()

    digests = bytearray()
    outcomes = bytearray()
    nodes = checked_moves = static_leaves = 0
    last_vertex, last_counts = None, None
    line_limit = max_line_chars if hardened else None
    proof_sha = hashlib.sha256()
    with open(proof_path, "rb", buffering=0) as handle:
        raw = _HashingRaw(handle, proof_sha)
        buffered = io.BufferedReader(raw, 1 << 20)
        compressed = buffered.peek(2)[:2] == b"\x1f\x8b"
        binary = gzip.GzipFile(fileobj=buffered, mode="rb") if compressed else buffered
        stream = io.TextIOWrapper(binary, encoding="utf-8")
        header = _parse(stream.readline(), "line 1", line_limit)
        require(isinstance(header, dict), "line 1 is not an object")
        require(header.get("format") == FORMAT, "unknown proof format")
        require(is_int(header.get("groups")) and header["groups"] == G,
                "proof group count differs from independently reconstructed model")
        require(is_int(header.get("vertices")) and header["vertices"] == V,
                "proof vertex count differs from independently reconstructed model")
        require(is_int(header.get("root")) and header["root"] >= 0, "invalid proof root id")
        if "input_sha256" in header:
            require(input_digest is not None, "input_sha256 requires --input")
            require(header["input_sha256"] == input_digest, "proof input hash mismatch")
        hex_length = 2 * G
        for line_number, line in enumerate(stream, 2):
            node = _parse(line, f"line {line_number}", line_limit)
            require(isinstance(node, dict), f"line {line_number} is not an object")
            identifier = nodes
            require(is_int(node.get("id")) and node["id"] == identifier,
                    f"line {line_number}: ids must be contiguous from zero")
            current = node.get("v")
            require(is_int(current) and 0 <= current < V, f"node {identifier}: invalid vertex")
            encoded = node.get("c")
            require(isinstance(encoded, str) and len(encoded) == hex_length,
                    f"node {identifier}: wrong count encoding length")
            try:
                counts = bytes.fromhex(encoded)
            except ValueError as exc:
                raise VerificationError(f"node {identifier}: invalid hex counts") from exc
            require(len(counts) == G, f"node {identifier}: count length mismatch")
            require(model.counts_within_dictionary(counts),
                    f"node {identifier}: counts exceed dictionary")
            canonical, static = normalize(current, counts)
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
                winning = result == "W"
                if winning:
                    require(len(moves) == 1, f"node {identifier}: W needs one witness")
                a, b = lo[current], hi[current]
                legal = set(compress(range(a, b), counts[a:b]))
                seen = set()
                wanted_child_outcome = 0 if winning else 1
                for move in moves:
                    require(type(move) is list and len(move) == 2
                            and is_int(move[0]) and is_int(move[1]),
                            f"node {identifier}: malformed move")
                    group, child_id = move
                    require(group in legal, f"node {identifier}: illegal move group")
                    require(group not in seen, f"node {identifier}: duplicate move group")
                    seen.add(group)
                    require(0 <= child_id < identifier,
                            f"node {identifier}: child must precede parent")
                    remaining = bytearray(counts)
                    remaining[group] -= 1
                    target = model.dst[group]
                    child_counts, _ = normalize(target, remaining)
                    offset = 16 * child_id
                    require(digests[offset:offset + 16] == digest_of(target, child_counts),
                            f"node {identifier}: incorrect child state")
                    require(outcomes[child_id] == wanted_child_outcome,
                            f"node {identifier}: child verdict contradicts minimax")
                    checked_moves += 1
                if not winning:
                    require(seen == legal, f"node {identifier}: losing node omits legal move")
            digests += digest_of(current, counts)
            outcomes.append(result == "W")
            nodes += 1
            last_vertex, last_counts = current, counts
        stream.detach()
        while buffered.read(1 << 20):
            pass  # hash any bytes the parser did not need (none for valid files)
    require(nodes, "empty certificate")
    require(header["root"] == nodes - 1, "root must be last node")
    require(last_vertex == root_vertex and last_counts == expected_root,
            "root does not match exact requested history")
    return {"verified": True, "format": FORMAT,
            "result_for_player_to_move": "W" if outcomes[-1] else "L",
            "current_syllable": model.syllables[root_vertex],
            "history": position["history"],
            "initial_used_words": position.get("initial_used_words", []),
            "position_is_pure_history": not position.get("initial_used_words"),
            "dictionary_words": len(model.words), "used_words": len(used),
            "checked_certificate_states": nodes, "checked_certificate_moves": checked_moves,
            "checked_static_leaves": static_leaves, "reduced_root_word_count": sum(expected_root),
            "dictionary_sha256": dict_digest,
            "dictionary_pinned": bool(hardened and dictionary_sha256),
            "position_sha256": hashlib.sha256(position_bytes).hexdigest(),
            "proof_sha256": proof_sha.hexdigest(), "proof_bytes": raw.size,
            "input_sha256": input_digest,
            "dueum": "legacy-verify.py" if legacy_dueum else "standard-10-12",
            "child_identity": "keyed-blake2b-128 (fresh random key per run)",
            "mode": "hardened" if hardened else "compat", "engine": engine,
            "c_engine_python_crosschecks": crosschecked[0],
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "legacy_lookup_trusted": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dictionary", required=True)
    parser.add_argument("--position", required=True)
    parser.add_argument("--proof", required=True)
    parser.add_argument("--input")
    parser.add_argument("--expected-word-count", type=int, default=817)
    parser.add_argument("--compat", action="store_true",
                        help="verify_v2 acceptance policy (no dictionary pin, lax position keys)")
    parser.add_argument("--legacy-dueum", action="store_true")
    parser.add_argument("--allow-initial-used", action="store_true")
    parser.add_argument("--engine", choices=("python", "c"), default="python",
                        help="c = ctypes fastnorm.so built from fastnorm.c in this folder")
    parser.add_argument("--crosscheck-every", type=int, default=64,
                        help="with --engine c, recompute every N-th normalization in Python (0 = off)")
    parser.add_argument("--dictionary-sha256", default=PINNED_DICTIONARY_SHA256,
                        help="pinned dictionary hash; empty string disables the pin")
    args = parser.parse_args(argv)
    try:
        report = verify_fast(args.dictionary, args.position, args.proof, args.input,
                             args.expected_word_count, hardened=not args.compat,
                             legacy_dueum=args.legacy_dueum,
                             allow_initial_used=args.allow_initial_used,
                             dictionary_sha256=args.dictionary_sha256, engine=args.engine,
                             crosscheck_every=args.crosscheck_every)
    except (VerificationError, OSError, EOFError, UnicodeError, MemoryError) as exc:
        print(json.dumps({"verified": False, "error": f"{type(exc).__name__}: {exc}"},
                         ensure_ascii=False))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
