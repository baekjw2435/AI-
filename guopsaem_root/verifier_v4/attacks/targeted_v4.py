#!/usr/bin/env python3
"""Targeted attacks on verify_v4.py and verify_v4 (C++).

Every attack is written to attacks/cases/<name>/ (d.txt, p.json, proof file, optional in.txt,
cmd.sh with the exact commands) and run against verify_v4.py (exact and --digest-only) and the
C++ verifier (exact and --digest-only).  `expect` is what a correct verifier must do:
  "reject"          - must be rejected;
  "accept:X"        - a sound certificate whose root result is X (X = true value);
  "any"             - acceptance or rejection are both fine, but the two verifiers should agree
                      and an acceptance must give the true value.
An "issue" is: acceptance of a wrong result, acceptance where expect=reject, a crash (exit code
other than 0/1 or an uncaught Python exception), a timeout, or a Python/C++ disagreement.

Usage: targeted_v4.py [CPP_BINARY]   (default build/verify_v4); writes attacks/results_targeted.json
"""
import copy
import gzip
import hashlib
import json
import random
import re
import shutil
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import attack_lib as A  # noqa: E402
from attack_lib import ModelV3, Writer, dumps  # noqa: E402

HERE = Path(__file__).resolve().parent
CASES = HERE / "cases"

# Base dictionary (found by search: shared groups, an L node with two groups to one child).
WORDS = ['넨돵줭넨', '넨뵮려', '넨쁶닒엿', '넨여', '녀', '녀녓', '녀륜', '녓렠륜', '녓쯔녀', '눙', '눙괣눙', '눙땹햮엿',
         '눙엄멦여', '눙엿', '려솙퍨엿', '려핍넨', '렷퇤녀', '룽힓윤', '륜', '륜깆엿', '륜랿샗룽', '륜렠윤', '여뽓여', '여엿',
         '엿녀', '엿렷', '엿륜', '엿홰녀', '엿힓엿', '윤퉅륜']
POS = {"initial_syllable": "려", "history": [], "initial_used_words": ["눙땹햮엿", "여뽓여"]}


def replay(model, pos, nodes):
    """state info of reached nodes: id -> (vertex, counts, static, legal groups)."""
    cur, rs = A.root_state(model, pos)
    root = len(nodes) - 1
    state = {root: (cur, rs)}
    stack = [root]
    info = {}
    while stack:
        i = stack.pop()
        v, c = state[i]
        _, static = model.normalize(v, c)
        info[i] = (v, c, static, [g for g in model.available[v] if c[g]])
        for g, ch in nodes[i]["m"]:
            if ch not in state:
                tv, tc, _ = model.child(v, c, g)
                state[ch] = (tv, tc)
                stack.append(ch)
    return info


def text_of(header, nodes):
    return "\n".join([dumps(header)] + [dumps(n) for n in nodes]) + "\n"


