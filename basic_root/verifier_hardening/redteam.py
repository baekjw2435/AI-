#!/usr/bin/env python3
"""Red-team harness: mutate real certificates/positions/dictionaries and run
verify_v2 (unmodified, imported from route-verifier-v2) and verify_fast.

Run with plain python3 (verify_v2 imports verify.py from its own folder).
Output: rt/results.json and a table on stdout.
"""
import copy, gzip, hashlib, json, os, shutil, subprocess, sys, time
from pathlib import Path

S = Path("/tmp/claude-0/-home-user-AI-/80ff9426-9f7b-5815-97c0-938f621a9f93/scratchpad")
V2 = S / "verifier/route-verifier-v2"
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(V2))
sys.path.insert(0, str(HERE))
import verify as v1mod                      # noqa: E402
import verify_v2 as v2mod                   # noqa: E402
import verify_fast as vf                    # noqa: E402
import importlib.util                       # noqa: E402


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# patched copies (patched/verify.py + patched/verify_v2.py) loaded under other names
_orig_verify = sys.modules["verify"]
pv1 = _load("verify", HERE / "patched/verify.py")
sys.modules["verify"] = pv1
pv2 = _load("verify_v2_patched", HERE / "patched/verify_v2.py")
sys.modules["verify"] = _orig_verify

DICT = V2 / "words.txt"
RT = HERE / "rt"
shutil.rmtree(RT, ignore_errors=True)
RT.mkdir()
MODEL = vf.Model(DICT.read_bytes())

base_lines = (HERE / "proofs/proof_1.jsonl").read_text().splitlines()
HEADER = json.loads(base_lines[0])
NODES = [json.loads(l) for l in base_lines[1:]]
POS1 = json.loads((S / "bench/pos_1.json").read_text())
POS4 = json.loads((S / "bench/pos_4.json").read_text())
INPUT1 = S / "bench/v2_1.txt"


def classify():
    kinds = {}
    for n in NODES:
        c = bytes.fromhex(n["c"])
        _, st = MODEL.normalize(n["v"], c)
        kinds.setdefault(("S" if st != -1 else "N") + n["r"] + str(min(len(n["m"]), 2)), []).append(n["id"])
    return kinds


KINDS = classify()
ROOT = NODES[-1]["id"]
SW = KINDS["SW0"][0]; SL = KINDS["SL0"][0]
NW = next(i for i in KINDS["NW1"] if i > 5)
NL2 = KINDS["NL2"][0]
outcome = {n["id"]: n["r"] for n in NODES}


def legal_groups(node):
    c = bytes.fromhex(node["c"]); v = node["v"]
    return [g for g in range(MODEL.lo[v], MODEL.hi[v]) if c[g]]


def dump(lines):
    return ("\n".join(l if isinstance(l, str) else json.dumps(l, separators=(",", ":"), ensure_ascii=False)
                      for l in lines) + "\n").encode()


def proof_bytes(nodes=None, header=None):
    return dump([header or HEADER] + (nodes if nodes is not None else NODES))


def mutate(fn):
    nodes = copy.deepcopy(NODES)
    fn(nodes)
    return proof_bytes(nodes)


CASES = []


def case(name, expect, proof, position=None, dictionary=None, input_path=INPUT1,
         word_count=817, note=""):
    """expect: 'reject' = must be rejected; 'accept' = equivalent encoding / true verdict;
    'gap' = verify_v2 accepts but the report can mislead (hardening target)."""
    CASES.append(dict(name=name, expect=expect, proof=proof, position=position or POS1,
                      dictionary=dictionary, input=input_path, word_count=word_count, note=note))


# ---- certificate structure ---------------------------------------------------
case("valid_baseline", "accept", proof_bytes())
case("root_flip", "reject", mutate(lambda n: n[-1].update(r="L")))
case("static_W_leaf_flip", "reject", mutate(lambda n: n[SW].update(r="L")))
case("static_L_leaf_flip", "reject", mutate(lambda n: n[SL].update(r="W")))
case("static_leaf_with_move", "reject",
     mutate(lambda n: n[SL].update(m=[[legal_groups(n[SL])[0], 0]]) if legal_groups(n[SL]) else None))
