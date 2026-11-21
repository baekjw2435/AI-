#!/usr/bin/env python3
"""Follow-up branches: prove positions with any history (e.g. 식생활 → 활극 → 극락) and verify each certificate.

usage: branch_run.py CASES.json WORK [--seconds 600] [--budget 0] [--jobs 3] [--tt-mb 1024] [--stuck-nodes 200000]
                     [--only b01,b02 (these cases, in this order)] [--keep-state 0|1] [--cumulative-cap 0]
  CASES.json: {"cases": [{"name", "position": {"initial_syllable", "history": [...]}, "method": "replay"|"direct"|"table",
               "source": vertex name, "source_path": certificate (replay; default sources/<source>/proof.v4.gz),
               "guide": dir, "guide_book": book id, "expect": "W"|"L" (table)}]}
  WORK/<name>/ gets pos.json, in.txt, proof.v4.gz, run.json (and state.tt with --keep-state 1 while unsolved).
  WORK/budget.json (or --budget-log NAME): the budget account of this call.

The position is the case's own history, every word in it used; nothing is taken from another history.
--seconds is the most search time one case may use (guided walk, local searches of stuck states, normal search).
--budget T (> 0): the search seconds of the whole call add up to at most T. Cases start in their order; a case gets
  min(--seconds, what is left after the finished cases' actual search and the running cases' allotments). Unused time
  of a finished case goes back to the pool. A case that cannot get at least 5 s is not started ('untried').
--cumulative-cap C (> 0): a case that was run before (WORK/<name>/run.json, not accepted) continues from its saved state
  and gets at most C minus the search seconds it already used (the largest of its run records' total_search_seconds and
  the seconds carried in state.tt). The earlier run.json is kept as run.<n>.json.
--keep-state 1: the search state is checkpointed to WORK/<name>/state.tt; it is deleted when the certificate is
  accepted and kept otherwise, so the case can be continued later.
Certificate writing and verification have no extra limit, as everywhere in this study. A case counts only if the
unchanged verify_v4 accepts its certificate with every acceptance condition of solve_common.verify; otherwise it
stays unknown.
"""
from concurrent.futures import ThreadPoolExecutor
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

HERE = Path(__file__).resolve().parent
BASIC = HERE.parents[1]
sys.path.insert(0, str(BASIC.parent / 'guopsaem_root' / 'verifier_v3'))
sys.path.insert(0, str(BASIC.parent / 'guopsaem_root' / 'tools'))
from verify_v3 import ModelV3  # noqa: E402
import solve_common as sc  # noqa: E402

DICT = BASIC / 'words_817.txt'
SOURCES = Path(os.environ.get('SOURCES', '/home/user/AI-/.work/sources'))
REPLAY = os.environ.get('REPLAY_SOLVER', '/home/user/AI-/.work/measure/solver_v5_replay')
TABLE = os.environ.get('TABLE_SOLVER', '/home/user/AI-/.work/measure/solver_v5_table')
MAIN_DIR = os.environ.get('MAIN_DIR', '/home/user/AI-/.work/main_map')   # the existing route map's files
MIN_ALLOT = 5.0
KEEP = 2000000


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def root_result(proof):
    with gzip.open(proof, 'rt', encoding='utf-8') as f:
        head = json.loads(f.readline())
        last = None
        for line in f:
            if line.strip():
                last = line
    node = json.loads(last)
    assert node['id'] == head['root']
    return node['r']


class Budget:
    def __init__(self, total, per_case):
        self.total, self.per = total, per_case
        self.spent = 0.0
        self.reserved = 0.0
        self.cv = threading.Condition()
        self.log = []

    def take(self, name, cap=None):
        """seconds allotted to the next case, or None (not started)"""
        per = self.per if cap is None else min(self.per, cap)
        with self.cv:
            while True:
                if self.total <= 0:
                    return per
                avail = self.total - self.spent - self.reserved - 1.0   # 1 s margin: the solver may stop a few ms late
                if avail >= MIN_ALLOT:
                    a = min(per, avail)
                    self.reserved += a
                    self.log.append({'case': name, 'allotted': round(a, 3), 'at': time.strftime('%H:%M:%S')})
                    return a
                if self.reserved <= 0:
                    return None
                self.cv.wait()

    def give_back(self, allot, used):
        with self.cv:
            if self.total > 0:
                self.reserved -= allot
            self.spent += used
            self.cv.notify_all()


