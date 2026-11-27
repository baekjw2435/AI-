#!/usr/bin/env python3
"""Fix the cases of a replay comparison BEFORE anything is run.

usage: replay_pick.py SPLIT COUNT SALT SOURCES OUT.json [--exclude ID,ID] [--prefix f] [--only-sources 급,율]
  SPLIT    tune, final (the split of targets.json) or any (both: for solving, not for comparing methods)
  SOURCES  folder of prepared source certificates (replay_prep.py); only first moves whose handed-over vertex
           has one are eligible, so no new source has to be prepared
Eligible: targets of that split with no verified verdict yet (neither the earlier study nor results/summary.json).
They are sorted by sha256(SALT + id) and the first COUNT are taken: the choice depends on no result.
"""
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / 'guopsaem_root' / 'verifier_v3'))
from verify_v3 import ModelV3  # noqa: E402


def main():
    split, count, salt, sources, out = sys.argv[1:6]
    rest = sys.argv[6:]
    o = {rest[i]: rest[i + 1] for i in range(0, len(rest), 2)}
    exclude = set(o['--exclude'].split(',')) if '--exclude' in o else set()
    prefix = o.get('--prefix', 'f')
    only = set(o['--only-sources'].split(',')) if '--only-sources' in o else None
    m = ModelV3((HERE.parent / 'words_817.txt').read_bytes(), 817)
    doc = json.loads((HERE / 'targets.json').read_text(encoding='utf-8'))
    summ = json.loads((HERE / 'results' / 'summary.json').read_text(encoding='utf-8'))
    src = {m.vertex_of(d.name): d.name for d in sorted(Path(sources).iterdir())
           if (d / 'prep.json').exists() and (only is None or d.name in only)}
    eligible = []
    for t in doc['targets']:
        if (split != 'any' and t['split'] != split) or t['existing']['evidence'] == 'verified' or t['id'] in exclude:
            continue
        if any(e['decided'] for e in summ.get(t['id'], [])):
            continue
        v = m.vertex_of(t['words'][0][-1])
        if v in src:
            eligible.append((hashlib.sha256((salt + t['id']).encode('utf-8')).hexdigest(), t, src[v]))
    eligible.sort(key=lambda x: x[0])
    picked = eligible[:int(count)]
    width = max(2, len(str(len(picked))))
    cases = [{'name': f'{prefix}{i + 1:0{width}d}', 'id': t['id'], 'syllable': t['syllable'], 'word': t['words'][0], 'source': s,
              'split': t['split'], 'root_form': t['root_form'],
              'earlier_search_seconds': max((e['search_seconds_total'] for e in summ.get(t['id'], [])), default=0)}
             for i, (_, t, s) in enumerate(picked)]
    doc_out = {'rule': f'{split} split, no verified verdict, source prepared in {Path(sources).name}; sorted by sha256("{salt}" + id), first {count}',
               'eligible': len(eligible), 'eligible_by_source': {s: sum(1 for _, _, x in eligible if x == s) for s in sorted(set(src.values()))},
               'excluded': sorted(exclude), 'cases': cases}
    Path(out).write_text(json.dumps(doc_out, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(json.dumps({k: doc_out[k] for k in ('rule', 'eligible', 'eligible_by_source')}, ensure_ascii=False))
    for c in cases:
        print(' ', c['name'], c['id'], '→', c['source'], c['root_form'], f'(이전 탐색 {c["earlier_search_seconds"]:.0f}초)' if c['earlier_search_seconds'] else '')


if __name__ == '__main__':
    main()
