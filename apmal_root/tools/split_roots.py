#!/usr/bin/env python3
"""30분(1차 600초 + 2차 1200초) 안에 안 끝난 앞말잇기 루트 국면을 첫 수별로 나눠 4코어에서 푼다(묶음마다 6시간).

usage: split_roots.py RUN_DIR [--parts 4] [--hours 6] [--tt-mb 3072] [--jobs 4] [--wait-for FILE]
  RUN_DIR      예: apmal_root/results/roots_split (처음 실행 때 plan.json을 만들고, 다시 실행하면 그대로 이어서 함)
  --wait-for   이 파일이 생길 때까지 기다렸다가 시작(2차가 끝나는 표시 DONE_roots_1200s)

나누는 법 (eoinjeong_root/shield/shield_split.py와 같은 생각: 큰 질문을 첫 자리의 수별로 나눈다)
* 루트 국면 = 아무 단어도 안 쓴 채 그 음절을 받은 쪽이 둘 차례. 받은 쪽이 낼 수 있는 루트 단어마다
  '그 단어를 낸 뒤의 국면'(상대 차례)을 따로 푼다. 수가 parts개보다 적으면 그 아래(상대가 낼 수 있는 수)까지
  한 단계씩 더 나눈다(최대 6수). 숫자 입력이 똑같은 국면(같은 묶음의 단어를 낸 경우)은 한 번만 푼다.
* 각 국면은 solver_v5로 풀고, 그 국면의 자리 파일마다 verify_v4가 수락 조건 8개로 수락해야 그 국면이 확정이다.
  입력이 같은 자리들은 같은 증명서를 쓰되, 자리 파일마다 따로 검증한다.
* 합치기(한 수 앞을 보는 것뿐): 둘 차례인 쪽은 다음 국면 중 하나라도 '둘 차례인 쪽 패'가 있으면 승,
  다음 국면이 모두 '둘 차례인 쪽 승'이면 패. 루트의 결과가 정해지면 그 루트의 나머지 계산은 멈춘다.
  다른 수가 이미 정해서 필요 없어진 국면도 멈춘다.
* 한 루트의 나눈 국면들을 min(parts, 국면 수)묶음으로 번갈아 나누고, 묶음마다 탐색 시간 합계 hours시간.
  묶음 안에서는 차례로 풀며, 국면 하나에 묶음의 남은 시간을 모두 준다. 한도에 닿으면 미확정으로 둔다.
* 계산기는 동시에 jobs개(4)까지. 여러 루트의 묶음을 차례로 4코어에 나눠 준다.
* 컨테이너가 다시 켜져도 이어서 할 수 있게, 국면마다 탐색 상태(tt/)를 저장하고 결과(res/)를 남긴다.
  쓴 시간은 결과 파일과 저장 상태의 머리(state_carried_seconds)에서 다시 센다.

쓰는 것(RUN_DIR 아래)
  plan.json          나눈 모양(루트별 나무, 국면, 묶음). 처음 한 번 정하고 고치지 않는다.
  pos/<uid>_<j>.json  국면의 자리 파일(검증기에 주는 것), in/<uid>.txt 숫자 입력, proof/<uid>.v4.gz 증명서
  res/<uid>.json     국면 결과(solver JSON, 자리별 verify JSON과 수락 조건 8개, 쓴 시간)
  roots.json         루트별 결과(W/L/미확정)와 그 근거 국면
  DONE               다 끝났을 때
"""
import argparse
import hashlib
import json
import os
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]          # apmal_root
REPO = HERE.parent
sys.path.insert(0, str(REPO / 'guopsaem_root' / 'verifier_v3'))
sys.path.insert(0, str(REPO / 'guopsaem_root' / 'tools'))
from verify_v3 import ModelV3  # noqa: E402
import solve_common as sc  # noqa: E402

