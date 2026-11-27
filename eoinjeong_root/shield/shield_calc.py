#!/usr/bin/env python3
"""보호막 계산기: 보호막이 있는 자리에서 음절을 제시하거나 받았을 때의 승패.

usage:
  shield_calc.py present 칩 --shield 2            보호막 2에서 ~칩을 제시하면 제시한 쪽 승/패, 패배 요인
  shield_calc.py receive 죄 --shield 2            보호막 2에서 죄를 받았을 때 낼 수 있는 단어를 이기는 수/지는 수로
  옵션  --used 단어,단어,…   이미 쓴 단어(그 판의 수순)
        --cert FILE          판정 근거(증명서)를 저장 → shield_verify.py로 검증
        --json               결과를 JSON으로

규칙(사용자 설명, 2026-11-23·25)
  * 단어 w는 지금 보호막 s가 cont(w의 끝 음절) 이하일 때만 낼 수 있다. cont(x) = 전체 사전(482,556단어)에서
    x 또는 x의 두음 음절로 시작하는 단어 수(고정값). 한방(cont 0)은 보호막 0에서만.
  * 보호막은 한 수(양쪽 합쳐)마다 1씩 준다. '보호막 s에서 ~Y를 제시' = 보호막 s일 때 Y로 끝나는 단어를 냈고,
    상대는 보호막 s-1에서 Y를 받는다.  * 낼 수 있는 단어가 없으면 진다(보호막 때문에 못 내는 경우 포함).
판정
  * 보호막 1 이상: 한 수씩 실제로 둔다. 보호막 구간에서 쓴 단어 중 결과를 바꿀 수 있는 단어(제자리 단어, 왕복 쌍,
    같은 묶음이 12개 이하인 단어, 루트 단어)는 정확히 기록해 다시 못 쓰게 하고, 보호막 0 판정에서도 뺀다.
    그 밖의 단어는 같은 묶음에 13개 이상 있어 12수 안에 바닥나지 않고 보호막 0 판정도 바꾸지 않는다.
  * 보호막 0이 된 자리: 루트 음절 173개는 루트전(확정 결과, 쓴 루트 단어가 있으면 루트 계산기로 다시),
    그 밖은 전체 사전의 보호막 0 판정(ModelV3와 같은 정리, 쓴 단어 반영), 그것으로도 안 정해지는
    루트 밖 순환 음절은 사용자의 공격 목록을 따른다.
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT.parent / 'guopsaem_root' / 'verifier_v3'))
from shield_core import Graph, StaticModel  # noqa: E402
import shield_files as F  # noqa: E402  (끝말잇기/앞말잇기 자료: SHIELD_GAME)
from shield_files import show, show_why  # noqa: E402
from verify_v3 import ModelV3  # noqa: E402


def route_binary():
    """루트전 계산기(site/solver/eoin_solver.c, 사이트의 브라우저 계산과 같은 코드)를 필요할 때 컴파일한다."""
    src, out = ROOT / 'site' / 'solver' / 'eoin_solver.c', HERE / 'route_value'
    if not out.exists() or out.stat().st_mtime < src.stat().st_mtime:
        subprocess.run(['gcc', '-O2', '-DNATIVE', '-o', str(out), str(src)], check=True)
    return out


class Lite:
    """C 엔진을 쓸 때 화면 출력에 필요한 것만(이을 수 있는 단어 수, 루트 단어)."""
    def __init__(self, used=()):
        self.full = Graph()
        self.base_used = frozenset(used)
        unknown = [w for w in self.base_used if w not in set(self.full.words)]
        if unknown:
            raise SystemExit(f'사전에 없는 단어: {unknown}')
        self.route_words = set(F.ROUTE_WORDS.read_text(encoding='utf-8').split())
        self.cont_cache = {}

    def cont(self, x):
        if x not in self.cont_cache:
            self.cont_cache[x] = self.full.cont(x)
        return self.cont_cache[x]


class Calc:
    def __init__(self, used=()):
        self.full = Graph()
        self.base_used = frozenset(used)
        unknown = [w for w in self.base_used if w not in set(self.full.words)]
        if unknown:
            raise SystemExit(f'사전에 없는 단어: {unknown}')
        self.g = Graph(words=[w for w in self.full.words if w not in self.base_used]) if self.base_used else self.full
        self.sm = StaticModel(self.g)
        self.cont_cache = {}
        self.succ_cache = {}
        data = json.loads(F.ROUTE_DATA.read_text(encoding='utf-8'))
        self.route_syls = [s['s'] for s in data['syllables']]
        self.route_fresh = {s['s']: s['r'] for s in data['syllables']}
        self.route_words = set(F.ROUTE_WORDS.read_text(encoding='utf-8').split())
        self.route_cache = {}
        self._route_model = None
        self.memo = {}
        # 루트 밖 순환 음절(보호막 0 정리로 안 정해지는 루트 밖 음절, 기본 18개): 단어를 하나씩 두어 보는 직접 탐색
        self.cyc = frozenset(x for x in self.sm.recv if self.sm.label(x) is None and x not in self.route_fresh)
        self.cyc_memo = {}
        self.order_cache = {}

    # ── 사전 ──
    def cont(self, x):
        if x not in self.cont_cache:
            self.cont_cache[x] = self.full.cont(x)
        return self.cont_cache[x]

    def tracked(self, w):
        return w in self.route_words or self.sm.sensitive(w)

    def succ(self, x):
        if x not in self.succ_cache:
            self.succ_cache[x] = {y: sorted(ws) for y, ws in self.g.succ(x).items()}
        return self.succ_cache[x]

    def choices(self, x, s, used):
        """보호막 s, 보호막 구간에서 쓴 단어 used일 때 x에서 낼 수 있는 수. 같은 결과를 내는 단어는 하나로 묶는다:
        끝 음절마다 '기록 안 하는 단어' 하나 + 기록하는 단어는 묶음마다 하나.
        반환 ([(끝 음절, 대표 단어, 같은 단어들)], {보호막 때문에 못 내는 끝 음절: [단어]})"""
        out, blocked = [], {}
        for y, ws in self.succ(x).items():
            avail = [w for w in ws if w not in used]
            if not avail:
                continue
            if self.cont(y) < s:
                blocked[y] = avail
                continue
            free = [w for w in avail if not self.tracked(w)]
            if free:
                out.append((y, free[0], free))
            seen = set()
            for w in avail:
                if self.tracked(w):
                    k = self.sm.word_group.get(w, w) if w not in self.route_words else w
                    if k in seen:
                        continue
                    seen.add(k)
                    out.append((y, w, [w]))
        return out, blocked

    def child_used(self, used, w):
        return used | {w} if self.tracked(w) else used

    # ── 보호막 0 ──
    def route_value(self, x, used):
        ru = frozenset((self.base_used | used) & self.route_words)
        if not ru:
            return self.route_fresh[x], '루트전 결과(확정)'
        k = (x, ru)
        if k not in self.route_cache:
            if self._route_model is None:
                self._route_model = ModelV3(F.ROUTE_WORDS.read_bytes(), F.N_ROUTE)
            m = self._route_model
            with tempfile.TemporaryDirectory() as d:
                d = Path(d)
                lines = [f'{len(m.keys)} {len(m.edges)} {len(m.words)}']
                lines += [f'{s[0]} {t} {c}' for (s, t), c in zip(m.edges, m.full_counts)]
                lines.append(' '.join(str(m.word_group(w)) for w in m.words))
                (d / 'model.txt').write_text('\n'.join(lines) + '\n')
                ids = ' '.join(str(m.words.index(w)) for w in sorted(ru))
                (d / 'pos.txt').write_text(f'{m.vertex_of(x)} -1 {-len(ru)} {ids}\n')
                r = subprocess.run([str(route_binary()), str(d / 'model.txt'), str(d / 'pos.txt')],
                                   capture_output=True, text=True, check=True)
            self.route_cache[k] = 'W' if r.stdout.split()[0] == '1' else 'L'
        return self.route_cache[k], f'루트전 계산(쓴 루트 단어 {len(ru)}개 반영)'

    def oracle(self, x, used=frozenset()):
        lab = self.sm.label(x, frozenset(w for w in used if self.sm.sensitive(w)))
        if lab is not None:
            if lab == 'L' and not [w for ws in self.succ(x).values() for w in ws if w not in used]:
                return 'L', '보호막 0 판정: 낼 단어 없음'
            return lab, '보호막 0 판정(전체 사전)'
        if x in self.route_fresh:
            return self.route_value(x, used)
        if x in self.cyc:
            v = self.cyc_value(x, used)
            if v is not None:
                return v, '루트 밖 순환 음절: 단어를 하나씩 두어 본 탐색'
        return '?', '미정(루트 밖 순환)'

    def cyc_value(self, x, used):
        """순환 음절 x를 받은 쪽의 값. 순환 음절끼리의 단어는 하나씩 실제로 두고(다시 못 씀), 순환 밖으로 나가는
        단어는 그 끝 음절의 보호막 0 판정(루트 결과, 전체 사전 판정)을 쓴다. 모르면 None."""
        k = (x, frozenset(used))
        if k in self.cyc_memo:
            return self.cyc_memo[k]
        unknown = False
        res = 'L'
        for y, ws in self.succ(x).items():
            for w in ws:
                if w in used:
                    continue
                cu = used | {w}
                cv = self.cyc_value(y, cu) if y in self.cyc else self.oracle(y, self.child_used(used, w))[0]
                if cv == 'L':
                    res = 'W'
                    break
                if cv != 'W':
                    unknown = True
            if res == 'W':
                break
        if res == 'L' and unknown:
            res = None
        self.cyc_memo[k] = res
        return res

    # ── 탐색 ──
    def value(self, x, s, used=frozenset()):
        """보호막 s에서 x를 받은 쪽: (W|L|?, 근거, 이기는 수 (끝 음절, 단어) 또는 None)."""
        s = max(0, s)
        key = (x, s, used)
        if key in self.memo:
            return self.memo[key]
        if s == 0:
            v, why = self.oracle(x, used)
            res = (v, why, None)   # 보호막 0의 이기는 단어는 필요할 때만 찾는다(win_at0)
        else:
            ch, _ = self.choices(x, s, used)
            if not ch:
                res = ('L', f'보호막 {s}에서 낼 수 있는 단어 없음', None)
            else:
                res, unknown = None, False
                for y, w, _ in sorted(ch, key=lambda c: self.order(c[0], s - 1, used)):
                    cv = self.value(y, s - 1, self.child_used(used, w))[0]
                    if cv == 'L':
                        res = ('W', f'{w}(→{y})', (y, w))
                        break
                    unknown = unknown or cv == '?'
                if res is None:
                    res = ('?', '미정이 섞임', None) if unknown else ('L', f'낼 수 있는 수 {len(ch)}가지가 모두 상대 승', None)
        self.memo[key] = res
        return res

    def order(self, y, t, used):
        """이기는 수를 빨리 찾기 위한 순서: 보호막 0 판정이 패인 음절, 상대가 낼 수 있는 갈래가 적은 음절부터."""
        if t == 0:
            return (0, 0, y)
        k = (y, t)
        if k not in self.order_cache:
            lab = self.sm.label(y)
            n = sum(1 for z in self.succ(y) if self.cont(z) >= t)
            self.order_cache[k] = (0 if lab == 'L' else 1, n, y)
        return self.order_cache[k]

    def win_at0(self, x, used=frozenset()):
        """보호막 0에서 x를 받아 이길 때 실제로 이기는 단어 하나(표시용)."""
        if self.value(x, 0, used)[0] != 'W':
            return None
        for y, w, _ in self.choices(x, 0, used)[0]:
            if self.oracle(y, self.child_used(used, w))[0] == 'L':
                return (y, w)
        return None

    def classify(self, x, s, used=frozenset(), only=None):
        """x에서 낼 수 있는 수마다 결과. only = (끝 음절, 단어)면 그 수 하나만(이기는 수를 찾았으면 나머지는 안 봄)."""
        ch, blocked = self.choices(x, s, used)
        if only is not None:
            ch = [c for c in ch if (c[0], c[1]) == tuple(only)]
        rows = []
        for y, w, same in ch:
            cu = self.child_used(used, w)
            cv, why, win = self.value(y, s - 1, cu)
            if win is None and cv == 'W' and s - 1 <= 0:
                win = self.win_at0(y, cu)
            rows.append({'end': y, 'word': w, 'words': same, 'cont': self.cont(y),
                         'result_for_mover': {'L': '이기는 수', 'W': '지는 수'}.get(cv, '미정'),
                         'opponent': {'value': cv, 'why': why, 'winning_word': win[1] if win else None}})
        rows.sort(key=lambda r: (r['result_for_mover'] != '이기는 수', r['end']))
        return rows, blocked


def certificate(c, x, s, route_dir=None):
    """판정 근거. 자리 = (받은 음절, 보호막, 보호막 구간에서 쓴 단어). 승 자리는 이기는 수 하나, 패 자리는 모든 수.
    route_dir: 쓴 루트 단어가 있는 루트 잎을 solver_v5 + verify_v4로 확정한 증명서를 둘 폴더."""
    def k(y, t, u):
        return f"{y}|{t}|{','.join(sorted(u))}"
    nodes, todo = {}, [(x, max(0, s), frozenset())]
    while todo:
        y, t, u = todo.pop()
        key = k(y, t, u)
        if key in nodes:
            continue
        v, why, win = c.value(y, t, u)
        n = {'x': y, 't': t, 'used': sorted(u), 'v': v, 'why': why}
        if t == 0:
            n['leaf'] = True
            if route_dir is not None and why.startswith('루트전 계산'):
                import route_proof
                ru = (c.base_used | u) & c.route_words
                rec = route_proof.prove(y, ru, route_dir)
                n['route_proof'] = {'id': rec['id'], 'accepted': rec['accepted'], 'result': rec['result']}
                if rec['accepted'] and rec['result'] != v:
                    print(f'경고: {key} 루트 계산기 {v}, 정식 증명 {rec["result"]}', file=sys.stderr)
        elif v == 'W':
            yy, w = win
            n['word'] = w
            n['child'] = k(yy, t - 1, c.child_used(u, w))
            todo.append((yy, t - 1, c.child_used(u, w)))
        elif v == 'L':
            ch, _ = c.choices(y, t, u)
            n['words'] = [w for _, w, _ in ch]
            for yy, w, _ in ch:
                todo.append((yy, t - 1, c.child_used(u, w)))
        nodes[key] = n
    return {'format': 'shield-cert-2', 'root': k(x, max(0, s), frozenset()), 'used': sorted(c.base_used),
            'cycle': sorted(c.cyc), 'nodes': nodes}


def attach_route_proofs(nodes, base_used, route_words, route_dir, jobs=4):
    """쓴 루트 단어가 있는 루트 잎(why '루트전 계산…')마다 solver_v5 증명서를 만들고 verify_v4로 확인해 붙인다.
    같은 (음절, 쓴 루트 단어)는 한 번만, jobs개를 동시에."""
    import route_proof
    from concurrent.futures import ThreadPoolExecutor
    route_proof.model()   # 스레드 전에 한 번 만든다
    todo = {}
    for key, n in nodes.items():
        if n.get('leaf') and n['why'].startswith('루트전 계산'):
            ru = (frozenset(base_used) | frozenset(n['used'])) & route_words
            todo.setdefault((n['x'], ru), []).append(key)
    with ThreadPoolExecutor(jobs) as ex:
        recs = dict(zip(todo, ex.map(lambda k: route_proof.prove(k[0], k[1], route_dir), todo)))
    for k, keys in todo.items():
        rec = recs[k]
        for key in keys:
            n = nodes[key]
            n['route_proof'] = {'id': rec['id'], 'accepted': rec['accepted'], 'result': rec['result']}
            if rec['accepted'] and rec['result'] != n['v']:
                print(f'경고: {key} 루트 계산기 {n["v"]}, 정식 증명 {rec["result"]}', file=sys.stderr)


def engine_binary():
    """C 엔진(engine/shield_engine.c)을 필요할 때 컴파일한다."""
    src, out = HERE / 'engine' / 'shield_engine.c', HERE / 'bin' / 'shield_engine'
    solver = ROOT / 'site' / 'solver' / 'eoin_solver.c'
    if not out.exists() or out.stat().st_mtime < max(src.stat().st_mtime, solver.stat().st_mtime):
        out.parent.mkdir(exist_ok=True)
        subprocess.run(['gcc', '-O2', '-o', str(out), str(src)], check=True)
    return out


def run_c_engine(base_used, x, t, all_moves):
    """C 엔진으로 계산. 반환: (값, 근거, 이기는 수, 수 분류 rows, 막힌 수 blocked, 증명서 자리들, 순환 음절, 통계)."""
    import shield_export
    mp = shield_export.model_path(base_used)
    if not mp.exists():
        shield_export.export(base_used, mp)
    r = subprocess.run([str(engine_binary()), str(mp), x, str(t)] + (['all'] if all_moves else []),
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f'C 엔진 오류: {r.stderr.strip()[-400:]}')
    out = json.loads(r.stdout)
    if 'error' in out:
        raise SystemExit(f"C 엔진: {out['error']} ({x})")
    rows = []
    for m in out['rows']:
        rows.append({'end': m['end'], 'word': m['word'], 'words': m['words'], 'cont': m['cont'],
                     'result_for_mover': {'L': '이기는 수', 'W': '지는 수'}.get(m['value'], '미정'),
                     'opponent': {'value': m['value'], 'why': m['why'], 'winning_word': m['winning_word']}})
    rows.sort(key=lambda r: (r['result_for_mover'] != '이기는 수', r['end']))
    blocked = {y: ws for y, _, ws in out['blocked']}
    win = tuple(out['win']) if out['win'] else None
    return out['value'], out['why'], win, rows, blocked, out['nodes'], out['cycle'], out['stats']


def josa(word, a, b):
    """받침 있으면 a, 없으면 b (을/를, 은/는). a가 '으로'면 으로/로."""
    c = ord(word[-1]) - 0xAC00
    jong = c % 28 if 0 <= c < 11172 else 0
    if a == '으로':
        return word + ('로' if jong in (0, 8) else '으로')
    return word + (a if jong else b)


def fmt_words(ws, k=3):
    return ', '.join(show(w) for w in ws[:k]) + (f' 외 {len(ws) - k}개' if len(ws) > k else '')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('mode', choices=['present', 'receive'])
    ap.add_argument('syllable')
    ap.add_argument('--shield', type=int, required=True)
    ap.add_argument('--used', default='')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--cert')
    ap.add_argument('--all', action='store_true', help='이기는 수를 찾은 뒤에도 나머지 수를 모두 분류(오래 걸릴 수 있음)')
    ap.add_argument('--engine', choices=['c', 'py'], default='c', help='c: C 엔진(기본, 빠름), py: 파이썬 엔진(대조용)')
    a = ap.parse_args()
    if not 0 <= a.shield <= 12:
        raise SystemExit('보호막은 0~12만 계산합니다(기록하지 않는 단어가 바닥나지 않는다는 근거가 12수까지임).')
    base_used = [w.strip() for w in a.used.split(',') if w.strip()]
    if a.engine == 'py':
        c = Calc(base_used)
    else:
        c = Lite(base_used)
    x, s = a.syllable, a.shield
    q = {'mode': a.mode, 'syllable': x, 'shield': s, 'used': a.used}
    t = max(0, s - 1) if a.mode == 'present' else s
    if a.mode == 'present' and c.cont(x) < s:
        # 규칙: ~X는 보호막이 (X로 이을 수 있는 단어 수) 이하일 때만 낼 수 있다. 낼 수 없으면 승패를 따지지 않는다.
        msg = (f'보호막 {s}에서 ~{josa(x, "을", "를")} 제시 → 제시할 수 없음\n'
               f'  {josa(x, "으로", "로")} {F.CONT_WORD} 단어가 {c.cont(x)}개라서 ~{josa(x, "은", "는")} 보호막 {c.cont(x)} 이하에서만 낼 수 있습니다.')
        if a.json:
            print(json.dumps(dict(q, legal=False, cont=c.cont(x)), ensure_ascii=False, indent=1))
        else:
            print(msg)
        if a.cert:
            Path(a.cert).write_text(json.dumps({'format': 'shield-cert-2', 'game': F.GAME, 'query': q, 'illegal': True, 'cont': c.cont(x),
                                                'used': sorted(c.base_used), 'nodes': {}}, ensure_ascii=False),
                                    encoding='utf-8')
        return
    # 패(모든 수가 짐)는 이미 모든 수를 본 결과라 분류가 공짜. 승은 이기는 수 하나로 확정되므로 --all일 때만 나머지를 본다.
    if a.engine == 'py':
        v, why, win = c.value(x, t)
        partial = v == 'W' and win is not None and not a.all
        rows, blocked = c.classify(x, t, only=win if partial else None)
        if a.cert:
            cert = certificate(c, x, t, route_dir=Path(a.cert + '.route'))
            Path(a.cert).write_text(json.dumps(dict(cert, query=q, game=F.GAME), ensure_ascii=False), encoding='utf-8')
    else:
        v, why, win, rows, blocked, nodes, cycle, stats = run_c_engine(c.base_used, x, t, a.all)
        partial = v == 'W' and win is not None and not a.all
        if a.cert:
            attach_route_proofs(nodes, c.base_used, c.route_words, Path(a.cert + '.route'))
            cert = {'format': 'shield-cert-2', 'root': f'{x}|{t}|', 'used': sorted(c.base_used), 'cycle': cycle,
                    'nodes': nodes, 'engine': dict(stats, engine='c')}
            Path(a.cert).write_text(json.dumps(dict(cert, query=q, game=F.GAME), ensure_ascii=False), encoding='utf-8')
    if a.json:
        print(json.dumps(dict(q, game=F.GAME, value_for_mover=v, why=why, moves=rows, blocked=blocked), ensure_ascii=False, indent=1))
        return
    if a.mode == 'present':
        print(f'보호막 {s}에서 ~{josa(x, "을", "를")} 제시')
        print(f'  상대는 보호막 {t}에서 {josa(x, "을", "를")} 받습니다.')
        print(f'  판정: 제시한 쪽 {({"L": "승", "W": "패"}).get(v, "미정")}  ({show_why(why)})')
        wins = [r for r in rows if r['result_for_mover'] == '이기는 수']
        loses = [r for r in rows if r['result_for_mover'] == '지는 수']
        if wins and partial:
            print('  패배 요인(상대의 이기는 응수) — 하나만 나와도 결과가 확정되므로 찾은 하나만 적습니다(전부는 --all):')
        elif wins:
            print(f'  패배 요인(상대의 이기는 응수) {len(wins)}가지:')
        if wins:
            for r in wins:
                print(f"    - {fmt_words(r['words'])} → 내가 보호막 {max(0, t - 1)}에서 {josa(r['end'], '을', '를')} 받고 짐  [{show_why(r['opponent']['why'])}]")
        if loses:
            print(f'  상대가 내도 지는 응수 {len(loses)}가지:')
            for r in loses[:12]:
                o = r['opponent']
                ans = f" → 내가 {josa(show(o['winning_word']), '으로', '로')} 이김" if o['winning_word'] else ''
                print(f"    - {fmt_words(r['words'], 2)}{ans}  [{show_why(o['why'])}]")
            if len(loses) > 12:
                print(f'    … 외 {len(loses) - 12}가지')
        label = '상대가'
    else:
        print(f'보호막 {s}에서 {josa(x, "을", "를")} 받음 → 받은 쪽 {({"W": "승", "L": "패"}).get(v, "미정")}  ({show_why(why)})')
        if partial:
            print('  (이기는 수 하나로 확정. 나머지 수의 분류는 --all)')
        for lab in ('이기는 수', '지는 수', '미정'):
            rs = [r for r in rows if r['result_for_mover'] == lab]
            if rs:
                print(f'  {lab} {len(rs)}가지:')
                for r in rs[:15]:
                    o = r['opponent']
                    tail = f" — 상대가 {josa(show(o['winning_word']), '으로', '로')} 이김" if o['winning_word'] else f"  [상대: {show_why(o['why'])}]"
                    print(f"    - {fmt_words(r['words'], 3)} (→{r['end']}){tail}")
                if len(rs) > 15:
                    print(f'    … 외 {len(rs) - 15}가지')
        label = ''
    if blocked:
        print(f'  보호막 {t} 때문에 {label + " " if label else ""}못 내는 끝 음절 {len(blocked)}가지: ' +
              ', '.join(f"{y}({fmt_words(ws, 2)}, 보호막 {c.cont(y)} 이하부터)" for y, ws in list(blocked.items())[:10]))


if __name__ == '__main__':
    main()
