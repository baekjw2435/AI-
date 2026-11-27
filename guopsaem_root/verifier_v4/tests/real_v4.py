#!/usr/bin/env python3
"""Real positions (3,436-word list): solve in v3 and v4 format with the patched solver, then
verify_v3 (v3 file), verify_v4.py and verify_v4 C++ (v4 file; exact and --digest-only).
All verifiers must accept and agree with the solver.  Reports file sizes, wall time and
peak RSS (os.wait4 ru_maxrss) of every verifier run.

Usage: real_v4.py SOLVER VERIFY_CPP WORKDIR [--res-dir DIR --pos-dir DIR --in-dir DIR]
                  [--extra NAME:POS.json:IN.txt ...] [--seconds S] [--tt-mb M] [--skip-py-digest]
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DICT = ROOT / "words_3436.txt"


def measured(cmd, out_path):
    """Run cmd, stdout to out_path; return (returncode, wall seconds, peak RSS MB, parsed JSON or None)."""
    t = time.monotonic()
    with open(out_path, "wb") as out:
        p = subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT)
        _, status, usage = os.wait4(p.pid, 0)
    wall = time.monotonic() - t
    p.returncode = os.waitstatus_to_exitcode(status)
    text = Path(out_path).read_text(encoding="utf-8", errors="replace")
    try:
        parsed = json.loads(text[text.index("{"):]) if "{" in text else None
    except ValueError:
        parsed = None
    return p.returncode, round(wall, 3), round(usage.ru_maxrss / 1024, 1), parsed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("solver")
    ap.add_argument("cpp")
    ap.add_argument("work")
    ap.add_argument("--res-dir")
    ap.add_argument("--pos-dir")
    ap.add_argument("--in-dir")
    ap.add_argument("--extra", action="append", default=[])
    ap.add_argument("--seconds", default="60")
    ap.add_argument("--tt-mb", default="512")
    ap.add_argument("--skip-py-digest", action="store_true")
    ap.add_argument("--keep", action="store_true", help="keep the certificates")
    a = ap.parse_args()
    work = Path(a.work)
    work.mkdir(parents=True, exist_ok=True)
    jobs = []
    if a.res_dir:
        for f in sorted(Path(a.res_dir).glob("*.json")):
            res = json.loads(f.read_text(encoding="utf-8"))
            if res["solver"]["result"] in ("win", "loss"):
                jobs.append((f.stem, Path(a.pos_dir) / f"{f.stem}.json", Path(a.in_dir) / f"{f.stem}.txt",
                             res["solver"]["result"]))
    for e in a.extra:
        name, pos, inp = e.split(":")
        jobs.append((name, Path(pos), Path(inp), None))
    py = sys.executable
    rows = []
    for name, pos, inp, known in jobs:
        row = {"name": name}
        for fmt in ("v3", "v4"):
            proof = work / f"{name}.{fmt}.jsonl.gz"
            t = time.monotonic()
            r = subprocess.run([a.solver, str(inp), "--seconds", a.seconds, "--tt-mb", a.tt_mb, "--threads", "1",
                                "--proof", str(proof), "--proof-format", fmt], capture_output=True, text=True)
            s = json.loads(r.stdout.strip().splitlines()[-1])
            assert s["result"] in ("win", "loss") and not s["proof_error"], (name, fmt, s)
            if known:
                assert s["result"] == known, (name, s["result"], known)
            row[f"solver_{fmt}"] = {"result": s["result"], "proof_nodes": s["proof_nodes"], "mid_calls": s["mid_calls"],
                                    "seconds_total": round(time.monotonic() - t, 2)}
            row[f"size_{fmt}_gz"] = proof.stat().st_size
        assert row["solver_v3"]["proof_nodes"] == row["solver_v4"]["proof_nodes"]
        common = ["--dictionary", str(DICT), "--expected-word-count", "3436", "--position", str(pos), "--input", str(inp)]
        runs = {
            "verify_v3.py": [py, str(ROOT / "verifier_v3" / "verify_v3.py")] + common + ["--proof", str(work / f"{name}.v3.jsonl.gz")],
            "verify_v4.py": [py, str(ROOT / "verifier_v4" / "verify_v4.py")] + common + ["--proof", str(work / f"{name}.v4.jsonl.gz")],
            "verify_v4.py --digest-only": [py, str(ROOT / "verifier_v4" / "verify_v4.py")] + common
            + ["--proof", str(work / f"{name}.v4.jsonl.gz"), "--digest-only"],
            "verify_v4 (C++)": [a.cpp] + common + ["--proof", str(work / f"{name}.v4.jsonl.gz")],
            "verify_v4 (C++) --digest-only": [a.cpp] + common + ["--proof", str(work / f"{name}.v4.jsonl.gz"), "--digest-only"],
        }
        if a.skip_py_digest:
            del runs["verify_v4.py --digest-only"]
        want = "W" if row["solver_v4"]["result"] == "win" else "L"
        states = set()
        for label, cmd in runs.items():
            rc, wall, rss, out = measured(cmd, work / "verifier.out")
            assert rc == 0 and out and out["verified"] is True, (name, label, rc, out)
            assert out["result_for_player_to_move"] == want, (name, label, out)
            states.add((out["checked_certificate_states"], out["checked_certificate_moves"], out["checked_static_leaves"]))
            assert out.get("unreached_nodes", 0) == 0
            row[label] = {"seconds": wall, "peak_rss_mb": rss}
        assert len(states) == 1, (name, states)
        row["states"], row["moves"], row["static_leaves"] = states.pop()
        row["size_ratio_v3_over_v4"] = round(row["size_v3_gz"] / row["size_v4_gz"], 2)
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
        if not a.keep:
            for fmt in ("v3", "v4"):
                (work / f"{name}.{fmt}.jsonl.gz").unlink()
    print(json.dumps({"positions": len(rows), "ok": True}))


if __name__ == "__main__":
    main()
