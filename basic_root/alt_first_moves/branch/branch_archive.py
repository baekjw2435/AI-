#!/usr/bin/env python3
"""Keep the results of a branch batch: run records in the repository, certificates as release attachments.

usage: branch_archive.py CASES.json WORK RESULTS_DIR TAG STAGING
  RESULTS_DIR/<name>/{pos.json,in.txt,run.json} for every case that was started, RESULTS_DIR/INDEX.json, and
  STAGING/TAG/<sha256>.v4.gz + MANIFEST.json (the upload job's format) for every accepted certificate.
A certificate is copied only if its sha256 is the one the verifier accepted.
"""
import hashlib
import json
from pathlib import Path
import shutil
import sys


def main():
    cases_path, work, res, tag, staging = sys.argv[1:6]
    work, res, g = Path(work), Path(res), Path(staging) / tag
    doc = json.loads(Path(cases_path).read_text(encoding='utf-8'))
    g.mkdir(parents=True, exist_ok=True)
    files, idx = {}, []
    for c in doc['cases']:
        d = work / c['name']
        run = json.loads((d / 'run.json').read_text(encoding='utf-8'))
        e = {'case': c['name'], 'words': c['group_words'], 'position': c['position'], 'method': c['method'],
             'hint': c.get('source') or c.get('guide_book')}
        if run.get('untried'):
            idx.append({**e, 'status': 'untried'})
            continue
        (res / c['name']).mkdir(parents=True, exist_ok=True)
        for f in ('pos.json', 'in.txt', 'run.json'):
            if (d / f).exists():
                shutil.copyfile(d / f, res / c['name'] / f)
        s = run['solver']
        e.update(allotted_seconds=run.get('allotted_seconds'), search_seconds=s.get('seconds'))
        if not run['accepted']:
            idx.append({**e, 'status': 'tried_unconfirmed', 'state_kept': run.get('state_kept'), 'pn': s.get('pn'), 'dn': s.get('dn')})
            continue
        assert all(run['acceptance'].values())
        sha = hashlib.sha256((d / 'proof.v4.gz').read_bytes()).hexdigest()
        assert sha == run['verify']['proof_sha256']
        name = f'{sha}.v4.gz'
        if not (g / name).exists():
            shutil.copyfile(d / 'proof.v4.gz', g / name)
        size = (g / name).stat().st_size
        files.setdefault(name, {'sha256': sha, 'bytes': size, 'certifies': []})['certifies'].append(
            f"{doc['batch']}/{c['name']} {' → '.join(c['position']['history'])}")
        idx.append({**e, 'status': 'confirmed', 'result_for_mover': run['result_for_mover'],
                    'verdict_for_player_of_word': 'lose' if run['result_for_mover'] == 'W' else 'win', 'store': 'release',
                    'release_tag': tag, 'asset': name, 'url': f'https://github.com/baekjw2435/AI-/releases/download/{tag}/{name}',
                    'uploaded_verified': None, 'proof_sha256': sha, 'proof_bytes': size, 'proof_nodes': s['proof_nodes'],
                    'position_sha256': run['verify']['position_sha256'], 'input_sha256': run['verify']['input_sha256'],
                    'acceptance': run['acceptance'], 'proof_seconds': s['emit_seconds'], 'verify_seconds': run['verify']['elapsed_seconds'],
                    'solver_sha256': run['solver_sha256'], 'source_proof_sha256': run.get('source_proof_sha256')})
    (g / 'MANIFEST.json').write_text(json.dumps({'release_tag': tag, 'files': files, 'file_count': len(files),
                                                 'total_bytes': sum(v['bytes'] for v in files.values())}, ensure_ascii=False, indent=1) + '\n',
                                     encoding='utf-8')
    (res / 'INDEX.json').write_text(json.dumps({'format': 'branch-archive-1', 'batch': doc['batch'], 'cases': idx}, ensure_ascii=False, indent=1) + '\n',
                                    encoding='utf-8')
    from collections import Counter
    print(json.dumps({'cases': len(idx), 'status': dict(Counter(x['status'] for x in idx)), 'certificates': len(files),
                      'bytes': sum(v['bytes'] for v in files.values())}))


if __name__ == '__main__':
    main()