case("nonstatic_marked_k_static", "reject", mutate(lambda n: n[NW].update(k="static")))
case("static_leaf_marked_k_static", "accept", mutate(lambda n: n[SW].update(k="static")),
     note="descriptive label on a real static node is allowed by the interface")
case("W_two_moves", "reject", mutate(lambda n: n[NW]["m"].append([g for g in legal_groups(n[NW]) if g != n[NW]["m"][0][0]][0:1] + [0])
                                     if len(legal_groups(n[NW])) > 1 else n[NW]["m"].append(n[NW]["m"][0])))
case("W_no_move", "reject", mutate(lambda n: n[NW].update(m=[])))
case("W_wrong_group_same_child", "reject",
     mutate(lambda n: n[NW]["m"][0].__setitem__(0, [g for g in legal_groups(n[NW]) if g != n[NW]["m"][0][0]][0])
            if len(legal_groups(n[NW])) > 1 else None))
case("L_omit_move", "reject", mutate(lambda n: n[NL2]["m"].pop()))
case("L_duplicate_move", "reject", mutate(lambda n: n[NL2]["m"].append(n[NL2]["m"][0])))
case("L_as_leaf", "reject", mutate(lambda n: n[NL2].update(m=[])))


def redirect_same_outcome(n):
    g, c = n[NL2]["m"][0]
    other = next(i for i in range(NL2) if outcome[i] == outcome[c] and n[i]["c"] != n[c]["c"])
    n[NL2]["m"][0][1] = other


case("child_redirect_same_outcome", "reject", mutate(redirect_same_outcome))
case("child_self", "reject", mutate(lambda n: n[NW]["m"][0].__setitem__(1, NW)))
case("child_forward", "reject", mutate(lambda n: n[NW]["m"][0].__setitem__(1, NW + 1)))
case("child_negative_-1", "reject", mutate(lambda n: n[NW]["m"][0].__setitem__(1, -1)),
     note="-1 would index the last stored node in Python")
case("child_bool", "reject", mutate(lambda n: n[2]["m"][0].__setitem__(1, True)))
case("child_float", "reject", mutate(lambda n: n[NW]["m"][0].__setitem__(1, float(n[NW]["m"][0][1]))))
case("child_huge", "reject", mutate(lambda n: n[NW]["m"][0].__setitem__(1, 10 ** 30)))
case("child_str", "reject", mutate(lambda n: n[NW]["m"][0].__setitem__(1, str(n[NW]["m"][0][1]))))
case("group_bool", "reject", mutate(lambda n: n[NW]["m"][0].__setitem__(0, True)))
case("group_float", "reject", mutate(lambda n: n[NW]["m"][0].__setitem__(0, float(n[NW]["m"][0][0]))))
case("move_3_elements", "reject", mutate(lambda n: n[NW]["m"][0].append(0)))
case("move_as_object", "reject",
     mutate(lambda n: n[NW].update(m=[{"g": n[NW]["m"][0][0], "c": n[NW]["m"][0][1]}])))
case("moves_as_empty_object_on_leaf", "reject", mutate(lambda n: n[SL].update(m={})))
case("id_bool", "reject", mutate(lambda n: n[1].update(id=True)))
case("id_float", "reject", mutate(lambda n: n[3].update(id=3.0)))
case("id_gap", "reject", mutate(lambda n: [x.update(id=x["id"] + 1) for x in n[10:]]))
case("id_repeat", "reject", mutate(lambda n: n[11].update(id=10)))
case("swap_two_nodes", "reject", mutate(lambda n: n.__setitem__(slice(4, 6), [n[5], n[4]])))
case("v_changed", "reject", mutate(lambda n: n[SL].update(v=(n[SL]["v"] + 1) % len(MODEL.syllables))))
case("v_bool", "reject", mutate(lambda n: n[1].update(v=bool(n[1]["v"])) if n[1]["v"] in (0, 1) else n[1].update(v=True)))


