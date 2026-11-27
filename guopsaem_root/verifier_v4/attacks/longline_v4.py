#!/usr/bin/env python3
"""Resource attack: one very long (valid JSON) line, plain and gzip.

The header line of a valid certificate is padded with N MB of spaces before its closing
brace (still valid JSON, still a valid certificate).  Measures wall time and peak RSS of
verify_v4.py and the C++ verifier.  ProofReader::getline in verify_v4.cpp rescans the whole
pending buffer for '\\n' after every 1 MB refill, so its time grows quadratically with the
line length; a gzip file of about 1/1000 of the line size is enough to trigger it.

Usage: longline_v4.py CASE_DIR WORKDIR MB [MB ...] [--gzip] [--cpp BINARY] [--no-py]
"""
import gzip
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import attack_lib as A  # noqa: E402


def measured(cmd):
    t = time.monotonic()
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = p.stdout.read()
    _, status, usage = os.wait4(p.pid, 0)
    return (os.waitstatus_to_exitcode(status), round(time.monotonic() - t, 2), round(usage.ru_maxrss / 1024),
            out.decode("utf-8", "replace")[:80].replace("\n", " "))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    use_gz = "--gzip" in sys.argv
    cpp = sys.argv[sys.argv.index("--cpp") + 1] if "--cpp" in sys.argv else A.CPP
    if "--cpp" in sys.argv:
        args.remove(cpp)
    case, work = Path(args[0]), Path(args[1])
    work.mkdir(parents=True, exist_ok=True)
    lines = (case / "proof.jsonl").read_text(encoding="utf-8").splitlines()
    for mb in map(int, args[2:]):
        head = lines[0][:-1] + " " * (mb << 20) + "}"
        data = ("\n".join([head] + lines[1:]) + "\n").encode()
        proof = work / ("long.jsonl.gz" if use_gz else "long.jsonl")
        proof.write_bytes(gzip.compress(data, 9) if use_gz else data)
        size = proof.stat().st_size
        del data, head
        base = ["--dictionary", str(case / "d.txt"), "--expected-word-count", "0", "--position", str(case / "p.json"),
                "--proof", str(proof)]
        r = {"cpp": measured(["nice", "-n", "5", cpp] + base)}
        if "--no-py" not in sys.argv:
            r["py"] = measured(["nice", "-n", "5", sys.executable, A.PY] + base)
        print(f"{mb} MB line, file {size} bytes: " + "; ".join(f"{k}: exit {v[0]} {v[1]} s {v[2]} MB [{v[3]}]"
                                                              for k, v in r.items()), flush=True)
        proof.unlink()


if __name__ == "__main__":
    main()
