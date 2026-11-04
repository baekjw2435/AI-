#!/usr/bin/env python3
"""Mutation fuzzer for route-proof-v4 verifiers (verify_v4.py in process, C++ by subprocess).

Each round: a random small dictionary and position (history / initial_used_words), a valid
base certificate (patched solver or the independent attack_lib.Writer, with or without DAG
sharing, gzip or plain, sometimes with input_sha256), then MUTANTS mutants with 1-3 random
mutations each: structural (flip results, retarget edges, change groups, add/drop/duplicate
moves, delete/duplicate/swap nodes with renumbering, false static claims, consistent
"lie chains" that flip a whole path of results, splicing in a certificate of another
position, unreached nodes, header edits) and textual (byte edits, insertions of JSON
punctuation, line swaps/duplication/truncation, CRLF, gzip member splits).

Oracle (any of these is an issue and is saved under WORKDIR/issues/):
  * a crash (uncaught Python exception, C++ exit code other than 0/1, sanitizer report), a timeout;
  * Python and C++ disagree (accept vs reject, or a different result);
  * an accepted certificate whose result differs from the true value (model minimax, and the
    raw word-game brute force when the dictionary has at most RAW_MAX words);
  * the base certificate is rejected.
Usage: fuzz_v4.py WORKDIR SECONDS SEED [CPP_BINARY]
"""
import copy
import gzip
import hashlib
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import attack_lib as A  # noqa: E402
from attack_lib import ModelV3, Writer, dumps  # noqa: E402

MUTANTS = 25
RAW_MAX = 16
STATE_BUDGET = 4000
BIG_PROB = 0.35
BIG_MAX_EXTRA = 4
PUNCT = list('{}[],:"0123456789-.eE \r\n\tWLkx\\u') + ["NaN", "true", "-0", "1e0", '"k":"static"', "\x00", "\xff"]


def replay(model, root_v, root_c, nodes):
    state = {len(nodes) - 1: (root_v, root_c)}
    stack = [len(nodes) - 1]
    info = {}
    while stack:
        i = stack.pop()
        v, c = state[i]
        _, static = model.normalize(v, c)
        info[i] = (v, c, static)
        for g, ch in nodes[i]["m"]:
            if ch not in state and 0 <= ch < i:
                try:
                    tv, tc, _ = model.child(v, c, g)
                except Exception:  # noqa: BLE001 - only used on valid bases
                    continue
                state[ch] = (tv, tc)
                stack.append(ch)
    return info


def renumber(nodes, order):
    """order: list of old ids in new file order; references to removed ids go to a random kept id."""
    new_of = {old: new for new, old in enumerate(order)}
    out = []
    for new, old in enumerate(order):
        n = copy.deepcopy(nodes[old])
        n["id"] = new
        n["m"] = [[g, new_of.get(ch, max(0, new - 1))] for g, ch in n["m"]]
        out.append(n)
    return out


