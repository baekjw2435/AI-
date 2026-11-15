#!/usr/bin/env python3
"""Guide files for solver_v5_table: one book of the existing route map as a move-selection hint.

usage: make_guide.py SITE_DIR BOOK_ID OUT_DIR
  SITE_DIR  files of the existing route map (model.json, manifest.json, t/<book>/NN.wasm), read with the Artifact tool
  OUT_DIR   gets model.txt (the site model in cert2site's numeric form, the map solver group -> site group, and one
            more line: solver vertex -> site vertex) and table.bin (dump_book.js), plus guide.json

The solver's numbering is ModelV3's (solve_common / ModelV3.numeric_input); site_model.SiteMap checks, word for word,
that both models are the same game on the 817-word list and gives the two maps.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'site'))
import site_model  # noqa: E402

ENGINE = HERE.parents[1] / 'route-site' / 'site-engine.js'


def main():
    site_dir, book, out = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    out.mkdir(parents=True, exist_ok=True)
    sm = site_model.load(site_dir / 'model.json')
    sm.write_numeric(out / 'model.txt')
    n = len(sm.m.keys)
    with open(out / 'model.txt', 'a') as f:
        f.write(' '.join(str(sm.v3v[v]) for v in range(n)) + '\n')
    r = subprocess.run(['node', str(HERE / 'dump_book.js'), str(site_dir), book, str(out / 'table.bin'), str(ENGINE)],
                       capture_output=True, text=True, check=True)
    info = json.loads(r.stdout)
    sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
    info.update(model_json_sha256=sha(site_dir / 'model.json'), manifest_sha256=sha(site_dir / 'manifest.json'),
                engine_sha256=sha(ENGINE), model_txt_sha256=sha(out / 'model.txt'), table_bin_sha256=sha(out / 'table.bin'),
                solver_vertices=n, solver_groups=len(sm.g3))
    (out / 'guide.json').write_text(json.dumps(info, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(json.dumps(info, ensure_ascii=False))


if __name__ == '__main__':
    main()
