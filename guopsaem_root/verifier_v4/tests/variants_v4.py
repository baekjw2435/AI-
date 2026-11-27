#!/usr/bin/env python3
"""Valid but unusual spellings of a v4 certificate must be ACCEPTED by verify_v4.py and
verify_v4 (C++) with identical results (exercises both JSON slow paths):
spaces and shuffled key order, \\u escapes in strings, CRLF line ends, no final newline,
"k":"static" on truly static leaves, two concatenated gzip members, a header with
input_sha256, -0 as an id 0, and unreached extra nodes (reported, not rejected).
Usage: variants_v4.py VERIFY_CPP DICT WORD_COUNT POS.json PROOF INPUT.txt WORKDIR"""
import gzip
import hashlib
import json
import random
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2] / "verifier_v3"))
sys.path.insert(0, str(HERE.parents[1]))
from verify_v3 import ModelV3  # noqa: E402
from verify_v4 import verify_v4  # noqa: E402

cpp, dic, nwords, posf, proof, inp, work = sys.argv[1:8]
nwords = int(nwords)
work = Path(work)
work.mkdir(parents=True, exist_ok=True)
rng = random.Random(3)
with open(proof, "rb") as f:
    gz = f.read(2) == b"\x1f\x8b"
text = (gzip.open(proof, "rb") if gz else open(proof, "rb")).read().decode()
lines = text.splitlines()
header, nodes = json.loads(lines[0]), [json.loads(x) for x in lines[1:]]
model = ModelV3(Path(dic).read_bytes(), nwords)

# static leaves (by replay) for the "k":"static" variant
cur, counts, _ = model.position(json.loads(Path(posf).read_text(encoding="utf-8")))
state = {len(nodes) - 1: (cur, model.normalize(cur, counts)[0])}
stack, static_ids = [len(nodes) - 1], []
while stack:
    i = stack.pop()
    v, c = state[i]
    if model.normalize(v, c)[1] != -1:
        static_ids.append(i)
    for g, ch in nodes[i]["m"]:
        if ch not in state:
            tv, tc, _ = model.child(v, c, g)
            state[ch] = (tv, tc)
            stack.append(ch)


def shuffled(n):
    keys = list(n)
    rng.shuffle(keys)
    return json.dumps({k: n[k] for k in keys}, separators=(" , ", " : "))


def escaped(n):
    s = json.dumps(n, separators=(",", ":"))
    return s.replace('"r":"W"', '"\\u0072":"\\u0057"').replace('"r":"L"', '"r":"\\u004c"')


variants = {}
variants["spaces_shuffled_keys"] = "\n".join([" " + json.dumps(header) + "\t"] + [shuffled(n) for n in nodes]) + "\n"
variants["unicode_escapes"] = "\n".join([lines[0]] + [escaped(n) for n in nodes]) + "\n"
variants["crlf"] = "\r\n".join(lines) + "\r\n"
variants["no_final_newline"] = "\n".join(lines)
ks = [dict(n) for n in nodes]
for i in static_ids:
    ks[i]["k"] = "static"
variants["k_static_on_static_leaves"] = "\n".join([lines[0]] + [json.dumps(n, separators=(",", ":")) for n in ks]) + "\n"
h = dict(header)
h["input_sha256"] = hashlib.sha256(Path(inp).read_bytes()).hexdigest()
variants["header_input_sha256"] = "\n".join([json.dumps(h)] + lines[1:]) + "\n"
variants["minus_zero_id"] = "\n".join([lines[0], lines[1].replace('"id":0', '"id":-0', 1)] + lines[2:]) + "\n"
# unreached extra nodes: insert two leaves before the root, shift the root
extra = [dict(n) for n in nodes[:-1]]
extra.append({"id": len(extra), "r": "W", "m": []})
extra.append({"id": len(extra), "r": "L", "m": [[0, 0]] if len(model.edges) else []})
root = dict(nodes[-1], id=len(extra))
extra.append(root)
h = dict(header, root=root["id"])
variants["unreached_extra_nodes"] = "\n".join([json.dumps(h)] + [json.dumps(n, separators=(",", ":")) for n in extra]) + "\n"

ok = True
reference = None
for name, body in variants.items():
    path = work / f"var_{name}.jsonl"
    path.write_bytes(body.encode())
    paths = [path]
    if name == "spaces_shuffled_keys":
        half = len(body) // 2
        gzpath = work / "var_two_gzip_members.jsonl.gz"
        gzpath.write_bytes(gzip.compress(body[:half].encode()) + gzip.compress(body[half:].encode()))
        paths.append(gzpath)
    for p in paths:
        label = name if p is path else "two_gzip_members"
        try:
            v = verify_v4(dic, posf, p, inp, nwords)
        except Exception as exc:  # noqa: BLE001
            v = {"verified": False, "error": str(exc)}
        r = subprocess.run([cpp, "--dictionary", dic, "--expected-word-count", str(nwords), "--position", posf,
                            "--proof", str(p), "--input", inp], capture_output=True, text=True)
        c = json.loads(r.stdout)
        fields = ["verified", "result_for_player_to_move", "checked_certificate_states", "checked_certificate_moves",
                  "checked_static_leaves", "certificate_nodes", "unreached_nodes", "proof_sha256"]
        same = all(v.get(k) == c.get(k) for k in fields)
        good = v.get("verified") is True and c.get("verified") is True and same
        if reference is None:
            reference = v.get("result_for_player_to_move")
        good = good and v.get("result_for_player_to_move") == reference
        ok &= good
        print(f"{label:28s} py={v.get('verified')} cpp={c.get('verified')} same_fields={same} "
              f"states={v.get('checked_certificate_states')} unreached={v.get('unreached_nodes')} "
              f"{'' if good else (v.get('error'), c.get('error'))}")
        p.unlink()
print(json.dumps({"variants": len(variants) + 1, "ok": ok}))
sys.exit(0 if ok else 1)
