#!/usr/bin/env python3
"""Corrupted route-proof-v4 certificates must be rejected by verify_v4.py AND verify_v4 (C++).

Usage: corrupt_v4.py VERIFY_CPP DICT WORD_COUNT POS.json PROOF[.gz] INPUT.txt WORKDIR
The original certificate must verify.  Each corruption kind is applied where the
certificate has a suitable node (reached states are re-derived here with ModelV3 to
pick targets, e.g. a node re-reached with a different state).  Prints, per kind,
whether it was applicable and that both verifiers rejected it.
"""
import gzip
import json
import random
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "verifier_v3"))
sys.path.insert(0, str(ROOT / "verifier_v4"))
from verify_v3 import ModelV3, VerificationError  # noqa: E402
import verify_v4  # noqa: E402


def read_lines(path):
    with open(path, "rb") as f:
        gz = f.read(2) == b"\x1f\x8b"
    with (gzip.open(path, "rb") if gz else open(path, "rb")) as f:
        return f.read().decode("utf-8").splitlines()


def dump(node):
    return json.dumps(node, separators=(",", ":"))


def main():
    cpp, dic, nwords, posf, proof, inp, work = sys.argv[1:8]
    nwords = int(nwords)
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    rng = random.Random(5)
    lines = read_lines(proof)
    header = json.loads(lines[0])
    nodes = [json.loads(x) for x in lines[1:]]
    model = ModelV3(Path(dic).read_bytes(), nwords)
    cur, counts, _ = model.position(json.loads(Path(posf).read_text(encoding="utf-8")))
    root_counts, _ = model.normalize(cur, counts)
    # re-derive states (vertex, counts, static, legal groups) of reached nodes
    state = {len(nodes) - 1: (cur, root_counts)}
    stack = [len(nodes) - 1]
    info = {}
    parents = {}
    while stack:
        i = stack.pop()
        v, c = state[i]
        _, static = model.normalize(v, c)
        legal = [g for g in model.available[v] if c[g]]
        info[i] = (v, c, static, legal)
        for g, ch in nodes[i]["m"]:
            parents.setdefault(ch, []).append(i)
            if ch not in state:
                tv, tc, _ = model.child(v, c, g)
                state[ch] = (tv, tc)
                stack.append(ch)
    reached = sorted(info)
    L_multi = [i for i in reached if info[i][2] == -1 and nodes[i]["r"] == "L" and len(nodes[i]["m"]) >= 2]
    L_any = [i for i in reached if info[i][2] == -1 and nodes[i]["r"] == "L"]
    W_ns = [i for i in reached if info[i][2] == -1 and nodes[i]["r"] == "W"]
    statics = [i for i in reached if info[i][2] != -1]
    nonstatic = [i for i in reached if info[i][2] == -1]

    def pick(xs):
        return rng.choice(xs) if xs else None

    cases = []

    def add(kind, mutated_nodes=None, header_obj=None, raw=None, gz=False):
        cases.append((kind, mutated_nodes, header_obj, raw, gz))

    def clone():
        return [dict(n, m=[list(x) for x in n["m"]]) for n in nodes]

    # 1 flip a result (root, and a random reached non-root node)
    ns = clone(); ns[-1]["r"] = "L" if ns[-1]["r"] == "W" else "W"; add("flip_result_root", ns)
    if len(reached) > 1:
        i = pick([x for x in reached if x != len(nodes) - 1]); ns = clone(); ns[i]["r"] = "L" if ns[i]["r"] == "W" else "W"
        add("flip_result_inner", ns)
    # 2 drop a move from an L node
    i = pick(L_any)
    if i is not None:
        ns = clone(); ns[i]["m"].pop(rng.randrange(len(ns[i]["m"]))); add("drop_move_from_L", ns)
    # 3 duplicate a move
    i = pick(L_any or W_ns)
    if i is not None:
        ns = clone(); ns[i]["m"].append(list(ns[i]["m"][0])); add("duplicate_move", ns)
    # 4 illegal group (not legal in that state); on an L node any unlisted group is illegal
    i = pick(nonstatic)
    if i is not None:
        illegal = [g for g in range(len(model.edges)) if g not in info[i][3]]
        if illegal:
            ns = clone(); ns[i]["m"][0][0] = rng.choice(illegal); add("illegal_group", ns)
    # 4b group out of range
    i = pick(nonstatic)
    if i is not None:
        ns = clone(); ns[i]["m"][0][0] = len(model.edges); add("group_out_of_range", ns)
    # 5 child_id >= id
    i = pick(nonstatic)
    if i is not None:
        ns = clone(); ns[i]["m"][0][1] = i; add("child_id_equal_id", ns)
        if i + 1 < len(nodes):
            ns = clone(); ns[i]["m"][0][1] = i + 1; add("child_id_greater_id", ns)
    # 6 swap two child ids of an L node
    i = pick(L_multi)
    if i is not None:
        ns = clone(); a, b = ns[i]["m"][0], ns[i]["m"][1]; a[1], b[1] = b[1], a[1]; add("swap_child_ids", ns)
    # 7 extra move on a W node (a second, otherwise legal group pointing to an L node)
    i = pick(W_ns)
    if i is not None:
        others = [g for g in info[i][3] if g != nodes[i]["m"][0][0]]
        if others:
            ns = clone(); ns[i]["m"].append([others[0], ns[i]["m"][0][1]]); add("extra_move_on_W", ns)
        else:
            ns = clone(); ns[i]["m"].append(list(ns[i]["m"][0])); add("extra_move_on_W", ns)
    # 8 non-static node given no moves (L and W)
    i = pick(L_any)
    if i is not None:
        ns = clone(); ns[i]["m"] = []; add("nonstatic_L_no_moves", ns)
    i = pick(W_ns)
    if i is not None:
        ns = clone(); ns[i]["m"] = []; add("nonstatic_W_no_moves", ns)
    # 9 static claim on a non-static state (with and without moves)
    i = pick(nonstatic)
    if i is not None:
        ns = clone(); ns[i]["k"] = "static"; add("static_claim_nonstatic", ns)
        ns = clone(); ns[i]["k"] = "static"; ns[i]["m"] = []; add("static_claim_nonstatic_no_moves", ns)
    # 9b static leaf given a move
    i = pick(statics)
    if i is not None and i > 0:
        ns = clone(); ns[i]["m"] = [[info[i][3][0] if info[i][3] else 0, 0]]; add("static_leaf_with_move", ns)
    # 10 wrong header counts / root
    h = dict(header); h["groups"] += 1; add("header_groups_wrong", None, h)
    h = dict(header); h["vertices"] -= 1; add("header_vertices_wrong", None, h)
    h = dict(header); h["root"] = max(0, h["root"] - 1) if h["root"] else 1; add("header_root_wrong", None, h)
    h = dict(header); h["format"] = "route-proof-v3"; add("header_format_wrong", None, h)
    h = dict(header); h["input_sha256"] = "0" * 64; add("header_input_sha_wrong", None, h)
    h = dict(header); h["extra"] = 1; add("header_unknown_key", None, h)
    h = dict(header); h["groups"] = float(h["groups"]); add("header_groups_float", None, h)
    # 11 truncated file (plain: drop the root line / cut mid-line; gzip: cut the stream)
    text = "\n".join(lines) + "\n"
    add("truncated_drop_last_line", raw="\n".join(lines[:-1]) + "\n")
    add("truncated_mid_line", raw=text[: len(text) - max(2, len(lines[-1]) // 2)])
    add("truncated_gzip", raw=gzip.compress(text.encode())[:-9], gz=True)
    add("gzip_trailing_garbage", raw=gzip.compress(text.encode()) + b"junk", gz=True)
    # 12 bool / float where an int is required
    if len(nodes) > 1:
        ns = [dump(n) for n in nodes]; ns[1] = ns[1].replace('"id":1,', '"id":true,', 1)
        cases.append(("bool_id", None, None, lines[0] + "\n" + "\n".join(ns) + "\n", False))
    ns = [dump(n) for n in nodes]; k = len(ns) - 1
    ns[k] = ns[k].replace(f'"id":{k},', f'"id":{k}.0,', 1)
    cases.append(("float_id", None, None, lines[0] + "\n" + "\n".join(ns) + "\n", False))
    i = pick(nonstatic)
    if i is not None:
        ns = clone(); g, ch = ns[i]["m"][0]
        t = [dump(n) for n in ns]; t[i] = t[i].replace(f"[{g},{ch}]", f"[{g}.0,{ch}]", 1)
        cases.append(("float_group", None, None, lines[0] + "\n" + "\n".join(t) + "\n", False))
        t = [dump(n) for n in ns]; t[i] = t[i].replace(f"[{g},{ch}]", f"[{g},{'true' if ch == 1 else str(ch) + 'e0'}]", 1)
        cases.append(("bool_or_exp_child", None, None, lines[0] + "\n" + "\n".join(t) + "\n", False))
        t = [dump(n) for n in ns]; t[i] = t[i].replace(f'"id":{i},', f'"id":{i},"r":"{ns[i]["r"]}",', 1)
        cases.append(("duplicate_json_key", None, None, lines[0] + "\n" + "\n".join(t) + "\n", False))
        ns2 = clone(); ns2[i]["x"] = 1; add("unknown_node_key", ns2)
        ns2 = clone(); ns2[i]["k"] = "dynamic"; add("unknown_kind_value", ns2)
    # 13 non-contiguous ids
    if len(nodes) > 1:
        ns = clone()
        for n in ns[1:]:
            n["id"] += 1
        h = dict(header); h["root"] += 1; add("noncontiguous_ids", ns, h)
    # 14 a node re-reached with a different state: point an edge to another node with the same result
    done = False
    for i in rng.sample(nonstatic, len(nonstatic)):
        for slot, (g, ch) in enumerate(nodes[i]["m"]):
            want_r = nodes[ch]["r"]
            alts = [x for x in reached if x < i and x != ch and nodes[x]["r"] == want_r
                    and (state[x][0], state[x][1]) != model.child(info[i][0], info[i][1], g)[:2]]
            if alts:
                ns = clone(); ns[i]["m"][slot][1] = rng.choice(alts); add("redirect_edge_to_other_state", ns)
                done = True
                break
        if done:
            break
    # 14b deterministic re-arrival with a different state: two moves of one L node share a child id.
    # The first move records (or matches) the child's true state; the second derives a different one.
    for i in L_multi:
        (g0, c0), (g1, c1) = nodes[i]["m"][0], nodes[i]["m"][1]
        if model.child(info[i][0], info[i][1], g0)[:2] != model.child(info[i][0], info[i][1], g1)[:2]:
            ns = clone(); ns[i]["m"][1][1] = c0; add("rereached_different_state", ns)
            break
    # 15 root not last: append a trailing static-looking node
    ns = clone(); ns.append({"id": len(ns), "r": "L", "m": []}); add("root_not_last", ns)
    # 16 empty line / empty file
    cases.append(("blank_line", None, None, lines[0] + "\n\n" + "\n".join(lines[1:]) + "\n", False))
    cases.append(("empty_file", None, None, "", False))
    cases.append(("header_only", None, None, lines[0] + "\n", False))

    results = []
    for n, (kind, mutated, hobj, raw, gz) in enumerate(cases):
        path = work / (f"bad_{n}_{kind}.jsonl" + (".gz" if gz else ""))
        if raw is None:
            body = [dump(hobj if hobj is not None else header)] + [dump(x) for x in (mutated if mutated is not None else nodes)]
            raw = "\n".join(body) + "\n"
        path.write_bytes(raw if isinstance(raw, bytes) else raw.encode("utf-8"))
        try:
            verify_v4.verify_v4(dic, posf, path, inp, nwords)
            py = "ACCEPTED"
        except (VerificationError, OSError, EOFError, ValueError) as exc:
            py = "rejected: " + str(exc)[:90]
        r = subprocess.run([cpp, "--dictionary", dic, "--expected-word-count", str(nwords), "--position", posf,
                            "--proof", str(path), "--input", inp], capture_output=True, text=True)
        try:
            c = json.loads(r.stdout)
        except ValueError:
            c = {"verified": None, "error": r.stdout + r.stderr}
        cc = "ACCEPTED" if r.returncode == 0 or c.get("verified") else "rejected: " + str(c.get("error"))[:90]
        results.append({"kind": kind, "python": py, "cpp": cc})
        path.unlink()
    bad = [x for x in results if x["python"] == "ACCEPTED" or x["cpp"] == "ACCEPTED"]
    for x in results:
        print(f'{x["kind"]:34s} py: {x["python"][:70]:72s} cpp: {x["cpp"][:70]}')
    print(json.dumps({"kinds": len(results), "kinds_rejected_by_both": len(results) - len(bad),
                      "accepted": [x["kind"] for x in bad], "ok": not bad}))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
