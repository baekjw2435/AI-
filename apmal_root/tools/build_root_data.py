#!/usr/bin/env python3
"""앞말잇기 루트 확정 결과로 site/data.json(보호막 도구가 읽는 루트 결과)과 RESULTS_KO.md를 만든다.

usage: python3 apmal_root/tools/build_root_data.py

읽는 것: words_534.txt, syllables_113.txt, results/roots/res/R*.json, results/roots/proof/R*.v4.gz,
        (30분 안에 안 끝나 나눠 푼 루트) results/roots_split/plan.json, res/, pos/, proof/
루트마다 둘 중 하나여야 하고, 아니면 멈춘다.
  (가) 루트 국면 자체의 solver_v5 증명서를 verify_v4가 수락 조건 8개로 수락.
  (나) 나눠 푼 국면들의 증명서가 모두 verify_v4에 수락되고, 한 수 앞 보기로 루트 결과가 나옴:
       여기서 낼 수 있는 수를 ModelV3로 다시 세어(plan.json을 믿지 않음) 승이면 상대 패인 수 하나, 패면 모든 수가
       상대 승인지 확인한다. 쓴 국면 목록을 results/roots_split/cert/R###.json(합친 증명서)에 남긴다.

data.json (eoinjeong_root/site/data.json과 같은 뜻, 단어는 뒤집힌 채)
  words      뒤집은 루트 단어 534개(사전 순, 번호 = 단어 번호). 앞말잇기 원래 단어 = 거꾸로 읽기
  syllables  [{"s": 음절, "r": "W"|"L", "v": 꼭짓점}] — r은 아무 단어도 안 쓴 채 그 음절을 받은 쪽의 결과
  model      ModelV3 꼭짓점 수, 묶음 [[시작, 끝, 단어 수]], 단어별 묶음
  certs      [{"path": 저장소 안 증명서 경로, "sha256": …}]
  nodes      "<음절 번호> <W|L><증명서 번호>"
"""
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parent
sys.path.insert(0, str(REPO / 'guopsaem_root' / 'verifier_v3'))
from verify_v3 import ModelV3  # noqa: E402


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def rev(w):
    return w[::-1]


