import json, sys
from collections import Counter
for path in sys.argv[1:]:
    recs = [json.loads(l) for l in open(path)]
    node = Counter(r['node']['status'] for r in recs)
    kids = Counter(k.get('status', 'static%d' % k['static']) for r in recs for k in r['children'])
    found_node = [r for r in recs if r['node']['status'] == 'found']
    found_kid = [r for r in recs if any(k.get('status') == 'found' for k in r['children'])]
    contra = [r for r in found_node if r['res'] == 1] + [r for r in found_kid if r['res'] == 2]
    unverified = [r for r in recs if r['node'].get('verified') is False or any(k.get('verified') is False for k in r['children'])]
    print(path.split('/')[-1], 'samples', len(recs), '| node:', dict(node), '| children:', dict(kids))
    print('   canonical matches solver', sum(r['canonical_matches_solver'] for r in recs), '| solver results', dict(Counter(r['res'] for r in recs)),
          '| contradictions', len(contra), '| unverified finds', len(unverified))
    print('   live groups min/median', min(r['live_groups'] for r in recs), sorted(r['live_groups'] for r in recs)[len(recs)//2],
          '| depth min/max', min(r['depth'] for r in recs), max(r['depth'] for r in recs),
          '| seconds total', round(sum(r['seconds'] for r in recs)), 'max', max(r['seconds'] for r in recs))