def count_edit(node_id, edits):
    def fn(n):
        c = bytearray.fromhex(n[node_id]["c"])
        for g, delta in edits(n[node_id], c):
            c[g] = (c[g] + delta) % 256
        n[node_id]["c"] = c.hex()
    return fn


def over_multiplicity(node, c):
    # add a parallel copy to a positive core edge with dictionary multiplicity 1
    for g in legal_groups(node):
        if MODEL.full_counts[g] == 1 and MODEL.dst[g] != MODEL.src[g]:
            return [(g, 1)]
    return []


def readd_pair(node, c):
    for a, b in MODEL.pairs:
        if c[a] == 0 and c[b] == 0 and MODEL.src[a] == node["v"]:
            return [(a, 1), (b, 1)]
    for a, b in MODEL.pairs:
        if c[a] == 0 and c[b] == 0:
            return [(a, 1), (b, 1)]
    return []


def unreachable_edge(node, c):
    _, st = MODEL.normalize(node["v"], bytes(c))
    reach = {node["v"]}
    q = [node["v"]]
    for s in q:
        for g in range(MODEL.lo[s], MODEL.hi[s]):
            if c[g] and MODEL.dst[g] not in reach:
                reach.add(MODEL.dst[g]); q.append(MODEL.dst[g])
    for g in range(MODEL.G):
        if MODEL.src[g] not in reach and c[g] == 0:
            return [(g, 1)]
    return []


def untrimmed_child(nodes):
    """Replace a non-static child's counts by the parent's counts minus the move, i.e. the
    state before 'drop edges into/out of classified vertices' (pairs/reachability are
    no-ops there). The result is a real game state with the same value but is not canonical."""
    for parent in nodes:
        for g, cid in parent["m"]:
            child = nodes[cid]
            pc = bytearray.fromhex(parent["c"]); pc[g] -= 1
            target = MODEL.dst[g]
            canon, st = MODEL.normalize(target, bytes(pc))
            if st != -1 or canon.hex() != child["c"]:
                continue
            paired = V1_MODEL.reduce(target, bytes(pc))
            if paired != canon:
                child["c"] = paired.hex()
                return
    raise SystemExit("no trimmed child found")


V1_MODEL = v1mod.IndependentModel(DICT.read_bytes())


case("counts_above_multiplicity", "reject", mutate(count_edit(NL2, over_multiplicity)))
case("noncanonical_reciprocal_pair", "reject", mutate(count_edit(NL2, readd_pair)))
case("noncanonical_unreachable_edge", "reject", mutate(count_edit(NL2, unreachable_edge)))
case("noncanonical_untrimmed_core", "reject", mutate(untrimmed_child),
     note="child kept edges into/out of statically classified vertices")
case("count_255_wrap", "reject", mutate(count_edit(SL, lambda node, c: [(0, 255 - c[0])])))
case("hex_uppercase", "accept", mutate(lambda n: [x.update(c=x["c"].upper()) for x in n]))
case("hex_with_space", "reject", mutate(lambda n: n[5].update(c=" " + n[5]["c"][1:])))
case("hex_non_ascii_digit", "reject", mutate(lambda n: n[5].update(c="０" + n[5]["c"][1:])))
case("hex_too_long", "reject", mutate(lambda n: n[5].update(c=n[5]["c"] + "00")))
case("r_lowercase", "reject", mutate(lambda n: n[SW].update(r="w")))
case("r_draw", "reject", mutate(lambda n: n[SW].update(r="D")))
case("r_bool", "reject", mutate(lambda n: n[SW].update(r=True)))
case("unknown_node_field", "accept", mutate(lambda n: n[5].update(note="ignored")))

