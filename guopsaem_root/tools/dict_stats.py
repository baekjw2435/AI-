#!/usr/bin/env python3
"""Size of every start position of a word list after the model's simplification (ModelV3.normalize).

usage: python3 tools/dict_stats.py WORDS.txt N SYLLABLES.txt OUT.json

For each start syllable s (first presentation: no word used, the receiver of s moves first) it records
the receiver's number of first words, the static result if the simplification already decides it
(W: receiver wins, L: receiver loses), and otherwise the size of the remaining core (words, groups,
vertices). Start syllables whose simplified positions are identical share one 'position' id, so each
distinct position needs to be solved only once.
"""
import collections
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'verifier_v3'))
from verify_v3 import ModelV3  # noqa: E402


def main():
    words_path, n, syl_path, out = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
    model = ModelV3(Path(words_path).read_bytes(), n)
    syllables = Path(syl_path).read_text(encoding='utf-8').split()
    rows, ids = [], {}
    for s in syllables:
        cur, counts, _ = model.position({'initial_syllable': s, 'history': []})
        core, static = model.normalize(cur, counts)
        first = sum(counts[g] for g in model.available[cur])
        row = {'syllable': s, 'vertex': model.names[cur], 'first_words': first,
               'static': {1: 'W', 0: 'L'}.get(static)}
        if static == -1:
            key = hashlib.sha256(bytes([cur >> 8, cur & 255]) + core).hexdigest()
            ids.setdefault(key, len(ids))
            groups = [g for g, c in enumerate(core) if c]
            verts = {model.edges[g][1] for g in groups} | {v for g in groups for v in model.edges[g][0]}
            row.update(position=ids[key], core_words=sum(core), core_groups=len(groups), core_vertices=len(verts))
        rows.append(row)
    st = collections.Counter(r['static'] for r in rows)
    open_rows = [r for r in rows if not r['static']]
    sizes = collections.Counter((r['core_words'], r['core_groups'], r['core_vertices']) for r in open_rows)
    summary = {
        'dictionary': Path(words_path).name, 'words': len(model.words), 'vertices': len(model.keys),
        'groups': len(model.edges), 'shared_groups': sum(model.shared),
        'start_syllables': len(rows), 'static_W': st['W'], 'static_L': st['L'], 'open': len(open_rows),
        'distinct_open_positions': len(ids),
        'core_sizes_most_common': [{'words': w, 'groups': g, 'vertices': v, 'syllables': c}
                                   for (w, g, v), c in sizes.most_common(8)],
        'core_words_min_max': [min((r['core_words'] for r in open_rows), default=0),
                               max((r['core_words'] for r in open_rows), default=0)],
    }
    Path(out).write_text(json.dumps({'summary': summary, 'rows': rows}, ensure_ascii=False, indent=1) + '\n',
                         encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
