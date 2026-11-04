#!/usr/bin/env python3
"""Shared helpers for the route-proof-v4 attack suite (attacks/*.py).

- small random dictionaries (same generator as verifier_v3/test_v3_bruteforce.py);
- valid v4 certificates from the patched solver (build/solver_v4_pf --proof-format v4);
- an independent certificate writer (ModelV3 replay + memoized minimax) that can emit
  any well-formed certificate shape, including deliberately false ones;
- running verify_v4.py (in process, with the same exception filter as its main()) and the
  C++ verifier (subprocess) on the same files;
- the true value of a position by raw brute force over words (no model).
"""
import gzip
import json
import os
import random
import subprocess
import sys
import zlib
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve()
V4 = HERE.parents[1]
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "verifier_v3"))
sys.path.insert(0, str(V4))
from verify_v3 import ModelV3, VerificationError, conv  # noqa: E402
from test_v3_bruteforce import random_dictionary  # noqa: E402
import verify_v4  # noqa: E402

SOLVER = str(V4 / "build" / "solver_v4_pf")
CPP = os.environ.get("VERIFY_V4_CPP", str(V4 / "build" / "verify_v4"))
PY = str(V4 / "verify_v4.py")
V3PY = str(ROOT / "verifier_v3" / "verify_v3.py")
CAUGHT = (VerificationError, OSError, EOFError, ValueError, zlib.error, MemoryError)  # verify_v4.main()


def raw_value(words, start_syllable, used_words):
    """True if the player who receives start_syllable wins (plain rule, no model)."""
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
    return value(start_syllable, sum(1 << index[w] for w in used_words))


def position_truth(words, pos):
    hist = pos.get("history", [])
    start = hist[-1][-1] if hist else pos["initial_syllable"]
    return "W" if raw_value(words, start, list(pos.get("initial_used_words", [])) + list(hist)) else "L"


def random_case(rng, history_prob=0.4, used_prob=0.12):
    words = random_dictionary(rng)
    if rng.random() < 0.6:
        words = sorted(set(words) | set(random_dictionary(rng)))
    if rng.random() < 0.3:
        words = sorted(set(words) | set(random_dictionary(rng)))
    model = ModelV3(" ".join(words).encode(), 0)
    starts = sorted({w[-1] for w in words} | model.starts)
    initial = rng.choice(starts)
    used = [w for w in words if rng.random() < used_prob]
    history = []
    if rng.random() < history_prob:
        cur = model.vertex_of(initial)
        for _ in range(rng.randint(1, 2)):
            options = [w for w in words if w not in used and w not in history and w[0] in model.keys[cur]]
            if not options:
                break
            w = rng.choice(options)
            history.append(w)
            cur = model.vertex_of(w[-1])
    pos = {"initial_syllable": initial, "history": history, "initial_used_words": used}
    return words, model, pos


def write_case(work, words, model, pos, sep=" "):
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    d, p, inp = work / "d.txt", work / "p.json", work / "in.txt"
    d.write_text(sep.join(words), encoding="utf-8")
    p.write_text(json.dumps(pos, ensure_ascii=False), encoding="utf-8")
    cur, counts, _ = model.position(pos)
    inp.write_bytes(model.numeric_input(cur, counts))
    return d, p, inp


def solve(inp, proof, fmt="v4", seconds=20):
    r = subprocess.run([SOLVER, str(inp), "--seconds", str(seconds), "--tt-mb", "16", "--threads", "1",
                        "--proof", str(proof), "--proof-format", fmt], capture_output=True, text=True)
    out = json.loads(r.stdout.strip().splitlines()[-1])
    return out


def read_proof_lines(path):
    data = Path(path).read_bytes()
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return data.decode("utf-8").splitlines()


def dumps(obj):
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def run_py(d, p, proof, inp=None, digest_only=False, expected=0):
    """verify_v4.py in process. Returns ("accept", result) / ("reject", msg) / ("crash", repr)."""
    try:
        r = verify_v4.verify_v4(d, p, proof, inp, expected, digest_only)
        return ("accept", r["result_for_player_to_move"])
    except CAUGHT as exc:
        return ("reject", str(exc)[:200])
    except Exception as exc:  # noqa: BLE001 - anything else escapes main() as a traceback
        return ("crash", f"{type(exc).__name__}: {exc}"[:300])


