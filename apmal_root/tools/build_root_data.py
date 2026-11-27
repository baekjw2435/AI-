#!/usr/bin/env python3
"""앞말잇기 루트 확정 결과로 site/data.json(보호막 도구가 읽는 루트 결과)과 RESULTS_KO.md를 만든다.

usage: python3 apmal_root/tools/build_root_data.py

읽는 것: words_534.txt, syllables_113.txt, results/roots/res/R*.json, results/roots/proof/R*.v4.gz
모든 국면이 verify_v4 수락 조건 8개를 통과(accepted)했어야 하고, 하나라도 아니면 멈춘다.

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


def main():
    words = (HERE / 'words_534.txt').read_text(encoding='utf-8').split()
    syls = (HERE / 'syllables_113.txt').read_text(encoding='utf-8').split()
    m = ModelV3((HERE / 'words_534.txt').read_bytes(), 534)
    assert m.words == words and not any(m.shared)
    res = HERE / 'results' / 'roots' / 'res'
    certs, nodes, rows = [], [], []
    for i, s in enumerate(syls, 1):
        r = json.loads((res / f'R{i:03d}.json').read_text(encoding='utf-8'))
        assert r['position'] == {'initial_syllable': s, 'history': []}, r['id']
        assert r['accepted'] and all(r['verify']['acceptance'].values()), f"{r['id']} {s}: 확정 아님"
        proof = HERE / 'results' / 'roots' / 'proof' / f'R{i:03d}.v4.gz'
        assert sha(proof) == r['proof_sha256'], f'{proof} 해시가 다름'
        assert r['dictionary_sha256'] == sha(HERE / 'words_534.txt')
        certs.append({'path': str(proof.relative_to(REPO)), 'sha256': r['proof_sha256']})
        nodes.append(f"{i - 1} {r['result_for_player_to_move']}{i - 1}")
        rows.append((s, r['result_for_player_to_move'], r))
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
    search = round(sum(r['solver'].get('seconds', 0) for _, _, r in rows), 2)
    slow = max(rows, key=lambda x: x[2]['solver'].get('seconds', 0))
    md = [f'# 앞말잇기 루트 확정 결과 (표준사전, 루트 단어 534개)', '',
          f'- **113음절 모두 확정**: 아무 단어도 안 쓴 채 그 음절을 받았을 때 받은 쪽 **승 {len(win)}개, 패 {len(lose)}개**. 미확정 0.',
          '- 확정 = solver_v5 증명서를 verify_v4가 수락 조건 8개로 수락. 국면마다 따로 풀었습니다(탐색 한도 600초, 표 1GB, 4개 동시).',
          f'- 탐색 시간 합계 {search}초(가장 오래 걸린 음절: {slow[0]} {slow[2]["solver"].get("seconds")}초).',
          '- "받는다" = 상대가 그 음절로 **시작하는** 단어를 냈고, 내가 그 음절(두음 포함)로 **끝나는** 루트 단어를 내야 하는 차례.', '',
          '## 받으면 이기는 음절 (받은 쪽 승)', '', ' '.join(win), '',
          '## 받으면 지는 음절 (받은 쪽 패)', '', ' '.join(lose), '',
          '## 음절별', '', '| 음절 | 받은 쪽 | 낼 수 있는 루트 단어(그 음절로 끝남) |', '|---|---|---|']
    for s, v, _ in rows:
        md.append(f"| {s} | {'승' if v == 'W' else '패'} | {', '.join(route[s])} |")
    md += ['', '짝 단어(서로 주고받는 짝 52쌍)는 음절 줄에 없고, 짝 줄의 단어로만 이어지는 음절(둬 따 엠 잡 죄 쭝 척 훼 흉)은 루트 음절이 아닙니다.', '',
           f'자료: `site/data.json`(sha256 `{sha(out)}`), 증명서 `results/roots/proof/`, 국면별 기록 `results/roots/res/`.']
    (HERE / 'RESULTS_KO.md').write_text('\n'.join(md) + '\n', encoding='utf-8')
    print(f'{out}: {len(rows)}음절 (승 {len(win)}, 패 {len(lose)}), sha256 {sha(out)}; 탐색 {search}s, 실행 {tot}')


if __name__ == '__main__':
    main()
