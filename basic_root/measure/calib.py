import re, sys, math
rows = {}
for path in sys.argv[1:]:
    for line in open(path, encoding='utf-8'):
        m = re.search(r' (probe|long) (\S+) (R\S*) (win|loss|unknown) pn (\d+) dn (\d+)', line)
        if not m: continue
        _, tag, name, res, pn, dn = m.groups()
        rows.setdefault((path, name), []).append((res, int(pn), int(dn)))
agree = dis = 0; hard = []
for (path, name), rs in rows.items():
    final = [r for r in rs if r[0] != 'unknown']
    unk = [r for r in rs if r[0] == 'unknown']
    if not final or not unk: continue
    _, pn, dn = unk[0]
    lean = 'win' if dn > pn else 'loss'
    ok = lean == final[-1][0]
    agree += ok; dis += not ok
    s = math.log((dn + 1) / (pn + 1))
    hard.append((ok, round(s, 2), name, final[-1][0]))
print('agree', agree, 'disagree', dis)
for h in sorted(hard, key=lambda x: x[1]): print(*h)