def main():
    cpp = sys.argv[1] if len(sys.argv) > 1 else A.CPP
    if CASES.exists():
        shutil.rmtree(CASES)
    CASES.mkdir(parents=True)
    model = ModelV3(" ".join(WORDS).encode(), 0)
    truth = A.position_truth(WORDS, POS)
    cur, rs = A.root_state(model, POS)
    w = Writer(model, random.Random(1))
    w.build(cur, rs)
    nodes = w.lines
    header = w.header()
    info = replay(model, POS, nodes)
    G = len(model.edges)
    cases = []   # (name, expect, files{name: bytes}, note, input?, position override)

    def add(name, expect, proof_bytes, note, pos=None, inp=None, words=None, proof_name="proof.jsonl"):
        cases.append(dict(name=name, expect=expect, proof=proof_bytes, note=note, pos=pos, inp=inp, words=words,
                          proof_name=proof_name))

    base_text = text_of(header, nodes)
    add("base_writer", f"accept:{truth}", base_text.encode(), "independent writer certificate (valid)")

    def mut(fn, name, expect, note, hdr=None):
        ns = copy.deepcopy(nodes)
        fn(ns)
        add(name, expect, text_of(hdr or header, ns).encode(), note)

    root = len(nodes) - 1
    nonstatic = [i for i in sorted(info) if info[i][2] == -1]
    statics = [i for i in sorted(info) if info[i][2] != -1]
    Ls = [i for i in nonstatic if nodes[i]["r"] == "L"]
    Ws = [i for i in nonstatic if nodes[i]["r"] == "W"]

    # --- shared group played from a vertex that is not one of its sources (it is legal elsewhere)
    done = False
    for i in nonstatic:
        v, c, _, legal = info[i]
        wrong = [g for g in range(G) if c[g] and model.shared[g] and v not in model.edges[g][0]]
        if wrong and not done:
            g = wrong[0]
            def f(ns, i=i, g=g):
                ns[i]["m"].append([g, ns[i]["m"][0][1]])
            mut(f, "shared_group_wrong_vertex_extra", "reject", f"node {i} at vertex {v}: shared group {g} "
                f"(sources {model.edges[g][0]}) added as an extra move")
            if nodes[i]["r"] == "W":
                def f2(ns, i=i, g=g):
                    ns[i]["m"][0][0] = g
                mut(f2, "shared_group_wrong_vertex_witness", "reject", f"W node {i}: witness group replaced by {g}")
            done = True
    # a group with zero count (used in initial_used_words) but legal from this vertex
    for i in nonstatic:
        v, c, _, legal = info[i]
        zero = [g for g in model.available[v] if not c[g]]
        if zero:
            def f(ns, i=i, g=zero[0]):
                ns[i]["m"].append([g, ns[i]["m"][0][1]])
            mut(f, "zero_count_group", "reject", f"node {i}: group {zero[0]} has count 0 here")
            break
    # --- DAG re-entry with a different state: redirect an edge to another node with the same vertex and result
    for i in nonstatic:
        for slot, (g, ch) in enumerate(nodes[i]["m"]):
            alts = [j for j in info if j < i and j != ch and info[j][0] == info[ch][0]
                    and nodes[j]["r"] == nodes[ch]["r"] and info[j][1] != info[ch][1]]
            if alts:
                def f(ns, i=i, slot=slot, j=alts[0]):
                    ns[i]["m"][slot][1] = j
                mut(f, "dag_reentry_other_state", "reject", f"node {i} move {slot} redirected to node {alts[0]} "
                    "(same vertex, same result, different counts)")
                break
        else:
            continue
        break
    # --- the same: but the redirect target is reached FIRST through the redirected edge (order of DFS)
    #     i.e. redirect the root's first move: the other node is reached later with its true state
    if nodes[root]["m"]:
        g0, ch0 = nodes[root]["m"][0]
        alts = [j for j in info if j != ch0 and info[j][0] == info[ch0][0] and nodes[j]["r"] == nodes[ch0]["r"]
                and info[j][1] != info[ch0][1]]
        if alts:
            def f(ns, j=alts[0]):
                ns[-1]["m"][0][1] = j
            mut(f, "dag_reentry_root_edge_first", "reject", "root witness redirected to another node of the same vertex")
    # --- tree certificate (no sharing), then merge identical states by hand: must be accepted
    wt = Writer(model, random.Random(1), share=False)
    wt.build(cur, rs)
    add("tree_no_sharing", f"accept:{truth}", wt.text().encode(), f"same proof without DAG sharing ({len(wt.lines)} nodes)")
    # --- L node listing two groups that lead to one canonical child (legit DAG merge)
    two = [i for i in Ls if len({ch for _, ch in nodes[i]["m"]}) < len(nodes[i]["m"])]
    add("L_two_groups_one_child", f"accept:{truth}" if two else "any", base_text.encode(),
        f"nodes {two} list two groups whose children are the same node")
    # --- W node pointing to W child
    if Ws:
        i = Ws[-1]
        ch = nodes[i]["m"][0][1]
        def f(ns, ch=ch):
            ns[ch]["r"] = "W"
        mut(f, "W_child_flipped_to_W", "reject", f"child {ch} of W node {i} claims W")
    # --- static: "k":"static" on a static leaf (allowed) and on a non-static node
    if statics:
        def f(ns, j=statics[0]):
            ns[j]["k"] = "static"
        mut(f, "static_claim_on_static", f"accept:{truth}", "k:static on a real static leaf")
        def f(ns, j=statics[0]):
            ns[j]["r"] = "W" if ns[j]["r"] == "L" else "L"
        mut(f, "static_label_flipped", "reject", "static leaf with the wrong label")
    def f(ns):
        ns[-1]["k"] = "static"
        ns[-1]["m"] = []
    mut(f, "root_static_claim_no_moves", "reject" if info[root][2] == -1 else f"accept:{truth}", "root claims static")
    # --- unreached garbage nodes (false claims about nothing); shifted ids
    def f(ns):
        shift = 3
        for n in ns:
            n["id"] += shift
            n["m"] = [[g, ch + shift] for g, ch in n["m"]]
        garbage = [{"id": 0, "r": "W", "m": []}, {"id": 1, "r": "L", "m": [[0, 0]]}, {"id": 2, "r": "W", "m": [[1, 1]], "k": "static"}]
        ns[:0] = garbage
    mut(f, "unreached_garbage", f"accept:{truth}", "3 unreached nodes with nonsense claims; reported as unreached",
        hdr=dict(header, root=header["root"] + 3))
    # --- root identification: duplicate root appended as new last node
    def f(ns):
        r = copy.deepcopy(ns[-1]); r["id"] = len(ns); ns.append(r)
    mut(f, "root_duplicated_last", f"accept:{truth}", "copy of the root appended, header root updated",
        hdr=dict(header, root=header["root"] + 1))
    def f(ns):
        r = copy.deepcopy(ns[-1]); r["id"] = len(ns); r["r"] = "L" if r["r"] == "W" else "W"; ns.append(r)
    mut(f, "root_duplicate_flipped_last", "reject", "root copy with flipped result appended as root",
        hdr=dict(header, root=header["root"] + 1))
    # --- header / id / JSON quirks
    lines = base_text.splitlines()
    def raw(name, expect, lines_, note, sep="\n", end="\n"):
        add(name, expect, (sep.join(lines_) + end).encode() if isinstance(lines_[0], str) else b"", note)
    h = dict(header)
    hdr_variants = {
        "hdr_groups_true": ('"groups":' + str(G), '"groups":true', "reject"),
        "hdr_groups_float": ('"groups":' + str(G), f'"groups":{G}.0', "reject"),
        "hdr_groups_exp": ('"groups":' + str(G), f'"groups":{G}e0', "reject"),
        "hdr_groups_string": ('"groups":' + str(G), f'"groups":"{G}"', "reject"),
        "hdr_root_dup_key": ('"root":' + str(root), f'"root":{root},"root":{root}', "reject"),
        "hdr_root_float": ('"root":' + str(root), f'"root":{root}.0', "reject"),
        "hdr_root_huge": ('"root":' + str(root), f'"root":{root + 2**64}', "reject"),
        "hdr_root_neg": ('"root":' + str(root), f'"root":-1', "reject"),
        "hdr_root_nan": ('"root":' + str(root), '"root":NaN', "reject"),
        "hdr_format_escaped": ('"format":"route-proof-v4"', '"format":"route-proof-\\u0076\\u0034"', f"accept:{truth}"),
        "hdr_key_escaped": ('"format"', '"\\u0066ormat"', f"accept:{truth}"),
        "hdr_dup_key_escaped": ('"groups":' + str(G), f'"groups":{G},"\\u0067roups":{G}', "reject"),
        "hdr_input_null": ('"root":' + str(root), f'"root":{root},"input_sha256":null', "reject"),
        "hdr_format_v3": ('"format":"route-proof-v4"', '"format":"route-proof-v3"', "reject"),
    }
    for name, (old, new, expect) in hdr_variants.items():
        assert old in lines[0], (name, lines[0])
        add(name, expect, ("\n".join([lines[0].replace(old, new, 1)] + lines[1:]) + "\n").encode(), f"header: {new}")
    n0 = lines[1]
    assert n0.startswith('{"id":0,')
    node_variants = {
        "id_neg_zero": ('{"id":0,', '{"id":-0,', f"accept:{truth}"),
        "id_float": ('{"id":0,', '{"id":0.0,', "reject"),
        "id_exp": ('{"id":0,', '{"id":0e0,', "reject"),
        "id_bool_false": ('{"id":0,', '{"id":false,', "reject"),
        "id_string": ('{"id":0,', '{"id":"0",', "reject"),
        "id_leading_zero": ('{"id":0,', '{"id":00,', "reject"),
        "id_dup_key": ('{"id":0,', '{"id":0,"id":0,', "reject"),
        "id_key_escaped": ('{"id":0,', '{"\\u0069d":0,', f"accept:{truth}"),
        "r_escaped": ('"r":"', '"r":"\\u00' + ('57' if '"r":"W"' in n0 else '4c') + '"' + '#', f"accept:{truth}"),
        "spaces_everywhere": ('{"id":0,', '{ "id" : 0 , ', f"accept:{truth}"),
        "nul_byte": ('{"id":0,', '{"id":0,\x00', "reject"),
        "lone_surrogate_key": ('{"id":0,', '{"id":0,"\\ud800":1,', "reject"),
        "unknown_key_v": ('{"id":0,', '{"id":0,"v":0,', "reject"),
        "k_null": ('{"id":0,', '{"id":0,"k":null,', "reject"),
        "k_upper": ('{"id":0,', '{"id":0,"k":"Static",', "reject"),
        "r_lower": ('"r":"', '"r":"x', "reject"),
        "trailing_data": ('{"id":0,', '[] {"id":0,', "reject"),
    }
    for name, (old, new, expect) in node_variants.items():
        line = n0
        if name == "r_escaped":
            line = n0.replace('"r":"W"', '"r":"\\u0057"').replace('"r":"L"', '"r":"\\u004c"')
        elif name == "r_lower":
            line = n0.replace('"r":"W"', '"r":"w"').replace('"r":"L"', '"r":"l"')
        else:
            line = n0.replace(old, new, 1)
        add(name, expect, ("\n".join([lines[0], line] + lines[2:]) + "\n").encode(), f"node 0 line: {line}")
    # move-level JSON quirks on the root line
    rl = lines[-1]
    if nodes[root]["m"]:
        g, ch = nodes[root]["m"][0]
        mv = f"[{g},{ch}]"
        assert mv in rl
        for name, new, expect in [
            ("move_group_float", f"[{g}.0,{ch}]", "reject"),
            ("move_group_neg_zero", f"[-0,{ch}]" if g == 0 else f"[{g},-0]" if ch == 0 else f"[{g},{ch}]", "any"),
            ("move_group_wrap64", f"[{g + 2**64},{ch}]", "reject"),
            ("move_group_wrap32", f"[{g + 2**32},{ch}]", "reject"),
            ("move_child_wrap32", f"[{g},{ch + 2**32}]", "reject"),
            ("move_child_wrap64", f"[{g},{ch + 2**64}]", "reject"),
            ("move_child_neg", f"[{g},{ch - 2**32}]", "reject"),
            ("move_three", f"[{g},{ch},0]", "reject"),
            ("move_true", f"[true,{ch}]" if g == 1 else f"[{g},true]" if ch == 1 else f"[{g},{ch},true]", "reject"),
            ("move_nan", f"[NaN,{ch}]", "reject"),
            ("move_inf", f"[{g},Infinity]", "reject"),
            ("move_nested", f"[[{g}],{ch}]", "reject"),
            ("move_spaces", f"[ {g} , {ch} ]", f"accept:{truth}"),
            ("move_19digit_zero", f"[{g},{'0' * 19}]", "reject"),
            ("move_18digit", f"[{g},{10**17 + ch}]", "reject"),
            ("move_4301_digits", f"[{g},{'1' * 4301}]", "reject"),
        ]:
            add(name, expect, ("\n".join(lines[:-1] + [rl.replace(mv, new, 1)]) + "\n").encode(), f"root move {mv} -> {new[:60]}")
    # line structure
    add("crlf_lines", f"accept:{truth}", ("\r\n".join(lines) + "\r\n").encode(), "CRLF line ends")
    add("no_final_newline", f"accept:{truth}", "\n".join(lines).encode(), "no final LF")
    add("double_cr", f"accept:{truth}", ("\r\r\n".join(lines) + "\r\r\n").encode(), "CR CR LF (CRs are JSON whitespace)")
    add("blank_line_end", "reject", ("\n".join(lines) + "\n\n").encode(), "empty last line")
    add("blank_line_mid", "reject", ("\n".join(lines[:2] + [""] + lines[2:]) + "\n").encode(), "empty line")
    add("ws_only_line_end", "reject", ("\n".join(lines) + "\n \n").encode(), "whitespace-only last line")
    add("bom_proof", "reject", b"\xef\xbb\xbf" + base_text.encode(), "UTF-8 BOM before the header")
    add("cr_only_separators", "reject", ("\r".join(lines) + "\n").encode(), "CR used as line separator")
    add("vertical_tab_ws", "reject", ("\n".join([lines[0].replace(",", ",\x0b", 1)] + lines[1:]) + "\n").encode(),
        "VT is not JSON whitespace")
    add("u2028_inside_string_line", "reject", ("\n".join([lines[0].replace('"format"', '"format "', 1)] + lines[1:]) + "\n").encode(),
        "U+2028 in a key (unknown key)")
    add("header_only", "reject", (lines[0] + "\n").encode(), "no nodes")
    add("empty_file", "reject", b"", "empty file")
    # gzip variants
    gz = gzip.compress(base_text.encode())
    add("gz_plain", f"accept:{truth}", gz, "gzip", proof_name="proof.jsonl.gz")
    b = base_text.encode()
    cut = len(b) // 2 + 3
    add("gz_two_members_midline", f"accept:{truth}", gzip.compress(b[:cut]) + gzip.compress(b[cut:]),
        "two gzip members split inside a line", proof_name="proof.jsonl.gz")
    add("gz_empty_member_end", f"accept:{truth}", gz + gzip.compress(b""), "extra empty gzip member", proof_name="proof.jsonl.gz")
    add("gz_zero_padding", "any", gz + b"\x00" * 16, "16 zero bytes after the gzip member (FORMAT.md: trailing bytes invalid)",
        proof_name="proof.jsonl.gz")
    add("gz_one_zero_byte", "any", gz + b"\x00", "1 zero byte after the gzip member", proof_name="proof.jsonl.gz")
    add("gz_trailing_magic_only", "reject", gz + b"\x1f\x8b", "trailing partial gzip header", proof_name="proof.jsonl.gz")
    add("gz_trailing_garbage", "reject", gz + b"junk", "trailing garbage", proof_name="proof.jsonl.gz")
    bad = bytearray(gz); bad[-8] ^= 1
    add("gz_bad_crc", "reject", bytes(bad), "CRC32 flipped", proof_name="proof.jsonl.gz")
    bad = bytearray(gz); bad[-1] ^= 1
    add("gz_bad_isize", "reject", bytes(bad), "ISIZE flipped", proof_name="proof.jsonl.gz")
    # header with FNAME + FCOMMENT + FHCRC + FEXTRA
    body = zlib.compressobj(9, zlib.DEFLATED, -15)
    deflated = body.compress(b) + body.flush()
    hdr = bytearray(b"\x1f\x8b\x08\x1e" + b"\x00\x00\x00\x00\x00\xff")  # FHCRC|FEXTRA|FNAME|FCOMMENT
    hdr += struct.pack("<H", 3) + b"abc" + b"name\x00" + b"comment\x00"
    hdr += struct.pack("<H", zlib.crc32(bytes(hdr)) & 0xFFFF)
    full = bytes(hdr) + deflated + struct.pack("<II", zlib.crc32(b) & 0xFFFFFFFF, len(b) & 0xFFFFFFFF)
    add("gz_all_header_flags", f"accept:{truth}", full, "FEXTRA FNAME FCOMMENT FHCRC", proof_name="proof.jsonl.gz")
    hdr2 = bytearray(hdr); hdr2[-1] ^= 0xFF
    add("gz_bad_header_crc", "any", bytes(hdr2) + deflated + full[len(hdr) + len(deflated):],
        "wrong FHCRC (zlib checks it, Python does not)", proof_name="proof.jsonl.gz")
    add("gz_raw_deflate_magic", "reject", b"\x1f\x8b" + deflated, "magic then raw deflate", proof_name="proof.jsonl.gz")
    # --- input_sha256 handling
    inp_std = model.numeric_input(*model.position(POS)[:2])
    sha = hashlib.sha256(inp_std).hexdigest()
    hdr_in = dict(header, input_sha256=sha)
    add("input_sha_ok", f"accept:{truth}", text_of(hdr_in, nodes).encode(), "input_sha256 + --input", inp=inp_std)
    add("input_sha_without_input", "reject", text_of(hdr_in, nodes).encode(), "input_sha256 but no --input")
    add("input_sha_upper", "reject", text_of(dict(header, input_sha256=sha.upper()), nodes).encode(), "uppercase hex", inp=inp_std)
    # equivalent numeric inputs (Python int() parsing): + signs, underscores, leading zeros, odd whitespace
    toks = inp_std.decode().split("\n")
    v_plus = ("\n".join("+" + t.replace(" ", " +") if t else t for t in toks)).encode()
    v_under = re.sub(rb"[0-9]+", lambda m: b"_".join(bytes([c]) for c in m.group(0)), inp_std)  # 12 -> 1_2
    v_ws = inp_std.replace(b" ", b"\x1c").replace(b"\n", b"\x0b\x0c\r\n")
    v_zero18 = inp_std.replace(b"\n", b"\n" + b"0" * 17 + b"0 ", 1)  # inserts a token "000..0" (18 digits) -> mismatch
    first = toks[0].split()
    v_zero19 = (" ".join(["0" * 18 + first[0]] + first[1:]) + "\n" + "\n".join(toks[1:])).encode()
    for name, data, note in [("input_plus_signs", v_plus, "+N tokens"), ("input_underscores", v_under, "1_2 tokens (underscores between digits)"),
                             ("input_odd_ascii_ws", v_ws, "0x1c/VT/FF/CR separators"),
                             ("input_19_digit_leading_zeros", v_zero19, "first token zero-padded to 19+ digits"),
                             ("input_extra_token", v_zero18, "an extra token (must mismatch)")]:
        hs = hashlib.sha256(data).hexdigest()
        add(name, "reject" if name == "input_extra_token" else f"accept:{truth}", text_of(dict(header, input_sha256=hs), nodes).encode(),
            note, inp=data)
    # --- position quirks
    pj = json.dumps(POS, ensure_ascii=False)
    pos_cases = [
        ("pos_bom", b"\xef\xbb\xbf" + pj.encode(), f"accept:{truth}", "UTF-8 BOM"),
        ("pos_utf16", pj.encode("utf-16"), "any", "UTF-16 with BOM (documented C++ difference)"),
        ("pos_dup_key", pj.replace('"history": []', '"history": [], "history": []').encode(), "reject", "duplicate key"),
        ("pos_escaped_syllable", json.dumps(POS).encode(), f"accept:{truth}", "\\u escapes"),
        ("pos_extra_key_depth_950", (pj[:-1] + ', "x": ' + "[" * 950 + "]" * 950 + "}").encode(), "any",
         "extra key nested 950 deep"),
        ("pos_extra_key_depth_20000", (pj[:-1] + ', "x": ' + "[" * 20000 + "]" * 20000 + "}").encode(), "reject-clean",
         "extra key nested 20000 deep"),
        ("pos_history_null", pj.replace('"history": []', '"history": null').encode(), "reject", "history null"),
        ("pos_no_history", json.dumps({"initial_syllable": "려", "initial_used_words": POS["initial_used_words"]},
                                      ensure_ascii=False).encode(), "reject", "history missing"),
        ("pos_used_null", pj.replace('"initial_used_words": [', '"initial_used_words": null, "y": [').encode(), "reject",
         "initial_used_words null"),
        ("pos_used_dup", pj.replace('"눙땹햮엿"', '"눙땹햮엿", "눙땹햮엿"').encode(), "reject", "a word used twice"),
        ("pos_syllable_two", pj.replace('"려"', '"려려"').encode(), "reject", "two-syllable initial"),
        ("pos_syllable_latin", pj.replace('"려"', '"a"').encode(), "reject", "non-Hangul initial"),
        ("pos_syllable_surrogate", pj.replace('"려"', '"\\ud800"').encode(), "reject", "lone surrogate initial"),
        ("pos_syllable_nfd", pj.replace('"려"', '"려"').encode(), "reject", "decomposed jamo"),
        ("pos_big_int_extra", (pj[:-1] + ', "z": ' + "9" * 5000 + "}").encode(), "any", "5000-digit integer in an extra key"),
        ("pos_trailing_garbage", (pj + "x").encode(), "reject", "trailing data"),
        ("pos_nan_extra", (pj[:-1] + ', "z": NaN}').encode(), f"accept:{truth}", "NaN in an extra key"),
        ("pos_array", b"[]", "reject", "not an object"),
    ]
    for name, data, expect, note in pos_cases:
        add(name, expect, base_text.encode(), note, pos=data)
    # same canonical root from another position: dropping a used word that the reduction removes anyway
    alt = dict(POS, initial_used_words=POS["initial_used_words"][:1])
    alt_rs = A.root_state(model, alt)
    expect_alt = (f"accept:{A.position_truth(WORDS, alt)}" if alt_rs == (cur, rs) else "reject")
    add("pos_other_same_canonical", expect_alt, base_text.encode(),
        f"another position; same canonical root: {alt_rs == (cur, rs)}", pos=json.dumps(alt, ensure_ascii=False).encode())
    # --- dictionary quirks (parity of str.split and utf-8-sig)
    for name, sep, expect in [("dict_sep_u3000", "　", f"accept:{truth}"), ("dict_sep_x1c", "\x1c", f"accept:{truth}"),
                              ("dict_sep_x85", "\x85", f"accept:{truth}"), ("dict_sep_u200b", "​", "reject"),
                              ("dict_sep_u180e", "᠎", "reject"), ("dict_bom", "BOM", f"accept:{truth}")]:
        add(name, expect, base_text.encode(), f"dictionary separated by {sep!r}", words=sep)
    run_all(cases, cpp, model)