raw_nodes = base_lines[1:]


def raw_edit(index, old, new):
    lines = list(base_lines)
    assert old in lines[index], (old, lines[index][:80])
    lines[index] = lines[index].replace(old, new, 1)
    return ("\n".join(lines) + "\n").encode()


line_root = len(base_lines) - 1
case("dup_key_r_in_root", "reject", raw_edit(line_root, '"r":"W"', '"r":"L","r":"W"'))
case("dup_key_header", "reject", raw_edit(0, '"root":', '"root":0,"root":'))
case("r_unicode_escape", "accept", raw_edit(line_root, '"r":"W"', '"r":"\\u0057"'))
case("v_NaN", "reject", raw_edit(1, '"v":', '"v":NaN,"x":'))
case("id_Infinity", "reject", raw_edit(1, '"id":0', '"id":Infinity'))
case("id_minus_zero", "accept", raw_edit(1, '"id":0', '"id":-0'), note="-0 parses to int 0")
case("id_5000_digits", "reject", raw_edit(1, '"id":0', '"id":' + "1" * 5000))
case("deep_nesting_in_m", "reject", raw_edit(1, '"m":[]', '"m":' + "[" * 100000 + "]" * 100000))
case("blank_line", "reject", proof_bytes().replace(b"\n", b"\n\n", 3))
case("crlf_line_endings", "accept", proof_bytes().replace(b"\n", b"\r\n"))
case("lone_cr_inside_line", "reject", raw_edit(3, '"r":', '\r"r":'))
case("utf8_bom", "reject", b"\xef\xbb\xbf" + proof_bytes())
case("no_final_newline", "accept", proof_bytes().rstrip(b"\n"))
case("extra_node_after_root", "reject", dump([HEADER] + NODES + [dict(NODES[0], id=len(NODES))]))
case("header_root_not_last", "reject", proof_bytes(header=dict(HEADER, root=ROOT - 1)))
case("header_root_bool", "reject", proof_bytes(header=dict(HEADER, root=True)))
case("header_root_float", "reject", proof_bytes(header=dict(HEADER, root=float(ROOT))))
case("header_groups_wrong", "reject", proof_bytes(header=dict(HEADER, groups=HEADER["groups"] + 1)))
case("header_vertices_wrong", "reject", proof_bytes(header=dict(HEADER, vertices=HEADER["vertices"] - 1)))
case("header_format_v1", "reject", proof_bytes(header=dict(HEADER, format="route-proof-v1")))
case("truncated_no_root", "reject", dump([HEADER] + NODES[:-1]))
case("empty_file", "reject", b"")
case("header_only", "reject", dump([HEADER]))
input_sha = hashlib.sha256(INPUT1.read_bytes()).hexdigest()
case("input_sha256_without_input", "reject", proof_bytes(header=dict(HEADER, input_sha256=input_sha)),
     input_path=None)
case("input_sha256_wrong", "reject", proof_bytes(header=dict(HEADER, input_sha256="0" * 64)))
case("input_sha256_right", "accept", proof_bytes(header=dict(HEADER, input_sha256=input_sha)))
case("numeric_input_of_other_position", "reject", proof_bytes(), input_path=S / "bench/v2_4.txt")
gz = gzip.compress(proof_bytes())
case("gzip_valid", "accept", gz)
half = len(proof_bytes()) // 2
case("gzip_two_members", "accept", gzip.compress(proof_bytes()[:half]) + gzip.compress(proof_bytes()[half:]))
case("gzip_trailing_garbage", "reject", gz + b"GARBAGE")
case("gzip_trailing_zeros", "accept", gz + b"\0" * 64, note="gzip module ignores zero padding")
case("gzip_truncated", "reject", gz[:-20])
case("gzip_root_flip", "reject", gzip.compress(mutate(lambda n: n[-1].update(r="L"))))
case("gzip_inside_gzip", "reject", gzip.compress(gz))
case("proof_for_other_history", "reject", proof_bytes(), position=POS4)

