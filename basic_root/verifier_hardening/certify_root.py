#!/usr/bin/env python3
"""Prototype: certify that a position on the ROOT dictionary is the same canonical game
as the same position on a FULL dictionary, under the v2 reductions.

If normalize_FULL(position) equals normalize_ROOT(position) embedded into FULL's
numbering, every route-proof-v2 certificate for the ROOT position is (after renumbering)
a certificate for the FULL position: certificate nodes only contain ROOT edges, and the
reductions depend only on the multigraph, not on the numbering.  One normalization of the
full dictionary per research position is all that is needed.

Preconditions are checked, not assumed: ROOT words must be FULL words, and FULL must be
expressible in this edge model (no word may start with a dueum-changing syllable such as
라면/뉴스/리본; those need a two-variant source model and new reduction proofs).
"""
import argparse, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify_fast as vf  # noqa: E402


def certify(full_bytes, root_bytes, position):
    try:
        full = vf.Model(full_bytes, 0)
    except vf.VerificationError as exc:
        return {"certified": False, "reason": f"full dictionary not expressible: {exc}"}
    root = vf.Model(root_bytes, 0)
    missing = [w for w in root.words if w not in full.endpoints]
    if missing:
        return {"certified": False, "reason": "root words missing from full dictionary", "examples": missing[:10]}
    cur_f, cnt_f, _ = full.position(position)
    cur_r, cnt_r, _ = root.position(position)
    norm_f, st_f = full.normalize(cur_f, cnt_f)
    norm_r, st_r = root.normalize(cur_r, cnt_r)
    vmap = [full.vertex[s] for s in root.syllables]
    embedded = bytearray(full.G)
    for g, (s, t) in enumerate(root.edges):
        embedded[full.group[vmap[s], vmap[t]]] = norm_r[g]
    if st_f != -1 or st_r != -1:
        # a static root is certified by its label alone (both checkers recompute it)
        same = full.syllables[cur_f] == root.syllables[cur_r] and st_f == st_r
    else:
        same = full.syllables[cur_f] == root.syllables[cur_r] and bytes(embedded) == norm_f
    report = {"certified": same, "full_words": len(full.words), "root_words": len(root.words),
              "full_canonical_words": sum(norm_f), "root_canonical_words": sum(norm_r),
              "static_full": st_f, "static_root": st_r}
    if not same:
        diff = [(full.syllables[full.src[g]], full.syllables[full.dst[g]], norm_f[g], embedded[g])
                for g in range(full.G) if norm_f[g] != embedded[g]]
        report["differing_groups(src,dst,full,root)"] = diff[:12]
        report["differing_group_count"] = len(diff)
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--full", required=True)
    p.add_argument("--root", required=True)
    p.add_argument("--position", required=True)
    a = p.parse_args()
    r = certify(Path(a.full).read_bytes(), Path(a.root).read_bytes(),
                json.loads(Path(a.position).read_text(encoding="utf-8")))
    print(json.dumps(r, ensure_ascii=False, indent=1))
    sys.exit(0 if r["certified"] else 1)