def run_py_sub(d, p, proof, inp=None, digest_only=False, expected=0, timeout=600):
    cmd = [sys.executable, PY, "--dictionary", str(d), "--expected-word-count", str(expected),
           "--position", str(p), "--proof", str(proof)]
    if inp:
        cmd += ["--input", str(inp)]
    if digest_only:
        cmd.append("--digest-only")
    return _run(cmd, timeout)


def run_v3_sub(d, p, proof, inp=None, expected=0, timeout=600):
    cmd = [sys.executable, V3PY, "--dictionary", str(d), "--expected-word-count", str(expected),
           "--position", str(p), "--proof", str(proof)]
    if inp:
        cmd += ["--input", str(inp)]
    return _run(cmd, timeout)


def run_cpp(d, p, proof, inp=None, digest_only=False, expected=0, binary=None, timeout=600, extra=()):
    cmd = [binary or CPP, "--dictionary", str(d), "--expected-word-count", str(expected),
           "--position", str(p), "--proof", str(proof)]
    if inp:
        cmd += ["--input", str(inp)]
    if digest_only:
        cmd.append("--digest-only")
    cmd += list(extra)
    return _run(cmd, timeout)


def _run(cmd, timeout):
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return ("timeout", " ".join(cmd))
    out = r.stdout.decode("utf-8", "replace")
    if r.returncode == 0:
        try:
            return ("accept", json.loads(out)["result_for_player_to_move"])
        except (ValueError, KeyError):
            return ("crash", "exit 0 without JSON: " + out[:200])
    if r.returncode == 1 and out.startswith('{"verified": false'):
        return ("reject", json.loads(out)["error"][:200])
    return ("crash", f"exit {r.returncode}: {out[-200:]} {r.stderr.decode('utf-8', 'replace')[-300:]}")


class Writer:
    """Independent certificate writer from ModelV3 (memoized minimax over canonical states).

    nodes are emitted bottom-up; build(vertex, counts) returns the id of the node for that
    canonical state.  choose_w(i, winning_moves) picks the W witness; result overrides can
    be injected through `lie` (state key -> forced result string) to produce false claims."""

    def __init__(self, model, rng=None, share=True):
        self.model = model
        self.rng = rng or random.Random(0)
        self.share = share
        self.lines = []
        self.memo = {}
        self.value_memo = {}

    budget = None   # maximum number of distinct states for value(); None = unlimited

    def value(self, v, c):
        key = (v, c)
        if key in self.value_memo:
            return self.value_memo[key]
        if self.budget is not None and len(self.value_memo) >= self.budget:
            raise OverflowError("state budget exceeded")
        _, static = self.model.normalize(v, c)
        if static != -1:
            res = bool(static)
        else:
            res = False
            for g in self.model.available[v]:
                if c[g]:
                    tv, tc, _ = self.model.child(v, c, g)
                    if not self.value(tv, tc):
                        res = True
                        break
        self.value_memo[key] = res
        return res

    def build(self, v, c):
        key = (v, c)
        if self.share and key in self.memo:
            return self.memo[key]
        _, static = self.model.normalize(v, c)
        if static != -1:
            node = {"id": None, "r": "W" if static else "L", "m": []}
        else:
            win = self.value(v, c)
            moves = []
            legal = [g for g in self.model.available[v] if c[g]]
            if win:
                good = []
                for g in legal:
                    tv, tc, _ = self.model.child(v, c, g)
                    if not self.value(tv, tc):
                        good.append((g, tv, tc))
                g, tv, tc = self.rng.choice(good)
                moves.append([g, self.build(tv, tc)])
            else:
                for g in legal:
                    tv, tc, _ = self.model.child(v, c, g)
                    moves.append([g, self.build(tv, tc)])
                self.rng.shuffle(moves)
            node = {"id": None, "r": "W" if win else "L", "m": moves}
        node["id"] = len(self.lines)
        self.lines.append(node)
        self.memo[key] = node["id"]
        return node["id"]

    def header(self, input_sha=None):
        h = {"format": "route-proof-v4", "groups": len(self.model.edges), "vertices": len(self.model.keys),
             "root": len(self.lines) - 1}
        if input_sha:
            h["input_sha256"] = input_sha
        return h

    def text(self, input_sha=None):
        return "\n".join([dumps(self.header(input_sha))] + [dumps(n) for n in self.lines]) + "\n"


def root_state(model, pos):
    cur, counts, _ = model.position(pos)
    rs, _ = model.normalize(cur, counts)
    return cur, rs
