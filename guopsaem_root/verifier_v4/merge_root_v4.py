#!/usr/bin/env python3
"""Combine route-proof-v4 child certificates into one route-proof-v4 certificate for ROOT.

usage: merge_root_v4.py DICT WORD_COUNT ROOT_POSITION.json OUT.jsonl[.gz] CHILD_POS.json:CHILD_PROOF ...
       [--input ROOT_INPUT.txt]

Each child is given as POSITION:PROOF, where POSITION is ROOT's position plus one more
history word and PROOF is a v4 certificate for that position.  v4 nodes carry no state, so
a child certificate can be reused under ROOT only if the state the verifier will derive for
it there, model.child(ROOT canonical state, group), is byte-identical to the normalized child
position its own certificate starts from.  This is checked for every child used (otherwise
the merge stops); then every node of the child certificate replays to exactly the same state
as in its own verification, so the child certificates are concatenated with their ids
shifted.  With --dedup the child certificates are replayed with ModelV3 (as the verifier does)
and nodes with the same (result, vertex, exact state bytes) are merged, then nodes no longer
reachable from the new root are dropped; this is exact (full state, not a digest) but needs
the replay time and memory of a Python verification.
Children whose state is static under ROOT need no certificate: a leaf is written for them.

If some child is L (for its player to move) ROOT is W and only that child is used; otherwise
every legal group of ROOT's canonical state needs a W child and ROOT is L.  Nothing is trusted:
the result must still be checked with verify_v4.py / verify_v4 (C++) against ROOT_POSITION.
"""
import argparse
import gzip
import json
import sys
import zlib
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "verifier_v3"))
from verify_v3 import ModelV3  # noqa: E402


def lines_of(path):
    with open(path, "rb") as f:
        gz = f.read(2) == b"\x1f\x8b"
    with (gzip.open(path, "rb") if gz else open(path, "rb")) as f:
        for line in f:
            yield line.rstrip(b"\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dictionary")
    ap.add_argument("word_count", type=int)
    ap.add_argument("root_position")
    ap.add_argument("out")
    ap.add_argument("children", nargs="+", help="CHILD_POSITION.json:CHILD_PROOF")
    ap.add_argument("--input", help="ROOT's numeric solver input; its SHA-256 is written to the header")
    ap.add_argument("--dedup", action="store_true", help="merge nodes with identical replayed states (exact; slow)")
    a = ap.parse_args()
    m = ModelV3(Path(a.dictionary).read_bytes(), a.word_count)
    root_pos = json.loads(Path(a.root_position).read_text(encoding="utf-8"))
    cur, counts, used = m.position(root_pos)
    root, static = m.normalize(cur, counts)
    header = {"format": "route-proof-v4", "groups": len(m.edges), "vertices": len(m.keys)}
    if a.input:
        header["input_sha256"] = m.check_numeric_input(a.input, cur, counts)
    out = gzip.open(a.out, "wb", compresslevel=6) if a.out.endswith(".gz") else open(a.out, "wb")
    if static != -1:
        header["root"] = 0
        out.write((json.dumps(header) + "\n").encode())
        out.write((json.dumps({"id": 0, "r": "W" if static else "L", "m": []}, separators=(",", ":")) + "\n").encode())
        out.close()
        print(json.dumps({"root_result": "W" if static else "L", "nodes": 1, "static_root": True}))
        return
    legal = [g for g in m.available[cur] if root[g]]
    under_root = {g: m.child(cur, root, g) for g in legal}       # (vertex, counts, static) as the verifier derives it
    certs = {}                                                   # group -> (proof path, claimed result)
    for spec in a.children:
        pos_path, _, proof_path = spec.partition(":")
        pos = json.loads(Path(pos_path).read_text(encoding="utf-8"))
        require_prefix = (pos.get("initial_syllable") == root_pos.get("initial_syllable")
                          and pos.get("initial_used_words", []) == root_pos.get("initial_used_words", [])
                          and isinstance(pos.get("history"), list)
                          and pos["history"][:-1] == root_pos["history"] and len(pos["history"]) == len(root_pos["history"]) + 1)
        if not require_prefix:
            sys.exit(f"{pos_path}: not ROOT's position plus one history word")
        word = pos["history"][-1]
        g = m.word_group(word)
        if g not in under_root:
            sys.exit(f"{pos_path}: {word} is not a legal move of ROOT's canonical state")
        ccur, ccounts, _ = m.position(pos)
        own, own_static = m.normalize(ccur, ccounts)
        tv, tc, ts = under_root[g]
        if (ccur, own) != (tv, tc):
            sys.exit(f"{pos_path}: the child's normalized position differs from model.child(ROOT, group {g}); "
                     "its certificate would replay to different states under ROOT")
        it = lines_of(proof_path)
        head = json.loads(next(it))
        if head.get("format") != "route-proof-v4" or head.get("groups") != len(m.edges) or head.get("vertices") != len(m.keys):
            sys.exit(f"{proof_path}: not a route-proof-v4 certificate for this dictionary")
        last = None
        for last in it:
            pass
        claimed = json.loads(last)["r"]
        if g in certs and certs[g][1] != claimed:
            sys.exit(f"group {g}: two child certificates disagree")
        certs.setdefault(g, (proof_path, claimed, head["root"]))
    # static children need no certificate
    for g, (tv, tc, ts) in under_root.items():
        if ts != -1 and g not in certs:
            certs[g] = (None, "W" if ts else "L", 0)
    winning = [g for g in legal if g in certs and certs[g][1] == "L"]
    if winning:
        g = min(winning, key=lambda x: (certs[x][0] is not None, certs[x][2]))
        use = [g]
        result = "W"
    else:
        missing = [g for g in legal if g not in certs]
        if missing:
            sys.exit(f"cannot show L: no certificate for groups {missing}")
        use = legal
        result = "L"
    if a.dedup:
        return write_dedup(m, a, header, certs, under_root, use, result, out)
    next_id = 0
    root_moves = []
    tmp_path = a.out + ".body.tmp"
    with gzip.open(tmp_path, "wb", compresslevel=1) as body:
        for g in use:
            proof_path, claimed, _ = certs[g]
            if proof_path is None:
                body.write((json.dumps({"id": next_id, "r": claimed, "m": []}, separators=(",", ":")) + "\n").encode())
                root_moves.append([g, next_id])
                next_id += 1
                continue
            it = lines_of(proof_path)
            next(it)
            base = next_id
            count = 0
            for raw in it:
                node = json.loads(raw)
                if node["id"] != count:
                    sys.exit(f"{proof_path}: ids are not contiguous")
                node["id"] += base
                node["m"] = [[mg, mc + base] for mg, mc in node["m"]]
                body.write((json.dumps(node, separators=(",", ":")) + "\n").encode())
                count += 1
            next_id = base + count
            root_moves.append([g, next_id - 1])     # a certificate's root is its last node
    header["root"] = next_id
    out.write((json.dumps(header, separators=(",", ":")) + "\n").encode())
    with gzip.open(tmp_path, "rb") as body:
        for chunk in iter(lambda: body.read(1 << 20), b""):
            out.write(chunk)
    out.write((json.dumps({"id": next_id, "r": result, "m": root_moves}, separators=(",", ":")) + "\n").encode())
    out.close()
    Path(tmp_path).unlink()
    print(json.dumps({"root_result": result, "nodes": next_id + 1, "children_used": len(use),
                      "children_static": sum(1 for g in use if certs[g][0] is None)}))