DICT = HERE / 'words_534.txt'
NWORDS = 534
ROOT_RES = HERE / 'results' / 'roots' / 'res'
PLAN = HERE / 'plans' / 'roots.jsonl'
MAIN_SYL = HERE / 'source' / '루트단어_음절1.txt'
MAX_DEPTH = 6


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def write_json(path, obj, indent=1):
    tmp = Path(str(path) + '.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=indent) + '\n', encoding='utf-8')
    os.replace(tmp, path)


def undecided_roots():
    """2차(1200초)까지 돌았는데 수락되지 않은 루트."""
    out = []
    for line in PLAN.read_text(encoding='utf-8').splitlines():
        it = json.loads(line)
        r = json.loads((ROOT_RES / f"{it['id']}.json").read_text(encoding='utf-8'))
        if r.get('accepted'):
            continue
        if r.get('limit_seconds') != 1200.0:
            raise SystemExit(f"{it['id']}: 2차(1200초)를 아직 안 돌았음")
        out.append((it['id'], it['initial_syllable'], r['solver'].get('best_group')))
    return out


def make_plan(m, parts):
    roots = {}
    for rid, s, best in undecided_roots():
        def legal(h):
            cur, _, used = m.position({'initial_syllable': s, 'history': h})
            return [w for w in m.words if w[0] in m.keys[cur] and w not in used]

        def inp(h):
            cur, counts, _ = m.position({'initial_syllable': s, 'history': h})
            return m.numeric_input(cur, counts)
        nodes = {'': {'h': [], 'children': []}}
        frontier = ['']
        depth = 0
        while depth < MAX_DEPTH:
            # 루트는 꼭 한 번 나누고, 그다음은 다른 국면이 parts개보다 적을 때만 한 단계 더 나눈다
            if depth > 0 and len({inp(nodes[k]['h']) for k in frontier}) >= parts:
                break
            if not any(legal(nodes[k]['h']) for k in frontier):
                break
            new = []
            for k in frontier:
                h = nodes[k]['h']
                ws = legal(h)
                if not ws:                       # 낼 수가 없는 자리는 펼치지 않고 그대로 국면으로 푼다
                    new.append(k)
                    continue
                if depth == 0 and best is not None:      # 루트 탐색이 가장 유망하다고 본 묶음을 먼저
                    ws.sort(key=lambda w: (m.word_group(w) != best, m.words.index(w)))
                for w in ws:
                    ck = '/'.join(h + [w])
                    nodes[ck] = {'h': h + [w], 'children': []}
                    nodes[k]['children'].append(ck)
                    new.append(ck)
            frontier = new
            depth += 1
        units, by_input, order = {}, {}, []
        for k in frontier:
            b = inp(nodes[k]['h'])
            if b not in by_input:
                uid = f'{rid}_U{len(by_input):03d}'
                by_input[b] = uid
                units[uid] = {'positions': [], 'input_sha256': hashlib.sha256(b).hexdigest()}
                order.append(uid)
            uid = by_input[b]
            nodes[k]['unit'] = uid
            if nodes[k]['h'] not in units[uid]['positions']:
                units[uid]['positions'].append(nodes[k]['h'])
        nb = min(parts, len(order))
        batches = [order[i::nb] for i in range(nb)]
        for bi, b in enumerate(batches):
            for uid in b:
                units[uid]['batch'] = bi
        roots[rid] = {'syllable': s, 'best_group': best, 'depth': depth, 'nodes': nodes, 'units': units,
                      'batches': batches}
    return roots


class Runner:
    def __init__(self, work, a):
        self.work, self.a = work, a
        self.m = ModelV3(DICT.read_bytes(), NWORDS)
        self.lock = threading.Lock()
        self.res = {}
        self.running = {}          # uid -> input path
        self.stopped = set()
        for d in ('pos', 'in', 'proof', 'log', 'res', 'tt'):
            (work / d).mkdir(parents=True, exist_ok=True)
        pf = work / 'plan.json'
        if pf.exists():
            self.plan = json.loads(pf.read_text(encoding='utf-8'))
            assert self.plan['dictionary_sha256'] == sha(DICT)
            assert sorted(self.plan['roots']) == sorted(r for r, _, _ in undecided_roots()), '미확정 루트가 plan과 다름'
        else:
            self.plan = {'format': 'apmal-root-split-1', 'dictionary': str(DICT.relative_to(REPO)),
                         'dictionary_sha256': sha(DICT), 'parts': a.parts, 'hours_per_batch': a.hours,
                         'tt_mb': a.tt_mb, 'jobs': a.jobs, 'max_depth': MAX_DEPTH,
                         'created': time.strftime('%Y-%m-%d %H:%M:%S'), 'roots': make_plan(self.m, a.parts)}
            write_json(pf, self.plan)
        self.roots = self.plan['roots']
        self.budget = self.plan['hours_per_batch'] * 3600.0
        for rid, R in self.roots.items():
            for uid, u in R['units'].items():
                for j, h in enumerate(u['positions']):
                    posf = work / 'pos' / f'{uid}_{j}.json'
                    if not posf.exists():
                        posf.write_text(json.dumps({'initial_syllable': R['syllable'], 'history': h},
                                                   ensure_ascii=False), encoding='utf-8')
                inf = work / 'in' / f'{uid}.txt'
                if not inf.exists():
                    cur, counts, _ = self.m.position({'initial_syllable': R['syllable'], 'history': u['positions'][0]})
                    inf.write_bytes(self.m.numeric_input(cur, counts))
                assert sha(inf) == u['input_sha256']
                f = work / 'res' / f'{uid}.json'
                if f.exists():
                    self.res[uid] = json.loads(f.read_text(encoding='utf-8'))

    # ---- 값 매기기(한 수 앞을 보는 것뿐)
    def unit_value(self, uid):
        r = self.res.get(uid)
        return r.get('value') if r and r.get('accepted') else None

    def node_value(self, R, k, memo):
        if k in memo:
            return memo[k]
        n = R['nodes'][k]
        if 'unit' in n:
            v = self.unit_value(n['unit'])
        else:
            vs = [self.node_value(R, c, memo) for c in n['children']]
            v = 'W' if 'L' in vs else ('L' if vs and all(x == 'W' for x in vs) else None)
        memo[k] = v
        return v

    def needed(self, rid, uid):
        """국면 uid가 아직 필요한가: 그 국면을 쓰는 자리 중 하나라도, 자기와 조상이 모두 아직 정해지지 않았으면."""
        R = self.roots[rid]
        memo = {}
        for k, n in R['nodes'].items():
            if n.get('unit') != uid:
                continue
            h = n['h']
            if all(self.node_value(R, '/'.join(h[:i]), memo) is None for i in range(len(h) + 1)):
                return True
        return False

    def spent(self, uid):
        r = self.res.get(uid)
        if r is not None:
            return r['spent_seconds']
        tt = self.work / 'tt' / f'{uid}.tt'
        return (sc.state_carried_seconds(tt) or 0.0) if tt.exists() else 0.0

    # ---- 국면 하나 풀기
    def run_unit(self, rid, uid, seconds):
        R, w = self.roots[rid], self.work
        u = R['units'][uid]
        inf, proof, tt, log = w / 'in' / f'{uid}.txt', w / 'proof' / f'{uid}.v4.gz', w / 'tt' / f'{uid}.tt', w / 'log' / f'{uid}.out'
        carried = (sc.state_carried_seconds(tt) or 0.0) if tt.exists() else 0.0
        while True:
            try:
                with self.lock:
                    self.running[uid] = str(inf)
                t0 = time.time()
                sol = sc.solve(inf, proof, seconds, self.plan['tt_mb'], tt=tt, log=log)
                break
            except sc.LowDisk:
                with self.lock:
                    self.running.pop(uid, None)
                sc.wait_for_disk(w, uid)
        wall = time.time() - t0
        with self.lock:
            self.running.pop(uid, None)
            killed = uid in self.stopped
        run_s = sol.get('seconds') if isinstance(sol.get('seconds'), (int, float)) else wall
        res = {'uid': uid, 'root': rid, 'positions': u['positions'], 'limit_seconds': seconds, 'tt_mb': self.plan['tt_mb'],
               'carried_seconds_before': carried, 'run_seconds': run_s, 'spent_seconds': round(carried + run_s, 3),
               'solver': sol, 'solver_binary_sha256': sha(sc.SOLVER), 'verifier_binary_sha256': sha(sc.VERIFY_V4),
               'dictionary_sha256': sha(DICT), 'input_sha256': sha(inf), 'accepted': False, 'value': None,
               'status': 'stopped' if killed else 'undecided', 'wall_solve_seconds': round(wall, 3)}
        if not killed and sol.get('result') in ('win', 'loss') and not sol.get('proof_error') and proof.exists():
            want = 'W' if sol['result'] == 'win' else 'L'
            t1 = time.time()
            vs = []
            for j in range(len(u['positions'])):
                posf = w / 'pos' / f'{uid}_{j}.json'
                ok, vr = sc.verify(DICT, NWORDS, posf, proof, inf, want, sol.get('proof_nodes', 0))
                vs.append({'position': f'pos/{uid}_{j}.json', 'position_sha256': sha(posf), 'accepted': ok, 'verify': vr})
            ok = all(v['accepted'] for v in vs)
            res.update({'verify': vs, 'accepted': ok, 'value': want if ok else None, 'proof_sha256': sha(proof),
                        'proof_bytes': proof.stat().st_size, 'wall_verify_seconds': round(time.time() - t1, 3),
                        'status': 'accepted' if ok else 'rejected'})
            res['state_released'] = sc.release_state(tt, ok, proof)
        elif proof.exists():
            proof.unlink()
        res['state_kept'] = tt.exists()
        write_json(w / 'res' / f'{uid}.json', res)
        with self.lock:
            self.res[uid] = res
        return res

    def drop_state(self, uid):
        tt = self.work / 'tt' / f'{uid}.tt'
        for p in (tt, Path(str(tt) + '.tmp')):
            if p.exists():
                p.unlink()

    # ---- 묶음 하나(코어 하나)
    def run_batch(self, job):
        rid, bi = job
        R = self.roots[rid]
        for uid in R['batches'][bi]:
            with self.lock:
                need = self.needed(rid, uid)
            if not need:
                self.drop_state(uid)
                continue
            r = self.res.get(uid)
            if r is not None and (r.get('accepted') or r.get('status') == 'rejected'):
                continue                     # 확정, 또는 검증기가 거절한 증명서(다시 풀지 않고 미확정으로 둠)
            used = sum(self.spent(x) for x in R['batches'][bi])
            left = self.budget - used
            if left < 1:
                break
            res = self.run_unit(rid, uid, round(left, 3))
            tag = {'W': '둘 차례인 쪽 승', 'L': '둘 차례인 쪽 패'}.get(res['value'], res['status'])
            print(time.strftime('%H:%M:%S'), rid, R['syllable'], uid, '/'.join(x[::-1] for x in res['positions'][0]), tag,
                  f"탐색 {res['run_seconds']:.1f}s 누적 {res['spent_seconds']:.1f}s", flush=True)
            self.report()
        return job

    def report(self):
        with self.lock:
            out = {}
            for rid, R in self.roots.items():
                memo = {}
                v = self.node_value(R, '', memo)
                out[rid] = {'syllable': R['syllable'], 'value': v,
                            'units_accepted': sorted(u for u in R['units'] if self.unit_value(u)),
                            'units': len(R['units']), 'batches': len(R['batches']),
                            'spent_seconds_by_batch': [round(sum(self.spent(x) for x in b), 1) for b in R['batches']]}
            write_json(self.work / 'roots.json', out)
        return out

    def watch(self, stop):
        """필요 없어진 국면의 계산기를 멈춘다(루트나 위 국면이 이미 정해짐)."""
        while not stop.is_set():
            with self.lock:
                kill = [(uid, p) for uid, p in self.running.items()
                        if uid not in self.stopped and not self.needed(uid.split('_')[0], uid)]
                for uid, _ in kill:
                    self.stopped.add(uid)
            for uid, p in kill:
                for pid in os.listdir('/proc'):
                    if not pid.isdigit():
                        continue
                    try:
                        cmd = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
                    except OSError:
                        continue
                    if any(x.endswith(b'solver_v5') for x in cmd[:2]) and p.encode() in cmd:
                        try:
                            os.kill(int(pid), signal.SIGTERM)
                            print(time.strftime('%H:%M:%S'), uid, '필요 없어져 멈춤', flush=True)
                        except OSError:
                            pass
            stop.wait(20)

    def run(self):
        # 주요 루트 음절(source/루트단어_음절1.txt)부터 먼저, 희귀 루트 음절(음절2)은 나중에. 순서만 바뀌고 계산 양은 같음
        main = {l.split(':')[0].strip() for l in MAIN_SYL.read_text(encoding='utf-8').splitlines() if ':' in l}
        first = sorted(self.roots, key=lambda rid: (self.roots[rid]['syllable'] not in main, rid))
        jobs = [(rid, bi) for rid in first for bi in range(len(self.roots[rid]['batches']))]
        print(json.dumps({'roots': len(self.roots), 'units': sum(len(R['units']) for R in self.roots.values()),
                          'batches': len(jobs), 'hours_per_batch': self.plan['hours_per_batch'],
                          'jobs': self.plan['jobs'], 'solver': sc.SOLVER, 'verifier': sc.VERIFY_V4}, ensure_ascii=False),
              flush=True)
        stop = threading.Event()
        th = threading.Thread(target=self.watch, args=(stop,), daemon=True)
        th.start()
        t0 = time.time()
        with ThreadPoolExecutor(self.plan['jobs']) as ex:
            list(ex.map(self.run_batch, jobs))
        stop.set()
        out = self.report()
        for rid, r in out.items():
            if r['value'] is not None:
                for uid in self.roots[rid]['units']:
                    self.drop_state(uid)
        (self.work / 'DONE').write_text(f'{time.time() - t0:.1f}\n')
        print('끝', json.dumps({rid: r['value'] for rid, r in out.items()}, ensure_ascii=False), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('dir')
    ap.add_argument('--parts', type=int, default=4)
    ap.add_argument('--hours', type=float, default=6)
    ap.add_argument('--tt-mb', type=int, default=3072)
    ap.add_argument('--jobs', type=int, default=4)
    ap.add_argument('--wait-for')
    a = ap.parse_args()
    if a.wait_for:
        while not Path(a.wait_for).exists():
            time.sleep(30)
    Runner(Path(a.dir), a).run()


if __name__ == '__main__':
    main()
