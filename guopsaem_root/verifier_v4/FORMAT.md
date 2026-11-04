# route-proof-v4

A route-proof-v4 certificate proves the game value of one position of the word-chain game
(one-way initial-sound rule, see `../verifier_v3/README_KO.md`). It is route-proof-v3 with
the per-node state removed. v3 stored, for every node, the vertex and the full count
vector (2,613 groups means 5,226 hex characters per line on the 3,436-word list). v4 stores
only results and moves. The verifier re-derives every state by replaying the moves from
the requested position, using the same reviewed model (`ModelV3` in
`../verifier_v3/verify_v3.py`).

## File

UTF-8 text with one JSON object per line, separated by LF (`\n`). A final LF is optional;
a CR before the LF is JSON whitespace and is allowed. Empty lines are invalid. The file
may be gzip-compressed (detected by the magic bytes `1f 8b`). Concatenated gzip members
are allowed. Trailing bytes that are not a gzip member, or a truncated member, are invalid.
Duplicate keys in any JSON object are invalid. "Integer" means a JSON number with no
fraction and no exponent: `true`, `false`, `1.0`, `1e0` and strings are rejected.

### Header (line 1)

```json
{"format":"route-proof-v4","groups":G,"vertices":N,"root":R}
{"format":"route-proof-v4","groups":G,"vertices":N,"root":R,"input_sha256":"<hex>"}
```

- `groups`, `vertices`: integers that must equal the group and vertex counts the verifier
  rebuilds from the dictionary (2,613 and 461 for `words_3436.txt`).
- `root`: integer id of the root node. It must equal the last id in the file.
- `input_sha256` (optional): SHA-256 of the numeric solver input. If present, the verifier
  must be given `--input`. The input must equal the input generated from
  dictionary + position, and its hash must match.
- No other keys are allowed.

### Node lines (lines 2 ..)

```json
{"id":i,"r":"W","m":[[group,child_id]]}
{"id":i,"r":"L","m":[[g1,c1],[g2,c2],...]}
{"id":i,"r":"L","m":[]}
{"id":i,"r":"W","m":[],"k":"static"}
```

- `id`: integers 0, 1, 2, ... in file order, with no gaps. The root is the last node.
- `r`: `"W"` or `"L"`, the value for the player to move in that node's state.
- `m`: list of moves `[group, child_id]` (two integers) with `0 <= group < G`,
  `0 <= child_id < id` and no group listed twice in a node.
- `k` (optional): only the value `"static"` is allowed. It claims the node's state is
  statically labelled; the verifier rejects the claim on a non-static state. The solver
  does not write it.
- No other keys are allowed (no `v`, no `c`).

The solver writes exactly `{"id":i,"r":"X","m":[[g,c],...]}` without spaces. Both
verifiers have a fast path for that exact form. Every other spelling goes through a full
JSON parser with the same rules.

## Checking (verify_v4.py, verify_v4 C++)

1. Rebuild the model from the dictionary (`ModelV3`): words, vertices, groups and
   populations. Replay the position (`initial_syllable`, `history`,
   `initial_used_words`) exactly as verify_v3 does. The root state is
   `normalize(root vertex, counts)`. Check `--input` and `input_sha256` when given.
2. Parse all node lines into compact arrays (result bits, move offsets, flat
   group/child pairs). Check the syntax rules above for every node, including nodes that
   are never reached.
3. Run an iterative depth-first search from the root (the last node). The root's state is
   the root state from step 1. When a node is expanded with state `S` at vertex `v`:
   - `normalize(v, S)` must equal `S` (v3's "canonically reduced" check). Its static
     label decides the rest:
   - static (label != -1): no moves, and `r` equals the label (1 = W, 0 = L);
   - not static: no `"k":"static"`. Every move group must be legal (`S[group] > 0` and
     `v` is one of the group's sources). If `r` is W: exactly one move, to a child
     whose `r` is L. If `r` is L: the moves list every legal group exactly once, and
     every child's `r` is W;
   - for every move, the child state is `model.child(v, S, group)` (one word of the group
     used, then normalized). On the first arrival at `child_id`, this derived state is
     recorded and the child is pushed for expansion. On every later arrival, the derived
     state must be byte-identical to the recorded one (same vertex, same 2,613 count
     bytes).
4. Report `verified: true` and the root result. Nodes never reached from the root carry
   no claim about any position. They are only syntax-checked and are counted in
   `unreached_nodes`. The solver never writes them.

State storage: the default keeps each recorded state zlib-compressed and compares by
decompressing it and comparing all bytes exactly (`state_storage: "zlib-exact"`).
`--digest-only` keeps a SHA-256 digest of each recorded state instead
(`state_storage: "sha256"`). This is the same digest equality that verify_v3 already
relies on, and it is opt-in.

## Why nothing is weaker than v3

v3 checked that each node's stated `(v, counts)` was canonical, and that each move's
`model.child(...)` equalled the stated state of the child line (by digest). v4 has no
stated states. A node's state is exactly the `model.child(...)` value that v3 compared
against, recorded on the first arrival. Every other edge into the node must produce the
identical state, where v3 compared it with the stated one. Static labels, W/L rules,
legality, duplicates, id order, root and header checks are the same. They are applied to
every node reachable from the root, which is every node the root's claim depends on. The
default comparison is exact; v3 compared digests.

## Size

Per node, v3 needs about 5.3 KB before gzip. v4 needs about 25 bytes plus about 10 bytes
per move. Measured sizes are in `README_KO.md` (test results).

## Tools

- Solver: `solver_v4 IN.txt ... --proof OUT.jsonl.gz --proof-format v4`. The default is
  still v3. See `solver_proof_v4.patch`.
- `verify_v4.py --dictionary D --expected-word-count N --position P.json --proof F [--input IN] [--digest-only]`
- `build/verify_v4` (from `verify_v4.cpp`), with the same flags and the same JSON result
  fields.
- `merge_root_v4.py`: combines certificates of ROOT's children into one certificate for
  ROOT.