# splice: root of another proof
other = [json.loads(l) for l in (HERE / "proofs/proof_4.jsonl").read_text().splitlines()]
case("foreign_certificate_same_dictionary", "reject", dump(other))

# ---- positions -------------------------------------------------------------
case("history_extra_word", "reject", proof_bytes(), position=dict(POS1, history=POS1["history"] + ["득점"]))
case("history_reordered", "reject", proof_bytes(), position=dict(POS1, history=POS1["history"][::-1]))
case("history_as_string", "reject", proof_bytes(), position=dict(POS1, history="역습"))
case("history_int_word", "reject", proof_bytes(), position=dict(POS1, history=[1]))
case("history_reuses_initial_used", "reject", proof_bytes(),
     position=dict(POS1, initial_used_words=["역습"]))
case("initial_syllable_two_chars", "reject", proof_bytes(), position=dict(POS1, initial_syllable="역습"))
case("initial_syllable_latin", "reject", proof_bytes(), position=dict(POS1, initial_syllable="A"))
case("initial_syllable_rieul_form", "accept", proof_bytes(), position=dict(POS1, initial_syllable="력"),
     note="력 is normalised to 역 by dueum")
case("position_duplicate_key", "reject", proof_bytes(),
     position=b'{"initial_syllable":"\xec\x97\xad","history":[],"history":["\xec\x97\xad\xec\x8a\xb5","\xec\x8a\xb5\xeb\x93\x9d"]}')
case("position_unknown_key", "gap", proof_bytes(), position=dict(POS1, comment="ignored"))
case("same_state_via_initial_used_words", "gap", proof_bytes(),
     position={"initial_syllable": "득", "history": [], "initial_used_words": ["역습", "습득"]},
     note="same counts and vertex; report says history [] at 득")


def single_static_certificate(model, current, counts):
    canon, st = model.normalize(current, counts)
    assert st != -1
    return dump([{"format": "route-proof-v2", "groups": model.G, "vertices": model.V, "root": 0},
                 {"id": 0, "v": current, "c": canon.hex(), "r": "W" if st else "L", "m": []}]), st


# yeokpung with every 풍-word removed in advance -> mover at 풍 has no word (static L)
pung = [w for w in MODEL.words if w[0] == "풍"]
yp = {"initial_syllable": "역", "history": ["역풍"], "initial_used_words": pung}
cur, cnt, _ = MODEL.position(yp)
yp_proof, _ = single_static_certificate(MODEL, cur, cnt)
case("yeokpung_initial_used_abuse", "gap", yp_proof, position=yp, input_path=None,
     note="verified:true, history ['역풍'], result L — only initial_used_words reveals the edit")

smoke = json.loads((V2 / "examples/smoke/position.json").read_text())
smoke_proof = (V2 / "examples/smoke/proof.jsonl").read_bytes()
case("smoke_valid", "accept", smoke_proof, position=smoke, input_path=V2 / "examples/smoke/input.txt")
for key, bad in (("dictionary_sha256", "0" * 64), ("current_syllable", "역"),
                 ("legal_words", ["푼돈"]), ("remaining_words", 1), ("next_player", "B")):
    case(f"smoke_false_{key}", "gap", smoke_proof, position=dict(smoke, **{key: bad}),
         input_path=V2 / "examples/smoke/input.txt",
         note="informational key is never checked by verify_v2")

# ---- dictionaries ----------------------------------------------------------
words = DICT.read_text(encoding="utf-8").split()
swapped = [("습자득" if w == "습득" else w) for w in words]
(RT / "dict_same_model.txt").write_text("\n".join(swapped) + "\n", encoding="utf-8")
case("dictionary_renamed_word_same_model", "gap", proof_bytes(),
     position=dict(POS1, history=["역습", "습자득"]), dictionary=RT / "dict_same_model.txt",
     note="different dictionary bytes, same graph; accepted without a pin")
