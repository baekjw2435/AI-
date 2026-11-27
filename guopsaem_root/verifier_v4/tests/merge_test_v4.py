#!/usr/bin/env python3
"""merge_root_v4.py test: for ROOT, solve every child position (ROOT + one word per legal
group) in v4 format, merge, verify the merged certificate with verify_v4.py and verify_v4
(C++), and compare with the solver's direct result for ROOT.  Then the same for ROOT2 =
ROOT + a move to an L child (an L root: every child certificate is needed).
Usage: merge_test_v4.py SOLVER VERIFY_CPP DICT WORD_COUNT ROOT_POS.json WORKDIR"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2] / "verifier_v3"))
sys.path.insert(0, str(HERE.parents[1]))
from verify_v3 import ModelV3  # noqa: E402
from verify_v4 import verify_v4  # noqa: E402

solver, cpp, dic, nwords, rootpos, work = sys.argv[1:7]
nwords = int(nwords)
work = Path(work)
work.mkdir(parents=True, exist_ok=True)
m = ModelV3(Path(dic).read_bytes(), nwords)


def solve(pos, tag, seconds="120"):
    cur, counts, _ = m.position(pos)
    (work / f"{tag}.json").write_text(json.dumps(pos, ensure_ascii=False), encoding="utf-8")
    (work / f"{tag}.txt").write_bytes(m.numeric_input(cur, counts))
    r = subprocess.run([solver, str(work / f"{tag}.txt"), "--seconds", seconds, "--tt-mb", "512", "--threads", "1",
                        "--proof", str(work / f"{tag}.jsonl.gz"), "--proof-format", "v4"], capture_output=True, text=True)
    res = json.loads(r.stdout.strip().splitlines()[-1])
    if res["result"] not in ("win", "loss") or res["proof_error"]:
        return None                      # unproven child: left out of the merge
    return res["result"]


def children(pos):
    cur, counts, used = m.position(pos)
    canon, static = m.normalize(cur, counts)
    assert static == -1
    out, seen = [], set()
    for w in m.words:
        g = m.word_group(w)
        if w in used or w[0] not in m.keys[cur] or not canon[g] or g in seen:
            continue
        seen.add(g)
        out.append(dict(pos, history=pos["history"] + [w]))
    return out


def check(pos, tag):
    direct = solve(pos, tag)
    assert direct is not None
    specs, kids = [], {}
    for k, child in enumerate(children(pos)):
        ctag = f"{tag}_c{k}"
        kids[ctag] = (child, solve(child, ctag, "30"))
        if kids[ctag][1] is not None:
            specs.append(f"{work / ctag}.json:{work / ctag}.jsonl.gz")
    for dedup in ([], ["--dedup"]):
        merged = merge_and_verify(tag, specs, direct, dedup)
    return kids


def merge_and_verify(tag, specs, direct, dedup):
    out = work / f"{tag}_merged{'_dedup' if dedup else ''}.jsonl.gz"
    r = subprocess.run([sys.executable, str(HERE.parents[1] / "merge_root_v4.py"), dic, str(nwords),
                        str(work / f"{tag}.json"), str(out)] + specs + ["--input", str(work / f"{tag}.txt")] + dedup,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    merged = json.loads(r.stdout)
    v = verify_v4(dic, work / f"{tag}.json", out, work / f"{tag}.txt", nwords)
    c = subprocess.run([cpp, "--dictionary", dic, "--expected-word-count", str(nwords), "--position", str(work / f"{tag}.json"),
                        "--proof", str(out), "--input", str(work / f"{tag}.txt")], capture_output=True, text=True)
    cj = json.loads(c.stdout)
    assert c.returncode == 0 and cj["verified"] is True, c.stdout
    want = "W" if direct == "win" else "L"
    assert v["result_for_player_to_move"] == cj["result_for_player_to_move"] == merged["root_result"] == want
    assert v["unreached_nodes"] == cj["unreached_nodes"] == 0
    summary = {"root": tag, "dedup": bool(dedup), "direct": direct, "merged_root": merged["root_result"],
               "child_certificates": len(specs), "children_used": merged["children_used"],
               "merged_nodes": merged["nodes"], "nodes_before_dedup": merged.get("nodes_before_dedup"),
               "verified_states": v["checked_certificate_states"], "unreached": v["unreached_nodes"]}
    print(json.dumps(summary), flush=True)
    return merged


root = json.loads(Path(rootpos).read_text(encoding="utf-8"))
kids = check(root, "root")
losing = [child for child, res in kids.values() if res == "loss"]
if losing:
    check(losing[0], "root2")
else:
    winning = [child for child, res in kids.values()]
    check(winning[0], "root2")
print(json.dumps({"ok": True}))
