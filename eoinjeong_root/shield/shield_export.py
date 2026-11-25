#!/usr/bin/env python3
"""C 엔진(engine/shield_engine.c)이 읽는 모형 파일을 만든다. 계산 규칙은 shield_calc.py(파이썬 엔진)와 같다.

모형 파일(텍스트, 숫자만):
  단어      : 사전 단어(쓴 단어를 뺀 것)를 문자열 순으로 정렬한 번호. 기록 여부, 묶음 번호, 루트 모형의 단어 번호.
  음절      : 받은 음절마다 cont(전체 사전), 루트 확정 결과, 순환 음절 여부, 정적 꼭짓점, 루트 모형 꼭짓점,
              낼 수 있는 단어를 끝 음절별로(파이썬 Calc.succ와 같은 순서).
  정적 모형 : StaticModel의 묶음(시작 꼭짓점들, 끝 꼭짓점, 개수, 왕복 짝), 기본 정리 개수 rc0,
              꼭짓점마다 succ0·loop0·shl0·pred0·val0·lcnt0.
  루트 모형 : ModelV3(621단어)의 묶음과 단어별 묶음(site/solver/eoin_solver.c 입력과 같음).
"""
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT.parent / 'guopsaem_root' / 'verifier_v3'))
from shield_core import DICT, Graph, StaticModel  # noqa: E402
from verify_v3 import ModelV3  # noqa: E402

FORMAT = 'shield-engine-model-1'


def model_path(base_used):
    h = hashlib.sha256(json.dumps([FORMAT, sorted(base_used)], ensure_ascii=False).encode()).hexdigest()[:16]
    return HERE / 'bin' / f'engine_model_{h}.txt'


def export(base_used=frozenset(), out=None):
    base_used = frozenset(base_used)
    full = Graph()
    g = Graph(words=[w for w in full.words if w not in base_used]) if base_used else full
    sm = StaticModel(g)
    sm._base()
    data = json.loads((ROOT / 'site' / 'data.json').read_text(encoding='utf-8'))
    route_fresh = {s['s']: s['r'] for s in data['syllables']}
    route_words = set((ROOT / 'words_621.txt').read_text(encoding='utf-8').split())
    cyc = {x for x in sm.recv if sm.label(x) is None and x not in route_fresh}
    m = ModelV3((ROOT / 'words_621.txt').read_bytes(), 621)

    words = sorted(g.words)
    wid = {w: i for i, w in enumerate(words)}
    groups = list(sm.count)
    gid = {grp: i for i, grp in enumerate(groups)}

    # 음절: 받은 음절 전체(끝 음절) + 루트 음절 + 단어 첫 음절
    syls = sorted(sm.recv | set(route_fresh) | {w[0] for w in g.words})
    sid = {x: i for i, x in enumerate(syls)}

    def tracked(w):
        return w in route_words or sm.sensitive(w)

    lines = [FORMAT, json.dumps({'base_used': sorted(base_used), 'dictionary_sha256':
                                 hashlib.sha256(Path(DICT).read_bytes()).hexdigest()}, ensure_ascii=False)]
    lines.append(f'{len(words)} {len(syls)} {sm.n} {len(groups)}')
    for w in words:   # 글자 / 기록 / 묶음 / 루트 단어 번호
        grp = sm.word_group.get(w)
        rw = m.words.index(w) if w in route_words else -1
        lines.append(f'{w} {1 if tracked(w) else 0} {gid[grp] if grp is not None else -1} {rw}')
    for x in syls:
        succ = {}
        for w in g.moves(x):
            succ.setdefault(w[-1], []).append(w)
        rf = {'W': 1, 'L': 0}.get(route_fresh.get(x), -1)
        rv = sm.recv_v.get(x, -1)
        try:
            mv = m.vertex_of(x) if x in route_fresh else -1
        except Exception:
            mv = -1
        lines.append(f'{x} {full.cont(x)} {rf} {1 if x in cyc else 0} {rv} {mv} {len(succ)}')
        for y, ws in succ.items():
            lines.append(f'{sid[y]} ' + ' '.join(str(wid[w]) for w in sorted(ws)))
    for grp in groups:
        srcs, t = grp
        flag = (1 if grp in sm.loop else 0) | (2 if grp in sm.paired else 0) | (4 if grp in sm.single else 0)
        rev = gid.get(((t,), srcs[0]), -1) if grp in sm.paired else -1
        lines.append(f'{t} {sm.count[grp]} {sm.rc0[grp]} {flag} {rev} {len(srcs)} ' + ' '.join(map(str, srcs)))
    for v in range(sm.n):
        val = {'W': 1, 'L': 0}.get(sm.val0[v], -1)
        s0 = sorted(sm.succ0[v])
        p0 = sorted(sm.pred0[v])
        gb = [gid[grp] for grp in sm.groups_by_src[v]]
        lines.append(f'{val} {sm.loop0[v]} {1 if sm.shl0[v] else 0} {sm.lcnt0[v]} {len(s0)} {len(p0)} {len(gb)} '
                     + ' '.join(map(str, s0 + p0 + gb)))
    # 루트 모형(eoin_solver.c 입력과 같은 내용)
    lines.append(f'{len(m.keys)} {len(m.edges)} {len(m.words)}')
    lines += [f'{s[0]} {t} {c}' for (s, t), c in zip(m.edges, m.full_counts)]
    lines.append(' '.join(str(m.word_group(w)) for w in m.words))
    bu = sorted(m.words.index(w) for w in base_used & route_words)   # 질문 전에 이미 쓴 루트 단어
    lines.append(' '.join(map(str, [len(bu)] + bu)))
    out = Path(out or model_path(base_used))
    out.parent.mkdir(exist_ok=True)
    tmp = out.with_suffix('.tmp')
    tmp.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    tmp.replace(out)
    return out


if __name__ == '__main__':
    used = [w for w in (sys.argv[1] if len(sys.argv) > 1 else '').split(',') if w]
    print(export(used))
