"""overlap.py A.bin B.bin ... : shared expanded positions between runs (sampled by fingerprint)."""
import sys, struct
sets = {}
for p in sys.argv[1:]:
    data = open(p, 'rb').read()
    allp, prov = set(), set()
    for i in range(0, len(data), 24):
        h0, h1, fl = struct.unpack_from('<QQQ', data, i)
        allp.add((h0, h1))
        if fl & 1: prov.add((h0, h1))
    sets[p.split('/')[-1][:-4]] = (allp, prov)
names = list(sets)
print('positions (sampled):', {n: len(sets[n][0]) for n in names})
print('row = earlier run X, column = later run Y: share of Y\'s positions seen in X / proven in X')
print(' ' * 18 + ''.join(f'{n[-11:]:>22}' for n in names))
for x in names:
    row = f'{x[-17:]:>18}'
    for y in names:
        if x == y: row += f'{"-":>22}'; continue
        ya = sets[y][0]
        seen = len(sets[x][0] & ya) / len(ya); proven = len(sets[x][1] & ya) / len(ya)
        row += f'{seen:>13.1%} /{proven:>6.1%}'
    print(row)