def main():
    cases_path, work = Path(sys.argv[1]), Path(sys.argv[2])
    rest = sys.argv[3:]
    o = {'--seconds': '600', '--budget': '0', '--jobs': '3', '--tt-mb': '1024', '--stuck-nodes': '200000', '--only': '', '--keep-state': '0',
         '--cumulative-cap': '0', '--budget-log': 'budget.json'}
    o.update({rest[i]: rest[i + 1] for i in range(0, len(rest), 2)})
    cases = json.loads(cases_path.read_text(encoding='utf-8'))['cases']
    if o['--only']:                                   # exactly these cases, in the order given
        by = {c['name']: c for c in cases}
        cases = [by[n] for n in o['--only'].split(',') if n]
    m = ModelV3(DICT.read_bytes(), 817)
    budget = Budget(float(o['--budget']), float(o['--seconds']))
    keep = o['--keep-state'] == '1'
    guide_lock = threading.Lock()
    work.mkdir(parents=True, exist_ok=True)

    def ensure_guide(c):
        g = Path(c['guide'])
        with guide_lock:
            if not (g / 'guide.json').exists():
                subprocess.run([sys.executable, str(HERE.parent / 'table_guide' / 'make_guide.py'), MAIN_DIR, c['guide_book'], str(g)],
                               check=True, capture_output=True, text=True)
        return g

    def one(c):
        d = work / c['name']
        d.mkdir(parents=True, exist_ok=True)
        cap, prior, earlier = None, 0.0, []
        if float(o['--cumulative-cap']) > 0 and (d / 'run.json').exists():
            old = json.loads((d / 'run.json').read_text(encoding='utf-8'))
            if old.get('accepted'):
                print(time.strftime('%H:%M:%S'), json.dumps({'name': c['name'], 'already_accepted': True}, ensure_ascii=False), flush=True)
                return
            if not old.get('untried'):
                k = 1
                while (d / f'run.{k}.json').exists():
                    k += 1
                (d / 'run.json').rename(d / f'run.{k}.json')
                for j in range(1, k + 1):
                    earlier.append(json.loads((d / f'run.{j}.json').read_text(encoding='utf-8')))
                prior = max([float(e['solver'].get('total_search_seconds') or e['solver'].get('seconds') or 0) for e in earlier]
                            + [sc.state_carried_seconds(d / 'state.tt') if (d / 'state.tt').exists() else 0.0])
                cap = float(o['--cumulative-cap']) - prior
                if cap < MIN_ALLOT:
                    rec = {'name': c['name'], 'position': c['position'], 'method': c['method'], 'accepted': False, 'untried': False,
                           'cap_reached': True, 'prior_search_seconds': prior, 'earlier_runs': len(earlier),
                           'note': f'not continued: its {prior:.3f} s of search already reach --cumulative-cap'}
                    (d / 'run.json').write_text(json.dumps(rec, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
                    return
        allot = budget.take(c['name'], cap)
        if allot is None:
            rec = {'name': c['name'], 'position': c['position'], 'method': c['method'], 'accepted': False, 'untried': True,
                   'note': 'not started: the search budget of this call was used up'}
            (d / 'run.json').write_text(json.dumps(rec, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
            print(time.strftime('%H:%M:%S'), json.dumps({'name': c['name'], 'word': c['word'], 'untried': True}, ensure_ascii=False), flush=True)
            return
        (d / 'pos.json').write_bytes(json.dumps(c['position'], ensure_ascii=False).encode('utf-8'))
        cur, k, _ = m.position(c['position'])
        (d / 'in.txt').write_bytes(m.numeric_input(cur, k))
        proof, state = d / 'proof.v4.gz', d / 'state.tt'
        if proof.exists():
            proof.unlink()
        common = ['--seconds', f'{allot:.3f}', '--tt-mb', o['--tt-mb'], '--threads', '1', '--proof-format', 'v4', '--proof', str(proof)]
        if keep:
            common += ['--tt-save', str(state), '--checkpoint-seconds', '60', '--tt-save-max', str(KEEP)]
            if state.exists():
                common += ['--tt-load', str(state)]
        if c['method'] == 'replay':
            src = Path(c.get('source_path') or SOURCES / c['source'] / 'proof.v4.gz')
            cmd = [REPLAY, str(d / 'in.txt'), '--replay', str(src), '--replay-stuck-nodes', o['--stuck-nodes'], '--emit-check', '0'] + common
            extra = {'source_path': str(src), 'source_proof_sha256': sha(src), 'solver_sha256': sha(REPLAY)}
        elif c['method'] == 'table':
            g = ensure_guide(c)
            cmd = [TABLE, str(d / 'in.txt'), '--table-guide', str(g), '--table-root', c.get('expect', 'W'),
                   '--replay-stuck-nodes', o['--stuck-nodes'], '--emit-check', '0'] + common
            extra = {'guide': json.loads((g / 'guide.json').read_text(encoding='utf-8')), 'solver_sha256': sha(TABLE)}
        else:
            cmd = [sc.SOLVER, str(d / 'in.txt')] + common
            extra = {'solver_sha256': sha(sc.SOLVER)}
        t0 = time.time()
        try:
            r = subprocess.run(cmd, capture_output=True, text=True)
            sol = sc.parse_solver_output(r.stdout, r.returncode)
        finally:
            used = 0.0
            try:
                used = float(sol.get('seconds') or 0)
            except Exception:
                used = allot
            budget.give_back(allot, used)
        wall = time.time() - t0
        rec = {'name': c['name'], 'position': c['position'], 'method': c['method'], 'source': c.get('source'),
               'started': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(t0)), 'allotted_seconds': round(allot, 3),
               'prior_search_seconds': round(prior, 6), 'earlier_runs': len(earlier), 'resumed_from_state': '--tt-load' in cmd,
               'cmd': cmd[1:], 'solver_wall_seconds': round(wall, 2), 'solver': sol, **extra}
        if proof.exists():
            want = root_result(proof)
            t1 = time.time()
            ok, v = sc.verify(DICT, 817, d / 'pos.json', proof, d / 'in.txt', want, sol.get('proof_nodes') or 0)
            rec.update(result_for_mover=want, verify_wall_seconds=round(time.time() - t1, 2), accepted=ok,
                       verify={x: v.get(x) for x in ('verified', 'result_for_player_to_move', 'proof_sha256', 'input_sha256',
                                                     'position_sha256', 'dictionary_sha256', 'state_storage', 'verifier',
                                                     'exit_code', 'elapsed_seconds', 'error')},
                       acceptance=v.get('acceptance'), proof_bytes=proof.stat().st_size)
        else:
            rec.update(accepted=False, note='no certificate: not solved within its allotted search time')
        if keep:
            if rec['accepted'] and state.exists():
                state.unlink()
            rec['state_kept'] = str(state) if state.exists() else None
        (d / 'run.json').write_text(json.dumps(rec, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
        line = {'name': c['name'], 'word': c['word'], 'accepted': rec['accepted'], 'mover': rec.get('result_for_mover'),
                'allot': round(allot, 3), 'search': sol.get('seconds'), 'total_search': sol.get('total_search_seconds'), 'proof_s': sol.get('emit_seconds'),
                'verify_s': rec.get('verify_wall_seconds'), 'proof_nodes': sol.get('proof_nodes')}
        print(time.strftime('%H:%M:%S'), json.dumps(line, ensure_ascii=False), flush=True)

    with ThreadPoolExecutor(int(o['--jobs'])) as ex:
        list(ex.map(one, cases))
    (work / o['--budget-log']).write_text(json.dumps({'budget': budget.total, 'per_case': budget.per, 'search_spent': round(budget.spent, 3),
                                                  'allotments': budget.log}, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(json.dumps({'budget': budget.total, 'search_spent': round(budget.spent, 3)}))


if __name__ == '__main__':
    main()
