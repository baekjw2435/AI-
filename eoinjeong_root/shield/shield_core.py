#!/usr/bin/env python3
"""보호막 계산기의 바탕: 전체 사전으로 만든 음절 그래프와 보호막 0(평소 게임)의 판정.

음절 그래프
  상태 = '받은 음절' X. X를 받은 사람은 X 또는 X의 두음 음절(엔진 표준두음법칙, verify_v3.conv)로
  시작하는 단어를 낸다. 단어 w를 내면 상대가 w의 끝 음절을 받는다.
  단어 재사용은 이 그래프에서 따지지 않는다(짧은 공격 수순에서는 같은 단어가 두 번 필요하지 않음).

보호막 0의 판정(되짚기 분석)
  낼 단어가 없으면 0수 패. 지는 음절로 보내는 단어가 있으면 승(가장 빠른 것), 모든 단어가 이기는 음절로
  가면 패(가장 늦은 것). 끝까지 정해지지 않는 음절은 순환(루트 쪽)이다.
  승 음절에서 지는 음절로 보내는 단어 w의 '깊이' = 1 + (w의 끝 음절의 패 수). 공격 목록과 같은 정의.

보호막 상한
  thr(w) = cont(w의 끝 음절) = 그 음절(두음 포함)로 시작하는 사전 단어 수.
  단어 w는 지금 보호막이 thr(w) 이하일 때만 낼 수 있다.
"""
import collections
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / 'guopsaem_root' / 'verifier_v3'))
from verify_v3 import conv  # noqa: E402

DICT = HERE / 'source' / '표준사전_어인정_전체단어.txt'
ATTACK = HERE / 'source' / '공격단어_목록.txt'


class Graph:
    def __init__(self, dict_path=DICT, words=None):
        if words is None:
            words = [w.strip() for w in Path(dict_path).read_text(encoding='utf-8-sig').splitlines() if w.strip()]
        self.words = list(words)
        self.by_first = collections.defaultdict(list)
        for w in self.words:
            self.by_first[w[0]].append(w)
        self.first_count = {k: len(v) for k, v in self.by_first.items()}

    def firsts(self, x):
        a = conv(x)
        return [x] + ([a] if a and a != x else [])

    def cont(self, x):
        """이을 수 있는 단어 수 = 이 음절로 끝나는 단어를 낼 수 있는 보호막의 상한."""
        return sum(self.first_count.get(f, 0) for f in self.firsts(x))

    def moves(self, x):
        """x를 받았을 때 낼 수 있는 모든 단어."""
        out = []
        for f in self.firsts(x):
            out += self.by_first.get(f, [])
        return out

    def succ(self, x):
        """x에서 갈 수 있는 끝 음절과 그 단어들 {끝 음절: [단어]}."""
        d = collections.defaultdict(list)
        for w in self.moves(x):
            d[w[-1]].append(w)
        return d


def retrograde(g, fixed=None):
    """보호막 0의 판정. fixed = {음절: 'W'|'L'}이면 그 음절은 그 값으로 고정(루트 결과를 넣을 때).
    반환: {음절: ('W'|'L', 수)}  (고정한 음절은 수 None). 목록에 없는 음절은 순환(미정)."""
    nodes = set(w[-1] for w in g.words) | set(fixed or {})
    succ = {x: set(g.succ(x)) for x in nodes}
    pred = collections.defaultdict(set)
    for x, ys in succ.items():
        for y in ys:
            pred[y].add(x)
    val, left = {}, {x: len(ys) for x, ys in succ.items()}
    q = collections.deque()
    for x, v in (fixed or {}).items():
        val[x] = (v, None)
        q.append(x)
    for x in nodes:
        if x not in val and left[x] == 0:
            val[x] = ('L', 0)
            q.append(x)
    while q:
        y = q.popleft()
        vy, dy = val[y]
        for x in pred[y]:
            if x in val:
                continue
            if vy == 'L':
                val[x] = ('W', None if dy is None else dy + 1)
                q.append(x)
            else:
                left[x] -= 1
                if left[x] == 0:
                    ds = [val[z][1] for z in succ[x]]
                    val[x] = ('L', None if any(d is None for d in ds) else max(ds) + 1)
                    q.append(x)
    return val


