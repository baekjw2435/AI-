#!/bin/bash
# make_bundle.sh OUTDIR [START ...]
# Builds a complete bundle in OUTDIR: tables from the verified proofs (only those of START syllables, if given),
# then the engine files, catalog, readable lines and README. Needs gcc with zlib, python3 with numpy, node.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd); BOOK=$(dirname "$HERE")
OUT=$1; shift
mkdir -p "$OUT"
gcc -O2 -o "$OUT/../proof2tab" "$HERE/proof2tab.c" -lz
python3 -I "$HERE/build_book.py" "$OUT/../proof2tab" "$OUT" "$@"
cp "$BOOK/engine.js" "$BOOK/index.html" "$BOOK/test_book.js" "$OUT/"
(cat "$BOOK/engine.js"; printf '\nexport default RouteBook;\nexport { RouteBook };\n') > "$OUT/engine.mjs"
node "$HERE/make_catalog.js" "$OUT"
node "$HERE/make_summary.js" "$OUT"
node "$HERE/make_readme.js" "$OUT"
mkdir -p "$OUT/build" && cp "$HERE"/*.c "$HERE"/*.py "$HERE"/*.js "$HERE"/*.sh "$OUT/build/"
echo "bundle ready: $OUT (build metadata in $OUT/_proofs.json is not part of the bundle)"
