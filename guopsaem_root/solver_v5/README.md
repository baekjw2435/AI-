# solver_v5

Same search as `solver_v4`, fewer CPU cycles per node. Same command line, same JSON output, same
`route-proof-v3` certificates. For single-thread runs with the same options, every non-timing field
of the JSON output and the certificate file are identical to solver_v4's (checked, see below).

## What changed

1. **In-place state with an undo log.** solver_v4 copied the whole search state into the next depth
   for every descent (`materialize`), including one 64-byte successor row per core vertex. With
   about 243–461 vertices this row copy took about 19 % of all instructions (callgrind, -O3).
   v5 keeps one state per searcher, changes it in place when descending (`apply_child`) and
   restores it from an undo record when returning (`revert_child`): the previous count of every
   changed group, the at most MAXSRC modified successor rows and loop flags, the core, the
   current vertex and the hash. The children list of a node is computed before descending and
   is still valid after the restore, because the restore is exact.
2. **Lazily masked successor rows.** A row may keep bits of vertices that already left the core;
   every use masks it with the current core (`& P.core`): reachability, the cascade's successor
   counts, the seed test, the move-count heuristic. So a core shrink no longer rewrites every
   row. `--selfcheck` compares masked rows.
3. **The two breadth-first searches in `gen_child` read rows directly.** A modified row
   (`child_mods`) differs from `P.succ[u]` only by the bit of the target `w`, and `w` is in the
   visited set from the first step of both searches, so that bit is discarded either way. The
   lookup of modified rows per visited vertex (about 6 % of instructions) is gone there; the
   cascade, which can test `w` itself, still uses the modified rows.
4. **Single-source fast path** in the hash update and in the zeroing of dropped groups.
5. **Bug fix in certificate emission.** When a node evicted from the transposition table had to
   be re-solved, solver_v4 copied the state field by field and forgot the shared-loop flags.
   That could only make emission fail or produce a certificate that the verifier rejects; v5
   copies the whole state.

## Checks

- Identical JSON (all fields except timing) for v4 and v5 on 9 real positions at 200,000 and
  2,000,000 nodes (면's first moves, 락, 면, 탁).
- `--selfcheck 1` (every child and every state recomputed by the reference canonicalization)
  for 60 s on three of 면's first moves: no mismatch.
- `solver_v4/tests/random_test.py` with v5: 300 random small dictionaries, certificates
  accepted by verify_v3 and equal to brute force.
- 817-word regression (running): syllables solved in the 817 study are solved again by v4 and
  v5 on the 817 list (the v3 model is the same game there). So far every one gives identical
  JSON, byte-identical certificates accepted by verify_v3, the SOLVED_KO.md result and even the
  same certificate size as in the 817 study.

## Speed

About 1.3x faster than v4 on 2,000,000-node runs (c_9 8.3 s vs 11.4 s, 락 7.7 s vs 10.5 s,
면 7.7 s vs 10.1 s, on a machine shared with other jobs).