def static_values(g, fixed=None):
    """보호막 0의 판정을 ModelV3(verify_v3.py)와 같은 정리로 계산한다.
    꼭짓점 = 받은 음절이 낼 수 있는 첫 음절의 집합, 묶음 = (낼 수 있는 꼭짓점들, 끝 꼭짓점) 별 단어 수.
    1) 한 꼭짓점에서만 낼 수 있는 왕복 쌍 u→v, v→u는 적은 쪽만큼 서로 지움  2) 한 꼭짓점의 제자리 단어는 2로 나눈 나머지
    3) 최소 고정점: 지는 후속이 있으면 승, 모든 후속이 승이면 제자리 단어가 남았을 때 승·없으면 패
       (여러 꼭짓점에서 낼 수 있는 제자리 단어가 있으면 미정).
    수(깊이): 승 = 1 + 가장 빠른 패 후속, 패 = 1 + 가장 늦은 승 후속, 제자리 단어로 이기면 2 + 가장 늦은 승 후속.
    fixed = {받은 음절: 'W'|'L'}: 그 음절의 꼭짓점을 그 값으로 고정(루트 결과).
    반환: (값 {받은 음절: ('W'|'L', 수 또는 None)}, 꼭짓점 정보)."""
    import heapq
    starts = set(g.by_first)
    recv = set(w[-1] for w in g.words) | set(fixed or {})

    def key(x):
        return tuple(sorted(f for f in g.firsts(x) if f in starts))
    vkey = {x: key(x) for x in recv}
    keys = sorted(set(vkey.values()))
    vid = {k: i for i, k in enumerate(keys)}
    src_of_first = collections.defaultdict(list)
    for i, k in enumerate(keys):
        for f in k:
            src_of_first[f].append(i)
    cnt = collections.Counter()
    for w in g.words:
        srcs = tuple(src_of_first[w[0]])
        if not srcs:
            continue
        cnt[(srcs, vid[key(w[-1])])] += 1
    # 1) 왕복 쌍  2) 제자리
    for (srcs, t), c in list(cnt.items()):
        if len(srcs) == 1 and srcs[0] < t:
            r = ((t,), srcs[0])
            if r in cnt:
                m = min(cnt[(srcs, t)], cnt[r])
                cnt[(srcs, t)] -= m
                cnt[r] -= m
    n = len(keys)
    succ = [set() for _ in range(n)]
    loop1 = [0] * n
    shloop = [False] * n
    for (srcs, t), c in cnt.items():
        if c <= 0:
            continue
        for s in srcs:
            if s == t:
                if len(srcs) == 1:
                    loop1[s] = c % 2
                else:
                    shloop[s] = True
            else:
                succ[s].add(t)
    pred = [set() for _ in range(n)]
    for s in range(n):
        for t in succ[s]:
            pred[t].add(s)
    val = [None] * n
    left = [len(succ[s]) for s in range(n)]
    maxw = [-1] * n
    heap = []
    fixed_v = {}
    for x, v in (fixed or {}).items():
        fixed_v[vid[vkey[x]]] = v

    def settle(s, lab, d):
        val[s] = (lab, d)
        heapq.heappush(heap, (d if d is not None else 10 ** 9, s))
    for s, v in fixed_v.items():
        settle(s, v, None)
    for s in range(n):
        if val[s] is None and left[s] == 0 and not shloop[s]:
            settle(s, 'W', 1) if loop1[s] else settle(s, 'L', 0)
    while heap:
        _, t = heapq.heappop(heap)
        lab, d = val[t]
        for s in pred[t]:
            if val[s] is not None:
                continue
            if lab == 'L':
                settle(s, 'W', None if d is None else d + 1)
            else:
                left[s] -= 1
                maxw[s] = 10 ** 9 if d is None else max(maxw[s], d)
                if left[s] == 0 and not shloop[s]:
                    big = maxw[s] >= 10 ** 9
                    if loop1[s]:
                        settle(s, 'W', None if big else maxw[s] + 2)
                    else:
                        settle(s, 'L', None if big else maxw[s] + 1)
    out = {x: val[vid[vkey[x]]] for x in recv if val[vid[vkey[x]]] is not None}
    return out, {'vid': vid, 'vkey': vkey, 'keys': keys, 'val': val}