def replay_keys(m, nodes, vertex, counts):
    """Exact state key (result, vertex, zlib(counts)) of every node reached from the last node."""
    root = len(nodes) - 1
    packed = {root: (vertex, zlib.compress(counts, 1))}
    keys = {}
    stack = [root]
    while stack:
        i = stack.pop()
        v, z = packed[i]
        keys[i] = (nodes[i]["r"], v, z)
        c = zlib.decompress(z)
        for g, ch in nodes[i]["m"]:
            if ch not in packed:
                tv, tc, _ = m.child(v, c, g)
                packed[ch] = (tv, zlib.compress(tc, 1))
                stack.append(ch)
    return keys


def write_dedup(m, a, header, certs, under_root, use, result, out):
    merged, seen, root_moves = [], {}, []
    for g in use:
        proof_path, claimed, _ = certs[g]
        tv, tc, _ = under_root[g]
        if proof_path is None:
            key = (claimed, tv, zlib.compress(tc, 1))
            if key not in seen:
                seen[key] = len(merged)
                merged.append({"r": claimed, "m": []})
            root_moves.append([g, seen[key]])
            continue
        it = lines_of(proof_path)
        next(it)
        nodes = [json.loads(raw) for raw in it]
        if any(n["id"] != i for i, n in enumerate(nodes)):
            sys.exit(f"{proof_path}: ids are not contiguous")
        keys = replay_keys(m, nodes, tv, tc)
        local = {}
        for i, n in enumerate(nodes):
            key = keys.get(i)
            if key is not None and key in seen:
                local[i] = seen[key]
                continue
            local[i] = len(merged)
            merged.append({"r": n["r"], "m": [[mg, local[mc]] for mg, mc in n["m"]]})
            if key is not None:
                seen[key] = local[i]
        root_moves.append([g, local[len(nodes) - 1]])
    merged.append({"r": result, "m": root_moves})
    # keep only nodes reachable from the new root, renumbered in the same (children-first) order
    reach = bytearray(len(merged))
    reach[-1] = 1
    for i in range(len(merged) - 1, -1, -1):
        if reach[i]:
            for _, ch in merged[i]["m"]:
                reach[ch] = 1
    new = {}
    for i in range(len(merged)):
        if reach[i]:
            new[i] = len(new)
    header["root"] = len(new) - 1
    out.write((json.dumps(header, separators=(",", ":")) + "\n").encode())
    for i, n in enumerate(merged):
        if reach[i]:
            line = {"id": new[i], "r": n["r"], "m": [[mg, new[mc]] for mg, mc in n["m"]]}
            out.write((json.dumps(line, separators=(",", ":")) + "\n").encode())
    out.close()
    print(json.dumps({"root_result": result, "nodes": len(new), "children_used": len(use),
                      "children_static": sum(1 for g in use if certs[g][0] is None), "dedup": True,
                      "nodes_before_dedup": sum(1 for _ in merged)}))


if __name__ == "__main__":
    main()