def run_all(cases, cpp, model):
    results = []
    issues = []
    for case in cases:
        d = CASES / case["name"]
        d.mkdir(parents=True)
        sep = case["words"]
        dict_path = d / "d.txt"
        if sep is None:
            dict_path.write_text(" ".join(WORDS), encoding="utf-8")
        elif sep == "BOM":
            dict_path.write_bytes(b"\xef\xbb\xbf" + " ".join(WORDS).encode())
        else:
            dict_path.write_text(sep.join(WORDS), encoding="utf-8")
        pos_path = d / "p.json"
        pos_path.write_bytes(case["pos"] if case["pos"] is not None else json.dumps(POS, ensure_ascii=False).encode())
        proof = d / case["proof_name"]
        proof.write_bytes(case["proof"])
        inp = None
        if case["inp"] is not None:
            inp = d / "in.txt"
            inp.write_bytes(case["inp"])
        rel = lambda p: str(p.relative_to(HERE.parent.parent.parent)) if p else None  # noqa: E731
        base = (f"--dictionary {rel(dict_path)} --expected-word-count 0 --position {rel(pos_path)} --proof {rel(proof)}"
                + (f" --input {rel(inp)}" if inp else ""))
        (d / "cmd.sh").write_text("#!/bin/sh\n# run from the repository root\n"
                                  f"python3 guopsaem_root/verifier_v4/verify_v4.py {base}\n"
                                  f"guopsaem_root/verifier_v4/build/verify_v4 {base}\n"
                                  f"python3 guopsaem_root/verifier_v4/verify_v4.py {base} --digest-only\n"
                                  f"guopsaem_root/verifier_v4/build/verify_v4 {base} --digest-only\n")
        outs = {"py": A.run_py_sub(dict_path, pos_path, proof, inp),
                "py_digest": A.run_py_sub(dict_path, pos_path, proof, inp, digest_only=True),
                "cpp": A.run_cpp(dict_path, pos_path, proof, inp, binary=cpp),
                "cpp_digest": A.run_cpp(dict_path, pos_path, proof, inp, digest_only=True, binary=cpp)}
        expect = case["expect"]
        problems = []
        kinds = {k: o[0] for k, o in outs.items()}
        for k, o in outs.items():
            if o[0] in ("crash", "timeout"):
                problems.append(f"{k} {o[0]}: {o[1][:200]}")
            if o[0] == "accept":
                if expect in ("reject", "reject-clean"):
                    problems.append(f"{k} ACCEPTED (expected reject) result {o[1]}")
                elif expect.startswith("accept:") and o[1] != expect.split(":")[1]:
                    problems.append(f"{k} accepted WRONG result {o[1]}")
            if o[0] == "reject" and expect.startswith("accept:"):
                problems.append(f"{k} rejected a valid certificate: {o[1][:120]}")
        if len({(o[0], o[1] if o[0] == "accept" else "") for o in outs.values()}) > 1:
            problems.append("verifiers disagree: " + json.dumps(kinds))
        row = {"name": case["name"], "expect": expect, "note": case["note"], "outcomes": outs, "problems": problems,
               "dir": str(d)}
        results.append(row)
        if problems:
            issues.append(row)
        print(f"{case['name']:34s} {expect:10s} " + " ".join(f"{k}={v}" for k, v in kinds.items())
              + ("   <-- " + "; ".join(problems) if problems else ""), flush=True)
    out = HERE / "results_targeted.json"
    out.write_text(json.dumps({"cases": len(results), "issues": issues, "results": results}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"{len(results)} cases, {len(issues)} with problems -> {out}")


if __name__ == "__main__":
    main()