class Mutator:
    def __init__(self, rng, model, info, G, other_nodes):
        self.rng, self.model, self.info, self.G, self.other = rng, model, info, G, other_nodes

    def structural(self, nodes, header):
        rng, G = self.rng, self.G
        n = len(nodes)
        reached = [i for i in self.info if i < n]
        pick = lambda: rng.choice(reached) if reached and rng.random() < 0.8 else rng.randrange(n)  # noqa: E731
        kind = rng.randrange(20)
        i = pick()
        nd = nodes[i]
        if kind == 0:
            nd["r"] = "L" if nd["r"] == "W" else "W"
        elif kind == 1 and nd["m"]:
            k = rng.randrange(len(nd["m"]))
            if i > 0:
                same_v = [j for j in self.info if j < i and self.info.get(nd["m"][k][1], (None,))[0] == self.info[j][0]]
                nd["m"][k][1] = rng.choice(same_v) if same_v and rng.random() < 0.7 else rng.randrange(i)
        elif kind == 2 and nd["m"]:
            k = rng.randrange(len(nd["m"]))
            if i in self.info and rng.random() < 0.7:
                v, c, _ = self.info[i]
                choices = [g for g in range(G) if c[g]]  # positive count, legal here or elsewhere
                if choices:
                    nd["m"][k][0] = rng.choice(choices)
            else:
                nd["m"][k][0] = rng.randrange(G)
        elif kind == 3 and nd["m"]:
            nd["m"].pop(rng.randrange(len(nd["m"])))
        elif kind == 4 and i > 0:
            g = rng.randrange(G)
            if i in self.info and rng.random() < 0.7:
                v, c, _ = self.info[i]
                legal = [g for g in self.model.available[v] if c[g]]
                if legal:
                    g = rng.choice(legal)
            nd["m"].insert(rng.randrange(len(nd["m"]) + 1), [g, rng.randrange(i)])
        elif kind == 5 and nd["m"]:
            nd["m"].append(list(rng.choice(nd["m"])))
        elif kind == 6 and len(nd["m"]) >= 2:
            a, b = rng.sample(range(len(nd["m"])), 2)
            nd["m"][a][1], nd["m"][b][1] = nd["m"][b][1], nd["m"][a][1]
        elif kind == 7:
            nd["m"] = []
        elif kind == 8:
            nd["k"] = "static"
        elif kind == 9 and n > 1:   # delete a node
            order = [j for j in range(n) if j != i]
            nodes[:] = renumber(nodes, order)
            header["root"] = len(nodes) - 1
        elif kind == 10:            # duplicate a node right after itself
            order = list(range(i + 1)) + [i] + list(range(i + 1, n))
            new = renumber(nodes, order)
            if rng.random() < 0.5:  # let later nodes point to the copy
                for m in new[i + 2:]:
                    for mv in m["m"]:
                        if mv[1] == i and rng.random() < 0.5:
                            mv[1] = i + 1
            nodes[:] = new
            header["root"] = len(nodes) - 1
        elif kind == 11 and i + 1 < n:  # swap adjacent nodes
            order = list(range(n))
            order[i], order[i + 1] = order[i + 1], order[i]
            new_of = {old: new for new, old in enumerate(order)}
            out = []
            for new, old in enumerate(order):
                m = copy.deepcopy(nodes[old])
                m["id"] = new
                m["m"] = [[g, new_of[ch] if 0 <= ch < n else ch] for g, ch in m["m"]]
                out.append(m)
            nodes[:] = out
        elif kind == 12:            # consistent lie chain along a path
            j = i
            for _ in range(rng.randint(1, 6)):
                m = nodes[j]
                m["r"] = "L" if m["r"] == "W" else "W"
                if m["r"] == "W":
                    if not m["m"]:
                        if j in self.info and j > 0:
                            v, c, _ = self.info[j]
                            legal = [g for g in self.model.available[v] if c[g]]
                            if legal:
                                m["m"] = [[rng.choice(legal), rng.randrange(j)]]
                    elif len(m["m"]) > 1:
                        m["m"] = [rng.choice(m["m"])]
                if not m["m"]:
                    break
                j = rng.choice(m["m"])[1]
                if not (0 <= j < len(nodes)):
                    break
        elif kind == 13 and self.other:  # splice another position's certificate in front, redirect an edge
            shift = len(self.other)
            out = copy.deepcopy(self.other)
            for m in nodes:
                m = copy.deepcopy(m)
                m["id"] += shift
                m["m"] = [[g, ch + shift] for g, ch in m["m"]]
                out.append(m)
            tgt = rng.randrange(shift)
            cand = [m for m in out[shift:] if m["m"]]
            if cand:
                mm = rng.choice(cand)
                mm["m"][rng.randrange(len(mm["m"]))][1] = tgt
            nodes[:] = out
            header["root"] = len(nodes) - 1
        elif kind == 14:            # unreached nodes appended before the root
            extra = [{"id": 0, "r": rng.choice("WL"), "m": []} for _ in range(rng.randint(1, 3))]
            shift = len(extra)
            for k, e in enumerate(extra):
                e["id"] = k
            for m in nodes:
                m["id"] += shift
                m["m"] = [[g, ch + shift] for g, ch in m["m"]]
            nodes[:0] = extra
            header["root"] = len(nodes) - 1
        elif kind == 15:
            key = rng.choice(["groups", "vertices", "root"])
            header[key] = header[key] + rng.choice([-1, 1, 2**32, -2**32, 2**64])
        elif kind == 16:            # move root elsewhere: append a copy of some node as root
            c = copy.deepcopy(nd)
            c["id"] = n
            nodes.append(c)
            header["root"] = n
        elif kind == 17 and nd["m"]:  # child id out of order
            k = rng.randrange(len(nd["m"]))
            nd["m"][k][1] = rng.choice([i, i + 1, n, -1, 2**32 + nd["m"][k][1]])
        elif kind == 18:
            nd["id"] = nd["id"] + rng.choice([-1, 1])
        else:                       # flip the root and keep its moves (or empty)
            nodes[-1]["r"] = "L" if nodes[-1]["r"] == "W" else "W"
            if rng.random() < 0.5 and nodes[-1]["m"]:
                nodes[-1]["m"] = nodes[-1]["m"][:1]

    def textual(self, data):
        rng = self.rng
        lines = data.split(b"\n")
        kind = rng.randrange(8)
        if kind == 0 and data:
            p = rng.randrange(len(data))
            data = data[:p] + bytes([rng.randrange(256)]) + data[p + 1:]
        elif kind == 1 and data:
            p = rng.randrange(len(data))
            data = data[:p] + data[p + 1:]
        elif kind == 2:
            p = rng.randrange(len(data) + 1)
            data = data[:p] + rng.choice(PUNCT).encode("utf-8", "surrogatepass") + data[p:]
        elif kind == 3 and len(lines) > 2:
            a, b = rng.sample(range(len(lines)), 2)
            lines[a], lines[b] = lines[b], lines[a]
            data = b"\n".join(lines)
        elif kind == 4 and len(lines) > 1:
            a = rng.randrange(len(lines))
            lines.insert(a, lines[a])
            data = b"\n".join(lines)
        elif kind == 5:
            data = data[:rng.randrange(len(data) + 1)]
        elif kind == 6:
            data = data.replace(b"\n", b"\r\n")
        else:  # digits: replace a number by an equal-looking spelling
            import re
            nums = list(re.finditer(rb"[0-9]+", data))
            if nums:
                m = rng.choice(nums)
                rep = rng.choice([b"-" + m.group(0), m.group(0) + b".0", b"0" + m.group(0), m.group(0) + b"e0",
                                  str(int(m.group(0)) + 2**32).encode(), str(int(m.group(0)) + 2**64).encode()])
                data = data[:m.start()] + rep + data[m.end():]
        return data


