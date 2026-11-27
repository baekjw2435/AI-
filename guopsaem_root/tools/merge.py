import sys, collections, json
sys.path.insert(0, '/home/user/AI-/basic_root/verifier/route-verifier-v2')
from verify import dueum
import os; U = os.path.dirname(os.path.abspath(__file__)) + '/../source/'
f1 = U + 'list1_syllable_words.txt'; f2 = U + 'list2_syllable_words.txt'; f3 = U + 'list3_pairs.txt'
syl = {}; order = []; words = []; src = collections.defaultdict(set); bad = []
for tag, f in (('1', f1), ('2', f2)):
    for ln, line in enumerate(open(f, encoding='utf-8-sig'), 1):
        line = line.strip()
        if not line: continue
        s, rest = line.split(':', 1); s = s.strip()
        ws = [w.strip() for w in rest.split(',') if w.strip()]
        assert s not in syl, s
        syl[s] = (tag, ws); order.append(s)
        for w in ws:
            words.append(w); src[w].add(tag)
            if w[0] != s and w[0] != dueum(s): bad.append((tag, ln, s, w))
pairs = []
for ln, line in enumerate(open(f3, encoding='utf-8-sig'), 1):
    line = line.strip()
    if not line: continue
    ws = [w.strip() for w in line.split(',') if w.strip()]
    assert len(ws) == 2, line
    pairs.append(ws)
    for w in ws: words.append(w); src[w].add('3')
allw = sorted(set(words))
nonhangul = [w for w in allw if not all(0xAC00 <= ord(c) <= 0xD7A3 for c in w)]
print('syllables f1', sum(1 for s in syl if syl[s][0]=='1'), 'f2', sum(1 for s in syl if syl[s][0]=='2'))
print('word mentions', len(words), 'unique', len(allw), 'nonhangul', nonhangul)
print('f1/f2 words not under own start syllable:', bad[:20], len(bad))
only3 = [w for w in allw if src[w] == {'3'}]
print('words only in file3:', len(only3), only3[:40])
# file3 pair sanity: a ends where b starts and vice versa
odd = [p for p in pairs if not (dueum(p[0][-1]) == p[1][0] and dueum(p[1][-1]) == p[0][0])]
print('pairs not forming a 2-cycle:', len(odd), odd[:10])
ps = set(tuple(p) for p in pairs); print('pairs w/o reverse:', [p for p in ps if (p[1], p[0]) not in ps][:10])
# completeness: every word starting with normal syllable s listed under s in f1/f2 ?
listed = collections.defaultdict(set)
for s, (t, ws) in syl.items():
    for w in ws: listed[s].add(w)
miss = collections.defaultdict(list)
for w in allw:
    s = w[0]
    if s in syl and w not in listed[s]: miss[s].append(w)
print('words whose start syllable has an entry but are missing from it:', dict(list(miss.items())[:30]), sum(map(len, miss.values())))
nostart = sorted({w[0] for w in allw} - set(syl))
print('start syllables without an entry:', nostart)
dstart = sorted(w for w in allw if dueum(w[0]) != w[0])
print('dueum-changing start words:', len(dstart), dstart)
json.dump({'syl': syl, 'order': order, 'pairs': pairs, 'words': allw}, open(sys.argv[1], 'w'), ensure_ascii=False)