class StaticModel:
    """보호막 0 판정(값만)을 '쓴 단어'를 빼 가며 빠르게 다시 계산하기 위한 모형. static_values와 같은 규칙.
    꼭짓점·묶음은 한 번만 만들고, labels(removed)는 묶음 개수에서 removed 단어만 빼고 다시 판정한다."""

    def __init__(self, g):
        self.g = g
        starts = set(g.by_first)
        self.recv = set(w[-1] for w in g.words)
        kc = {}

        def key(x):
            k = kc.get(x)
            if k is None:
                k = kc[x] = tuple(sorted(f for f in g.firsts(x) if f in starts))
            return k
        self.key = key
        keys = sorted({key(x) for x in self.recv})
        self.vid = {k: i for i, k in enumerate(keys)}
        src_of_first = collections.defaultdict(list)
        for i, k in enumerate(keys):
            for f in k:
                src_of_first[f].append(i)
        srcs_t = {f: tuple(v) for f, v in src_of_first.items()}
        self.word_group = {}
        self.count = collections.Counter()
        for w in g.words:
            srcs = srcs_t.get(w[0])
            if not srcs:
                continue
            kk = key(w[-1])
            t = self.vid.get(kk)
            if t is None:
                t = self.vid[kk] = len(self.vid)
            grp = (srcs, t)
            self.word_group[w] = grp
            self.count[grp] += 1
        self.n = len(self.vid)
        self.single = {grp for grp in self.count if len(grp[0]) == 1}
        self.loop = {grp for grp in self.count if grp[1] in grp[0]}
        self.paired = {grp for grp in self.single if grp[0][0] != grp[1] and ((grp[1],), grp[0][0]) in self.count}
        self.cache = {}
        self.recv_v = {x: self.vid[key(x)] for x in self.recv}

    def sensitive(self, w):
        """이 단어를 빼면 판정이 바뀔 수 있나: 제자리 묶음, 왕복 쌍 묶음, 12개 이하 묶음."""
        grp = self.word_group.get(w)
        return grp is not None and (grp in self.loop or grp in self.paired or self.count[grp] <= 12)

    def effective(self, removed):
        """판정을 바꿀 수 있는 것만 남긴다: 제자리·왕복 쌍 묶음의 단어, 그리고 다 써서 0이 된 묶음의 단어."""
        by = collections.Counter(self.word_group[w] for w in removed if w in self.word_group)
        return frozenset(w for w in removed if w in self.word_group and (
            self.word_group[w] in self.loop or self.word_group[w] in self.paired
            or by[self.word_group[w]] >= self.count[self.word_group[w]]))

    def _vertex_struct(self, v, rc):
        """꼭짓점 v의 (후속 집합, 단독 제자리 홀짝, 공유 제자리 있음) — rc: 묶음 → 정리된 개수."""
        succ, loop1, shloop = set(), 0, False
        for grp in self.groups_by_src[v]:
            c = rc(grp)
            if c <= 0:
                continue
            srcs, t = grp
            if t == v:
                if len(srcs) == 1:
                    loop1 = c % 2
                else:
                    shloop = True
            else:
                succ.add(t)
        return succ, loop1, shloop

    def _base(self):
        """쓴 단어가 없을 때의 정리된 개수·꼭짓점 구조·판정(한 번만)."""
        if hasattr(self, 'val0'):
            return
        self.groups_by_src = [[] for _ in range(self.n)]
        for grp in self.count:
            for s_ in grp[0]:
                self.groups_by_src[s_].append(grp)
        self.rc0 = dict(self.count)
        for grp in self.paired:
            s_, t = grp[0][0], grp[1]
            if s_ < t:
                r = ((t,), s_)
                m = min(self.count[grp], self.count[r])
                self.rc0[grp] = self.count[grp] - m
                self.rc0[r] = self.count[r] - m
        st = [self._vertex_struct(v, self.rc0.__getitem__) for v in range(self.n)]
        self.succ0 = [x[0] for x in st]
        self.loop0 = [x[1] for x in st]
        self.shl0 = [x[2] for x in st]
        self.pred0 = [set() for _ in range(self.n)]
        for v in range(self.n):
            for t in self.succ0[v]:
                self.pred0[t].add(v)
        self.val0 = self._fixpoint(range(self.n), self.succ0, self.loop0, self.shl0, {})
        self.lcnt0 = [sum(1 for t in self.succ0[v] if self.val0[t] == 'L') for v in range(self.n)]

    def _fixpoint(self, verts, succ, loop1, shloop, fixed):
        """verts 안의 판정을 최소 고정점으로. verts 밖은 fixed(없으면 self.val0)의 값을 그대로 쓴다."""
        verts = list(verts)
        inside = set(verts)
        val = {} if fixed is None else dict(fixed)
        lab = {}
        outside = (lambda t: self.val0[t]) if hasattr(self, 'val0') else (lambda t: None)

        def get(t):
            return lab.get(t) if t in inside else outside(t)
        changed = True
        while changed:
            changed = False
            for v in verts:
                if v in lab:
                    continue
                ss = succ[v] if isinstance(succ, list) else succ(v)
                vals = [get(t) for t in ss]
                if 'L' in vals:
                    lab[v] = 'W'
                    changed = True
                elif all(x == 'W' for x in vals) and not (shloop[v] if isinstance(shloop, list) else shloop(v)):
                    lab[v] = 'W' if (loop1[v] if isinstance(loop1, list) else loop1(v)) else 'L'
                    changed = True
        if not hasattr(self, 'val0'):
            return [lab.get(v) for v in range(self.n)]
        return lab

    def delta(self, removed=frozenset()):
        """쓴 단어 removed를 뺐을 때 판정이 바뀔 수 있는 꼭짓점들의 새 판정 {꼭짓점: 'W'|'L'|None}.
        바뀐 꼭짓점과, 그 판정에 기대는 조상만 다시 판정한다(그 밖은 판정이 바뀌지 않으므로 정확)."""
        self._base()
        removed = self.effective(frozenset(removed))
        if removed in self.cache:
            return self.cache[removed]
        if not removed:
            self.cache[removed] = {}
            return {}
        by = collections.Counter(self.word_group[w] for w in removed)
        mc = {g: self.count[g] - k for g, k in by.items()}
        rc = {}
        for g in list(mc):
            rc[g] = mc[g]
            if g in self.paired:
                r = ((g[1],), g[0][0])
                cg, cr = mc[g], mc.get(r, self.count[r])
                rc[g], rc[r] = max(0, cg - cr), max(0, cr - cg)
        for g in list(rc):
            if g in self.paired:
                r = ((g[1],), g[0][0])
                if r not in rc:
                    cg, cr = mc.get(g, self.count[g]), self.count[r]
                    rc[g], rc[r] = max(0, cg - cr), max(0, cr - cg)

        def rcf(g):
            return rc.get(g, self.rc0[g])
        affected = {s_ for g in rc for s_ in g[0]}
        new = {}
        for v in affected:
            st = self._vertex_struct(v, rcf)
            if st != (self.succ0[v], self.loop0[v], self.shl0[v]):
                new[v] = st
        if not new:
            self.cache[removed] = {}
            return {}

        def succ(v):
            return new[v][0] if v in new else self.succ0[v]

        def preds(v):
            return self.pred0[v] | newpred.get(v, set())
        newpred = collections.defaultdict(set)
        for v, st in new.items():
            for t in st[0] - self.succ0[v]:
                newpred[t].add(v)
        # U: 판정이 바뀔 수 있는 꼭짓점 = 바뀐 꼭짓점과 그 조상. 단, 원래 승이고 U 밖의 원래 패 후속이 남아 있는
        # 꼭짓점은 승 그대로(safe 개수가 0이 되면 그때 U에 넣는다).
        U, frontier, safe, UL = set(), [], {}, []

        def add(v):
            stack = [v]
            while stack:
                v = stack.pop()
                if v in U:
                    continue
                U.add(v)
                frontier.append(v)
                if self.val0[v] == 'L':
                    UL.append(v)
                    for p in preds(v):
                        if p in safe and p not in U and v in succ(p):
                            safe[p] -= 1
                            if safe[p] == 0:
                                stack.append(p)
        for v in new:
            add(v)
        while frontier:
            v = frontier.pop()
            for p in preds(v):
                if p in U or v not in succ(p):
                    continue
                if self.val0[p] == 'W':
                    if p not in safe:
                        if p in new:
                            safe[p] = sum(1 for t in succ(p) if t not in U and self.val0[t] == 'L')
                        else:   # 원래 패 후속 수에서 U 안의 것만 뺀다(U는 작다)
                            sp = self.succ0[p]
                            safe[p] = self.lcnt0[p] - sum(1 for t in UL if t in sp)
                    if safe[p] > 0:
                        continue
                add(p)
        lab = self._solve_inside(U, succ, preds,
                                 lambda v: new[v][1] if v in new else self.loop0[v],
                                 lambda v: new[v][2] if v in new else self.shl0[v])
        self.cache[removed] = lab
        return lab

    def _solve_inside(self, U, succ, preds, loop1, shloop):
        """U 안의 최소 고정점(되짚기). U 밖은 원래 판정(val0) 그대로. 반환 {꼭짓점: 'W'|'L'|None} (U 안만)."""
        lab = {v: None for v in U}
        left, blocked, q = {}, {}, []
        for v in U:
            n_in, hasL, unk = 0, False, False
            for t in succ(v):
                if t in U:
                    n_in += 1
                else:
                    o = self.val0[t]
                    if o == 'L':
                        hasL = True
                    elif o is None:
                        unk = True
            left[v] = n_in
            blocked[v] = unk or shloop(v)
            if hasL:
                lab[v] = 'W'
                q.append(v)
            elif n_in == 0 and not blocked[v]:
                lab[v] = 'W' if loop1(v) else 'L'
                q.append(v)
        while q:
            t = q.pop()
            for p in preds(t):
                if p not in U or lab[p] is not None or t not in succ(p):
                    continue
                if lab[t] == 'L':
                    lab[p] = 'W'
                    q.append(p)
                else:
                    left[p] -= 1
                    if left[p] == 0 and not blocked[p]:
                        lab[p] = 'W' if loop1(p) else 'L'
                        q.append(p)
        return lab

    def label(self, x, removed=frozenset()):
        """받은 음절 x의 보호막 0 판정 'W'|'L'|None (쓴 단어 removed 반영)."""
        i = self.recv_v.get(x)
        if i is None:
            return None
        d = self.delta(removed)
        return d[i] if i in d else self.val0[i]

    def labels(self, removed=frozenset()):
        """{받은 음절: 'W'|'L'} 전체(정해지지 않은 음절은 없음). 검사용."""
        d = self.delta(removed)
        out = {}
        for x, i in self.recv_v.items():
            v = d[i] if i in d else self.val0[i]
            if v is not None:
                out[x] = v
        return out


def read_attack_list(path=ATTACK):
    out, cur = [], None
    for line in Path(path).read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        m = re.match(r'^\[(.+)\]$', line)
        if m:
            cur = m.group(1)
            continue
        m = re.match(r'^깊이\s*(\d+)\s*:\s*(.*)$', line)
        if m:
            out += [(cur, int(m.group(1)), w.strip()) for w in m.group(2).split(',') if w.strip()]
    return out