def container(rng, data):
    """plain or gzip (single or split members); returns (bytes, suffix)."""
    r = rng.random()
    if r < 0.6:
        return data, ".jsonl"
    if r < 0.85:
        return gzip.compress(data, rng.choice([1, 6, 9])), ".jsonl.gz"
    cut = rng.randrange(len(data) + 1)
    return gzip.compress(data[:cut]) + gzip.compress(data[cut:]), ".jsonl.gz"


def main():
    work, seconds, seed = Path(sys.argv[1]), float(sys.argv[2]), int(sys.argv[3])
    cpp = sys.argv[4] if len(sys.argv) > 4 else A.CPP
    work.mkdir(parents=True, exist_ok=True)
    (work / "issues").mkdir(exist_ok=True)
    rng = random.Random(seed)
    stats = {"rounds": 0, "mutants": 0, "accepted_mutants": 0, "rejected_both": 0, "issues": 0,
             "py_digest_runs": 0, "cpp_digest_runs": 0, "solver_bases": 0, "writer_bases": 0, "gzip": 0,
             "raw_checked": 0, "true_W": 0, "true_L": 0, "issue_kinds": {}}
    t_end = time.monotonic() + seconds
    cpu0 = time.process_time()
    issue_no = 0

    def report(kind, payload, files):
        nonlocal issue_no
        issue_no += 1
        stats["issues"] += 1
        stats["issue_kinds"][kind] = stats["issue_kinds"].get(kind, 0) + 1
        d = work / "issues" / f"{issue_no:04d}_{kind}"
        d.mkdir(parents=True, exist_ok=True)
        for name, data in files.items():
            (d / name).write_bytes(data)
        (d / "info.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        print("ISSUE", kind, json.dumps(payload, ensure_ascii=False)[:400], flush=True)

    while time.monotonic() < t_end:
        stats["rounds"] += 1
        big = rng.random() < BIG_PROB
        words, model, pos = A.random_case(rng)
        if big:
            extra = set()
            for _ in range(rng.randint(1, BIG_MAX_EXTRA)):
                extra |= set(A.random_dictionary(rng))
            words = sorted(set(words) | extra)
            model = ModelV3(" ".join(words).encode(), 0)
            if any(w not in words for w in pos["initial_used_words"] + pos["history"]):
                continue
            try:
                model.position(pos)
            except A.VerificationError:
                continue
        rd = work / "round"
        d, p, inp = A.write_case(rd, words, model, pos)
        root_v, root_c = A.root_state(model, pos)
        wr = Writer(model, random.Random(rng.random()), share=rng.random() < 0.8)
        wr.budget = STATE_BUDGET
        try:
            truth_model = "W" if wr.value(root_v, root_c) else "L"
        except (OverflowError, RecursionError):
            stats["skipped_big"] = stats.get("skipped_big", 0) + 1
            continue
        truth = truth_model
        if len(words) <= RAW_MAX:
            truth_raw = A.position_truth(words, pos)
            stats["raw_checked"] += 1
            if truth_raw != truth_model:
                report("model_vs_raw", {"words": words, "pos": pos, "raw": truth_raw, "model": truth_model}, {})
            truth = truth_raw
        stats["true_" + truth] += 1
        input_sha = None
        if rng.random() < 0.5:
            stats["solver_bases"] += 1
            out = A.solve(inp, rd / "base.jsonl", "v4")
            if out.get("result") not in ("win", "loss"):
                continue
            lines = (rd / "base.jsonl").read_text(encoding="utf-8").splitlines()
            header = json.loads(lines[0])
            nodes = [json.loads(x) for x in lines[1:]]
        else:
            stats["writer_bases"] += 1
            wr.build(root_v, root_c)
            nodes = wr.lines
            header = wr.header()
        if rng.random() < 0.3:
            input_sha = hashlib.sha256(inp.read_bytes()).hexdigest()
            header["input_sha256"] = input_sha
        else:
            header.pop("input_sha256", None)
        use_inp = inp if (input_sha or rng.random() < 0.3) else None
        info = replay(model, root_v, root_c, nodes)
        # another position's certificate on the same dictionary, for splicing
        other = None
        starts = sorted(model.starts)
        try:
            opos = {"initial_syllable": rng.choice(starts), "history": [], "initial_used_words": []}
            ov, oc = A.root_state(model, opos)
            ow = Writer(model, random.Random(rng.random()))
            ow.build(ov, oc)
            other = ow.lines
        except Exception:  # noqa: BLE001
            other = None
        base_bytes = ("\n".join([dumps(header)] + [dumps(x) for x in nodes]) + "\n").encode()
        mut = Mutator(rng, model, info, len(model.edges), other)
        for k in range(MUTANTS + 1):
            if k == 0:
                data, suffix = base_bytes, ".jsonl"
            else:
                ns, hd = copy.deepcopy(nodes), dict(header)
                for _ in range(rng.choice([1, 1, 1, 2, 2, 3])):
                    if rng.random() < 0.75:
                        mut.structural(ns, hd)
                data = ("\n".join([dumps(hd)] + [dumps(x) for x in ns]) + "\n").encode()
                if rng.random() < 0.25:
                    data = mut.textual(data)
                data, suffix = container(rng, data)
                stats["gzip"] += suffix.endswith(".gz")
            proof = rd / ("m" + suffix)
            for old in rd.glob("m.jsonl*"):
                old.unlink()
            proof.write_bytes(data)
            pd = rng.random() < 0.3
            cd = rng.random() < 0.3
            stats["py_digest_runs"] += pd
            stats["cpp_digest_runs"] += cd
            py = A.run_py(d, p, proof, use_inp, digest_only=pd)
            cc = A.run_cpp(d, p, proof, use_inp, digest_only=cd, binary=cpp, timeout=120)
            if k:
                stats["mutants"] += 1
            files = {"d.txt": d.read_bytes(), "p.json": p.read_bytes(), "proof" + suffix: data}
            if use_inp:
                files["in.txt"] = inp.read_bytes()
            payload = {"py": py, "cpp": cc, "py_digest": pd, "cpp_digest": cd, "truth": truth,
                       "input": bool(use_inp), "mutant": k}
            if k == 0 and (py[0] != "accept" or cc[0] != "accept"):
                report("base_rejected", payload, files)
                break
            if py[0] in ("crash", "timeout") or cc[0] in ("crash", "timeout"):
                report("crash", payload, files)
                continue
            if py[0] != cc[0] or (py[0] == "accept" and py[1] != cc[1]):
                report("disagree", payload, files)
            for who, r in (("py", py), ("cpp", cc)):
                if r[0] == "accept" and r[1] != truth:
                    report(f"UNSOUND_{who}", payload, files)
            if k:
                if py[0] == "accept" or cc[0] == "accept":
                    stats["accepted_mutants"] += 1
                elif py[0] == cc[0] == "reject":
                    stats["rejected_both"] += 1
    stats["cpu_seconds_this_process"] = round(time.process_time() - cpu0, 1)
    print(json.dumps(stats), flush=True)
    (work / "stats.json").write_text(json.dumps(stats, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