fillers = iter(["갸갸", "갸걀", "갸걈", "갸걉", "갸걋", "갸걍", "갸걑", "갸걔", "갸걘"])
game_changed = [next(fillers) if (w[0] == "풍" and w != "풍력") else w for w in words]
game_changed = [("갸걥" if w == "풍력" else w) for w in game_changed]
(RT / "dict_game_changed.txt").write_text("\n".join(game_changed) + "\n", encoding="utf-8")
alt = vf.Model((RT / "dict_game_changed.txt").read_bytes())
cur, cnt, _ = alt.position({"initial_syllable": "역", "history": ["역풍"]})
alt_proof, _ = single_static_certificate(alt, cur, cnt)
case("dictionary_game_changed_817_words", "gap", alt_proof,
     position={"initial_syllable": "역", "history": ["역풍"]}, dictionary=RT / "dict_game_changed.txt",
     input_path=None, note="all 풍 words replaced by dummies; yeokpung 'proved' L; only dictionary_sha256 differs")
(RT / "dict_bom.txt").write_bytes(b"\xef\xbb\xbf" + DICT.read_bytes())
case("dictionary_with_bom", "gap", proof_bytes(), dictionary=RT / "dict_bom.txt",
     note="same words; hardened pin is on bytes")

# dueum toy repro: 가레 -> (legacy: 네) ; 네가.  Under 표준두음법칙 레 is unchanged.
(RT / "dict_dueum.txt").write_text("가레 네가\n", encoding="utf-8")
legacy_model = v1mod.IndependentModel((RT / "dict_dueum.txt").read_bytes(), 0)
lm = v2mod.IndependentModelV2((RT / "dict_dueum.txt").read_bytes(), 0)
toy_pos = {"initial_syllable": "가", "history": []}
cur, cnt, _ = lm.position(toy_pos)


def emit_certificate(model, current, counts):
    nodes, memo = [], {}

    def emit(current, counts):
        counts, static = model.normalize(current, counts)
        key = (current, counts)
        if key in memo:
            return memo[key]
        moves = []
        if static == -1:
            win = False
            for g in model.outgoing[current]:
                if counts[g]:
                    cv, cc, _ = model.child_v2(current, counts, g)
                    cid, cres = emit(cv, cc)
                    moves.append([g, cid])
                    if not cres:
                        win, moves = True, [moves[-1]]
                        break
        else:
            win = bool(static)
        nodes.append({"id": len(nodes), "v": current, "c": counts.hex(), "r": "W" if win else "L", "m": moves})
        memo[key] = (len(nodes) - 1, win)
        return memo[key]

    root, _ = emit(current, counts)
    return dump([{"format": "route-proof-v2", "groups": len(model.edges),
                  "vertices": len(model.syllables), "root": root}] + nodes)


case("dueum_legacy_false_verdict", "gap", emit_certificate(lm, cur, cnt), position=toy_pos,
     dictionary=RT / "dict_dueum.txt", input_path=None, word_count=0,
     note="legacy dueum maps 레->네: verify_v2 certifies L; raw game under standard rule is W")


# ---- run -------------------------------------------------------------------
def run_v2(c, files):
    try:
        r = v2mod.verify_v2(files["dict"], files["pos"], files["proof"], files["input"], c["word_count"])
        return "ACCEPT:" + r["result_for_player_to_move"], r
    except (v1mod.VerificationError, OSError, EOFError, UnicodeError) as exc:
        return "reject", str(exc)[:90]
    except Exception as exc:  # the CLI would exit 1 with a traceback
        return "CRASH:" + type(exc).__name__, str(exc)[:90]


def run_fast(c, files, **kw):
    try:
        r = vf.verify_fast(files["dict"], files["pos"], files["proof"], files["input"], c["word_count"], **kw)
        return "ACCEPT:" + r["result_for_player_to_move"], r
    except (vf.VerificationError, OSError, EOFError, UnicodeError) as exc:
        return "reject", str(exc)[:90]
    except Exception as exc:
        return "CRASH:" + type(exc).__name__, str(exc)[:90]


