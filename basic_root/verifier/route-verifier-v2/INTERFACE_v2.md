# New engine proof interface v2

2026-10-28. The dictionary, numeric input, grouped-word mapping, exact literal
history validation and full-state identity are unchanged from `INTERFACE.md`.
All nodes use the native sorted syllable/group numbering reconstructed from the
original dictionary. Legacy website numbering must be explicitly converted.

The certificate header has `format: "route-proof-v2"`. Node fields remain
`id`, `v`, `c`, `r`, `m`. An optional `k: "static"` is descriptive; the verifier
recomputes whether a node is static and does not trust that label.

## Canonicalization

1. Remove disjoint reciprocal edge pairs and pairs of self-loops; remove edges
   whose source is unreachable from the current vertex, as in v1.
2. Independently classify vertices by the following least fixed point. Start
   with all vertices unknown. Ignore the possible single self-loop when
   inspecting **nonloop** successors. An unknown vertex is W if it has a known
   L nonloop successor. If all its nonloop successors are W (including an empty
   successor set), it is W when it has a self-loop, otherwise L. A vertex not
   classified by these rules remains unknown. Assigned labels do not change.
3. If the current vertex is classified, retain the exact counts from step 1.
   This is a **static state** and its certificate node must have `m: []` and
   `r` equal to the independently computed label. This includes W leaves whose
   witness is a loop or a descending-rank move; the verifier checks the whole
   fixed-point condition itself.
4. If the current vertex is unknown, keep only edges in the unknown region
   reachable from it by unknown-to-unknown edges. Outgoing edges to classified
   vertices necessarily lead to W positions and can be discarded. The counts
   of this pruned unknown core form the canonical state.

The preservation theorem, self-loop qualification, raw-game comparisons and
limits of this reduction are in the accompanying model-audit material. Static
vertex labels are local to the current remaining-count vector. They must never
be copied from another position.

## Proof verification

The root must match canonicalization of the **raw dictionary minus the exact
history**, not a cache key. Every node is canonically reduced and within the
dictionary's word multiplicities. Static nodes are validated by recomputing
step 2. For every nonstatic W node, exactly one legal group leads to an L node.
For every nonstatic L node, every legal reduced group appears exactly once and
leads to W. Each child must equal consuming one word in that group, moving to
its target, and applying the complete v2 canonicalization. Children have lower
IDs; IDs are contiguous from zero; the final node is the root.

Unknown results and legacy hash lookups cannot be proof leaves. A legacy cache
may suggest a choice for certificate construction, but the resulting entire
certificate must pass this independent checker before its result is accepted.