def split_cert(m, rid, s):
    """나눠 푼 루트: 한 수 앞 보기로 결과를 다시 확인하고 합친 증명서를 쓴다. (결과, 경로)."""
    sd = HERE / 'results' / 'roots_split'
    plan = json.loads((sd / 'plan.json').read_text(encoding='utf-8'))
    assert plan['dictionary_sha256'] == sha(HERE / 'words_534.txt')
    R = plan['roots'][rid]
    assert R['syllable'] == s
    leaf = {}                                   # 자리(단어들) -> (국면, 자리 번호)
    for uid, u in R['units'].items():
        for j, h in enumerate(u['positions']):
            leaf['/'.join(h)] = (uid, j)
    used = []

    def legal(h):
        cur, _, usedw = m.position({'initial_syllable': s, 'history': h})
        return [w for w in m.words if w[0] in m.keys[cur] and w not in usedw]

    def unit_ok(h, want):
        uid, j = leaf['/'.join(h)]
        f = sd / 'res' / f'{uid}.json'
        if not f.exists():
            return False
        r = json.loads(f.read_text(encoding='utf-8'))
        if not (r.get('accepted') and r.get('value') == want):
            return False
        posf, proof, inf = sd / 'pos' / f'{uid}_{j}.json', sd / 'proof' / f'{uid}.v4.gz', sd / 'in' / f'{uid}.txt'
        assert json.loads(posf.read_text(encoding='utf-8')) == {'initial_syllable': s, 'history': h}
        vr = r['verify'][j]
        assert vr['accepted'] and all(vr['verify']['acceptance'].values()) and vr['position_sha256'] == sha(posf)
        assert vr['verify']['result_for_player_to_move'] == want
        assert sha(proof) == r['proof_sha256'] and sha(inf) == r['input_sha256'] == R['units'][uid]['input_sha256']
        assert r['dictionary_sha256'] == sha(HERE / 'words_534.txt')
        used.append({'history': h, 'unit': uid, 'value': want, 'position': str(posf.relative_to(REPO)),
                     'position_sha256': sha(posf), 'proof': str(proof.relative_to(REPO)), 'proof_sha256': r['proof_sha256'],
                     'input_sha256': r['input_sha256']})
        return True

    def ok(h, want):                            # 둘 차례인 쪽의 결과가 want인가
        k = '/'.join(h)
        if k in leaf:                           # 나눈 끝자리: 그 국면의 증명서로
            return unit_ok(h, want)
        if k not in R['nodes']:
            return False
        ws = legal(h)                           # plan.json이 아니라 사전에서 다시 센 수
        if not ws:
            return False
        for w in ws:
            mark = len(used)
            good = ok(h + [w], 'L' if want == 'W' else 'W')
            if want == 'W' and good:
                return True
            if want == 'W':
                del used[mark:]
            elif not good:
                return False
        return want == 'L'

    for v in ('W', 'L'):
        used.clear()
        if ok([], v):
            break
    else:
        raise AssertionError(f'{rid} {s}: 나눠 푼 국면으로도 확정 아님')
    out = sd / 'cert' / f'{rid}.json'
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({'format': 'apmal-root-split-cert-1', 'root': rid, 'syllable': s, 'value': v,
                               'rule': '둘 차례인 쪽: 다음 국면 중 하나라도 패면 승, 모두 승이면 패(낼 수 있는 수는 ModelV3로 다시 셈)',
                               'dictionary_sha256': sha(HERE / 'words_534.txt'), 'units': used},
                              ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    return v, out


def main():
    words = (HERE / 'words_534.txt').read_text(encoding='utf-8').split()
    syls = (HERE / 'syllables_113.txt').read_text(encoding='utf-8').split()
    m = ModelV3((HERE / 'words_534.txt').read_bytes(), 534)
    assert m.words == words and not any(m.shared)
    res = HERE / 'results' / 'roots' / 'res'
    certs, nodes, rows, how = [], [], [], {}
    for i, s in enumerate(syls, 1):
        r = json.loads((res / f'R{i:03d}.json').read_text(encoding='utf-8'))
        assert r['position'] == {'initial_syllable': s, 'history': []}, r['id']
        assert r['dictionary_sha256'] == sha(HERE / 'words_534.txt')
        if r.get('accepted'):
            assert all(r['verify']['acceptance'].values()), f"{r['id']} {s}: 확정 아님"
            proof = HERE / 'results' / 'roots' / 'proof' / f'R{i:03d}.v4.gz'
            assert sha(proof) == r['proof_sha256'], f'{proof} 해시가 다름'
            certs.append({'path': str(proof.relative_to(REPO)), 'sha256': r['proof_sha256']})
            v = r['result_for_player_to_move']
            how[s] = ('root', r['limit_seconds'])
        else:
            v, cpath = split_cert(m, r['id'], s)
            certs.append({'path': str(cpath.relative_to(REPO)), 'sha256': sha(cpath), 'kind': 'split'})
            how[s] = ('split', None)
        nodes.append(f"{i - 1} {v}{i - 1}")
        rows.append((s, v, r))
    model = {'vertices': len(m.keys), 'groups': [[sr[0], t, c] for (sr, t), c in zip(m.edges, m.full_counts)],
             'word_group': [m.word_group(w) for w in words]}
    data = {'format': 'apmal534-site-1', 'game': 'front',
            'note': '앞말잇기. 단어는 모두 뒤집혀 있음(뒤집으면 끝말잇기와 같은 규칙). 원래 단어 = 거꾸로 읽기.',
            'dictionary': 'apmal_root/words_534.txt', 'dictionary_sha256': sha(HERE / 'words_534.txt'),
            'words': words,
            'syllables': [{'s': s, 'r': v, 'v': m.vertex_of(s)} for s, v, _ in rows],
            'model': model, 'certs': certs, 'nodes': nodes}
    out = HERE / 'site' / 'data.json'
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False) + '\n', encoding='utf-8')

    # 사람이 읽는 표(원래 단어로): 받은 쪽 승/패, 승이면 이기는 첫 수 후보는 따로 계산하지 않았으므로 적지 않음
    route = {}
    for line in (HERE / 'reversed' / '루트단어_뒤집음.txt').read_text(encoding='utf-8').splitlines():
        if ' : ' in line:
            s, ws = line.split(' : ')
            route[s] = [rev(w) for w in ws.split(', ')]
    win = [s for s, v, _ in rows if v == 'W']
    lose = [s for s, v, _ in rows if v == 'L']
    tot = {k: round(sum(r[k] for _, _, r in rows if k in r), 1) for k in ('wall_solve_seconds', 'wall_verify_seconds')}
    n600 = sum(1 for x in how.values() if x == ('root', 600.0))
    n1200 = sum(1 for x in how.values() if x == ('root', 1200.0))
    nsplit = sum(1 for x in how.values() if x[0] == 'split')
    search = round(sum(r['solver'].get('seconds', 0) for _, _, r in rows), 2)
    method = {('root', 600.0): '루트 국면 그대로(10분 안)', ('root', 1200.0): '루트 국면 그대로(30분 안)',
              ('split', None): '첫 수별로 나눠서(묶음마다 6시간 안)'}
    md = [f'# 앞말잇기 루트 확정 결과 (표준사전, 루트 단어 534개)', '',
          f'- **113음절 모두 확정**: 아무 단어도 안 쓴 채 그 음절을 받았을 때 받은 쪽 **승 {len(win)}개, 패 {len(lose)}개**. 미확정 0.',
          '- 확정 = solver_v5 증명서를 verify_v4가 수락 조건 8개로 수락. 계산기는 4개까지 동시.',
          f'  - 루트 국면을 그대로 풀어 확정: 10분(600초) 안 {n600}개, 이어서 합계 30분 안 {n1200}개.',
          f'  - 30분 안에 안 끝난 {nsplit}개: 받은 쪽의 첫 수별로(필요하면 그 아래 수까지) 나눠 4코어에서 묶음마다 6시간 안에 풀고,'
          ' 나눈 국면마다 verify_v4 수락. 루트 결과는 한 수 앞 보기(다음 국면 하나라도 상대 패면 승, 모두 상대 승이면 패)로 합침'
          '(`results/roots_split/cert/`).',
          f'- 루트 국면 탐색 시간 합계 {search}초(나눠 푼 국면 제외).',
          '- "받는다" = 상대가 그 음절로 **시작하는** 단어를 냈고, 내가 그 음절(두음 포함)로 **끝나는** 루트 단어를 내야 하는 차례.', '',
          '## 받으면 이기는 음절 (받은 쪽 승)', '', ' '.join(win), '',
          '## 받으면 지는 음절 (받은 쪽 패)', '', ' '.join(lose), '',
          '## 음절별', '', '| 음절 | 받은 쪽 | 확정 방법 | 낼 수 있는 루트 단어(그 음절로 끝남) |', '|---|---|---|---|']
    for s, v, _ in rows:
        md.append(f"| {s} | {'승' if v == 'W' else '패'} | {method[how[s]]} | {', '.join(route[s])} |")
    md += ['', '짝 단어(서로 주고받는 짝 52쌍)는 음절 줄에 없고, 짝 줄의 단어로만 이어지는 음절(둬 따 엠 잡 죄 쭝 척 훼 흉)은 루트 음절이 아닙니다.', '',
           f'자료: `site/data.json`(sha256 `{sha(out)}`), 증명서 `results/roots/proof/`, 국면별 기록 `results/roots/res/`, '
           '나눠 푼 국면 `results/roots_split/`(plan.json, res/, proof/, cert/).']
    (HERE / 'RESULTS_KO.md').write_text('\n'.join(md) + '\n', encoding='utf-8')
    print(f'{out}: {len(rows)}음절 (승 {len(win)}, 패 {len(lose)}), sha256 {sha(out)}; 탐색 {search}s, 실행 {tot}')


if __name__ == '__main__':
    main()