def run_patched(c, files, pin):
    try:
        r = pv2.verify_v2(files["dict"], files["pos"], files["proof"], files["input"], c["word_count"],
                          pin or None, False, False)
        return "ACCEPT:" + r["result_for_player_to_move"], r
    except (pv1.VerificationError, OSError, EOFError, UnicodeError, RecursionError) as exc:
        return "reject", str(exc)[:90]
    except Exception as exc:
        return "CRASH:" + type(exc).__name__, str(exc)[:90]


results = []
sys.setrecursionlimit(10000)
for c in CASES:
    d = RT / c["name"]
    d.mkdir()
    (d / "proof.jsonl").write_bytes(c["proof"])
    pos = c["position"]
    (d / "position.json").write_bytes(pos if isinstance(pos, bytes) else json.dumps(pos, ensure_ascii=False).encode())
    files = {"dict": c["dictionary"] or DICT, "pos": d / "position.json", "proof": d / "proof.jsonl",
             "input": c["input"]}
    toy = c["word_count"] == 0
    pin = "" if toy else vf.PINNED_DICTIONARY_SHA256
    v2 = run_v2(c, files)
    compat = run_fast(c, files, hardened=False, legacy_dueum=True)
    hard = run_fast(c, files, hardened=True, dictionary_sha256=pin)
    hard_c = run_fast(c, files, hardened=True, dictionary_sha256=pin, engine="c")
    patched = run_patched(c, files, pin)
    results.append({"case": c["name"], "expect": c["expect"], "verify_v2": v2[0], "v2_detail": v2[1] if isinstance(v2[1], str) else "",
                    "fast_compat_legacy_dueum": compat[0], "fast_hardened": hard[0], "fast_hardened_c": hard_c[0], "patched_verify_v2": patched[0],
                    "hardened_detail": hard[1] if isinstance(hard[1], str) else "", "note": c["note"]})

bad = []
for r in results:
    v2ok = r["verify_v2"].startswith("ACCEPT")
    if r["expect"] == "reject" and v2ok:
        bad.append(("verify_v2 accepted a mutation", r["case"]))
    if r["expect"] == "reject" and r["fast_hardened"].startswith("ACCEPT"):
        bad.append(("verify_fast accepted a mutation", r["case"]))
    if r["fast_compat_legacy_dueum"].split(":")[0] != r["verify_v2"].split(":")[0] and not r["verify_v2"].startswith("CRASH"):
        bad.append(("compat mode differs from verify_v2", r["case"]))
    if r["verify_v2"].startswith("ACCEPT") and r["fast_compat_legacy_dueum"] != r["verify_v2"]:
        bad.append(("compat verdict differs", r["case"]))
    if r["fast_hardened"] != r["fast_hardened_c"]:
        bad.append(("python/C engines differ", r["case"]))
    if r["expect"] == "reject" and r["patched_verify_v2"].startswith("ACCEPT"):
        bad.append(("patched verify_v2 accepted a mutation", r["case"]))
    if r["expect"] == "accept" and not r["fast_hardened"].startswith("ACCEPT") and r["case"] not in ():
        bad.append(("hardened rejected an equivalent encoding", r["case"]))

w = max(len(r["case"]) for r in results)
print(f"{'case':<{w}}  {'expect':<6}  {'verify_v2':<14} {'fast-compat':<12} {'fast-hard':<10} {'v2-patched':<10} detail")
for r in results:
    print(f"{r['case']:<{w}}  {r['expect']:<6}  {r['verify_v2']:<14} {r['fast_compat_legacy_dueum']:<12} "
          f"{r['fast_hardened']:<10} {r['patched_verify_v2']:<10} {(r['v2_detail'] or r['hardened_detail'])[:60]}")
print("cases", len(results), "problems", bad)
(RT / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1))
