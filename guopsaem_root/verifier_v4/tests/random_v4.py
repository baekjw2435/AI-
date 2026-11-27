#!/usr/bin/env python3
"""Random small dictionaries: patched solver in v3 and v4 format; verify_v3 on v3,
verify_v4.py and verify_v4 (C++) on v4 (exact and --digest-only); all must accept and
agree with a raw brute force of the word game.  The v4 file must equal the v3 file
with "v" and "c" removed (same ids, results and moves).
Usage: random_v4.py SOLVER VERIFY_CPP WORKDIR [COUNT] [SEED]"""
import json
import random
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "verifier_v3"))
sys.path.insert(0, str(ROOT / "verifier_v4"))
from verify_v3 import ModelV3, verify_v3  # noqa: E402
from test_v3_bruteforce import random_dictionary, raw_solver  # noqa: E402
from verify_v4 import verify_v4  # noqa: E402

SAME_FIELDS = ["result_for_player_to_move", "initial_syllable", "current_vertex", "history", "initial_used_words",
               "dictionary_words", "used_words", "model_vertices", "model_groups", "shared_groups",
               "checked_certificate_states", "checked_certificate_moves", "checked_static_leaves",
               "reduced_root_word_count", "certificate_nodes", "unreached_nodes", "dictionary_sha256",
               "position_sha256", "proof_sha256", "input_sha256"]


def main():
    solver, cpp, work = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    count = int(sys.argv[4]) if len(sys.argv) > 4 else 200
    rng = random.Random(int(sys.argv[5]) if len(sys.argv) > 5 else 11)
    work.mkdir(parents=True, exist_ok=True)
    stats = {"positions": 0, "with_shared_groups": 0, "with_history": 0, "W": 0, "L": 0,
             "max_states": 0, "total_states": 0, "gzip": 0}
    for i in range(count):
        words = random_dictionary(rng)
        if rng.random() < 0.6:
            words = sorted(set(words) | set(random_dictionary(rng)))
        if rng.random() < 0.3:
            words = sorted(set(words) | set(random_dictionary(rng)))
        model = ModelV3(" ".join(words).encode(), 0)
        stats["with_shared_groups"] += any(model.shared)
        starts = sorted({w[-1] for w in words} | model.starts)
        initial = rng.choice(starts)
        used = [w for w in words if rng.random() < 0.12]
        history = []
        if rng.random() < 0.4:   # play one or two real moves first (exercises the history replay)
            cur = model.vertex_of(initial)
            for _ in range(rng.randint(1, 2)):
                options = [w for w in words if w not in used and w not in history and w[0] in model.keys[cur]]
                if not options:
                    break
                w = rng.choice(options)
                history.append(w)
                cur = model.vertex_of(w[-1])
        stats["with_history"] += bool(history)
        pos = {"initial_syllable": initial, "history": history, "initial_used_words": used}
        d, p, inp = work / "d.txt", work / "p.json", work / "in.txt"
        d.write_text(" ".join(words), encoding="utf-8")
        p.write_text(json.dumps(pos, ensure_ascii=False), encoding="utf-8")
        cur, counts, _ = model.position(pos)
        inp.write_bytes(model.numeric_input(cur, counts))
        gz = ".gz" if i % 3 == 0 else ""
        stats["gzip"] += bool(gz)
        out = {}
        for fmt in ("v3", "v4"):
            proof = work / f"pf_{fmt}.jsonl{gz}"
            r = subprocess.run([solver, str(inp), "--seconds", "20", "--tt-mb", "16", "--threads", "1", "--selfcheck", "1",
                                "--proof", str(proof), "--proof-format", fmt], capture_output=True, text=True)
            out[fmt] = json.loads(r.stdout.strip().splitlines()[-1])
            assert out[fmt]["result"] in ("win", "loss") and not out[fmt]["proof_error"], (out[fmt], words, pos)
        # same structure in both formats
        import gzip
        op = (lambda f: gzip.open(f, "rt", encoding="utf-8")) if gz else (lambda f: open(f, encoding="utf-8"))
        with op(work / f"pf_v3.jsonl{gz}") as a, op(work / f"pf_v4.jsonl{gz}") as b:
            la, lb = a.read().splitlines(), b.read().splitlines()
        ha, hb = json.loads(la[0]), json.loads(lb[0])
        assert ha.pop("format") == "route-proof-v3" and hb.pop("format") == "route-proof-v4" and ha == hb
        assert len(la) == len(lb)
        for x, y in zip(la[1:], lb[1:]):
            x = json.loads(x)
            del x["v"], x["c"]
            assert x == json.loads(y), (x, y)
        v3 = verify_v3(d, p, work / f"pf_v3.jsonl{gz}", inp, 0)
        v4 = verify_v4(d, p, work / f"pf_v4.jsonl{gz}", inp, 0)
        v4d = verify_v4(d, p, work / f"pf_v4.jsonl{gz}", inp, 0, True)
        runs = []
        for extra in ([], ["--digest-only"]):
            r = subprocess.run([cpp, "--dictionary", str(d), "--expected-word-count", "0", "--position", str(p),
                                "--proof", str(work / f"pf_v4.jsonl{gz}"), "--input", str(inp)] + extra,
                               capture_output=True, text=True)
            assert r.returncode == 0, (r.stdout, r.stderr, words, pos)
            runs.append(json.loads(r.stdout))
        c4, c4d = runs
        index, raw = raw_solver(words)
        start_syllable = history[-1][-1] if history else initial
        expected = raw(start_syllable, sum(1 << index[w] for w in used + history))
        want = "W" if expected else "L"
        assert v3["result_for_player_to_move"] == want == ("W" if out["v4"]["result"] == "win" else "L"), (words, pos)
        for r in (v4, v4d, c4, c4d):
            assert r["verified"] is True
            assert all(r[k] == v4[k] for k in SAME_FIELDS), ({k: (r[k], v4[k]) for k in SAME_FIELDS if r[k] != v4[k]}, words, pos)
        assert v4["unreached_nodes"] == 0 and v4["checked_certificate_states"] == v3["checked_certificate_states"]
        assert v4["checked_certificate_moves"] == v3["checked_certificate_moves"]
        assert v4["checked_static_leaves"] == v3["checked_static_leaves"]
        stats["positions"] += 1
        stats[want] += 1
        stats["max_states"] = max(stats["max_states"], v4["checked_certificate_states"])
        stats["total_states"] += v4["checked_certificate_states"]
    stats["ok"] = True
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
