#!/usr/bin/env python3
"""Write results/NAME/README_KO.md for a solving batch of one kind of run (replay only, or direct search only),
from the records of that folder. Also writes TABLES.md (replay_table.py) and copies NAME_cases.json to cases.json.

usage: replay_batch_readme.py NAME "한 줄 설명"
Reads results/NAME/*.phase1.json, archive/INDEX.json and sources/*/prep.json. Everything in the README is
computed from those files; nothing is typed in by hand except the one-line description.
"""
from collections import defaultdict
import json
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from replay_table import run_seconds  # noqa: E402
KO = {'lose': '지는 수', 'win': '이기는 수'}


def main():
    name, desc = sys.argv[1], sys.argv[2]
    res = HERE / 'results' / name
    recs = [json.loads(p.read_text(encoding='utf-8')) for p in sorted(res.glob('*.phase1.json'))]
    index = json.loads((res / 'archive' / 'INDEX.json').read_text(encoding='utf-8'))
    words = {t['id']: '·'.join(t['words']) for t in json.loads((HERE / 'targets.json').read_text(encoding='utf-8'))['targets']}
    kind = 'replay' if recs[0].get('replay') else 'direct'      # the one kind of run this batch made
    assert all(r.get(kind) for r in recs), 'a batch with both kinds of run is a comparison: write its README by hand'
    for r in recs:
        r['run'] = r[kind]
    dec = [r for r in recs if r['decided']]
    und = [r for r in recs if not r['decided']]

    def tot(x):
        return run_seconds(x)

    L = [f'# {"재생 풀이" if kind == "replay" else "직접 탐색"} 묶음: {name}', '', desc, '']
    L += ['## 결과', '',
          f'- 첫 수 {len(recs)}개 중 **{len(dec)}개 확정**(지는 수 {sum(r["first_move"] == "lose" for r in dec)}, '
          f'이기는 수 {sum(r["first_move"] == "win" for r in dec)}), 미확정 {len(und)}개.',
          '- 확정은 모두 그 국면의 v4 증명서가 C++ `verify_v4`의 수락 조건을 통과한 것입니다.',
          f'- 걸린 시간 합계(계산기 + 검증): {sum(tot(r["run"]) for r in recs):,.0f}초. '
          f'탐색 {sum(r["run"]["search_seconds"] or 0 for r in recs):,.0f}초, '
          f'증명서 쓰기 {sum(r["run"].get("proof_seconds") or 0 for r in dec):,.0f}초, '
          f'검증 {sum(r["run"].get("verify_seconds") or 0 for r in dec):,.0f}초.',
          f'- 재시작으로 끊긴 실행 {sum(r["run"]["interrupted_runs"] for r in recs)}개, '
          f'증명서를 못 썼거나 거부된 실행 {sum(1 for r in recs if r["run"].get("problem"))}개.']
    cut = [words[r['id']] for r in recs if r['run'].get('spent_is_lower_bound')]
    if cut:
        L += [f'- 재시작으로 끊긴 실행({", ".join(cut)})은 저장해 둔 상태에서 남은 시간만 이어 돌렸습니다. '
              '마지막 저장 뒤 끊길 때까지 한 탐색(저장 간격 60초 이하)은 잃었고, 위 합계에 들어 있지 않습니다.']
    L.append('')
    by = defaultdict(list)
    for r in dec:
        by[r['source']['syllable']].append(r)
    L += ['## 확정된 제시 단어', '',
          '음절 t를 제시한 단어별 판정입니다(용어: `../../TERMS_KO.md`). **지는 수 = 그 단어를 낸 쪽(제시자) 패, t를 받은 쪽 승. '
          '이기는 수 = 그 단어를 낸 쪽 승, t를 받은 쪽 패.** \'받은 쪽의 승리수\'는 t를 받은 쪽이 이기는 수입니다.', '',
          '| 제시한 음절 t | 지는 수 (제시자 패) | 받은 쪽의 승리수 | 이기는 수 (제시자 승) |', '|---|---|---|---|']
    for s in sorted(by):
        lose = sorted(words[r['id']] for r in by[s] if r['first_move'] == 'lose')
        win = sorted(words[r['id']] for r in by[s] if r['first_move'] == 'win')
        rep = sorted({w for r in by[s] if r['first_move'] == 'lose' for w in (r.get('reply') or [])})
        L.append(f'| {s} | {", ".join(lose)} | {"·".join(rep)} | {", ".join(win)} |')
    L.append('')
    if und:
        L += ['## 미확정', '', '| 제시 단어 | 제시한 음절 | 쓴 탐색 시간(초) | 탐색 국면 | 막힌 곳 |', '|---|---|---:|---:|---:|']
        for r in und:
            rp = r['run'].get('replay') or {}
            stuck = sum(rp.get(k, 0) for k in ('stuck_old_leaf', 'stuck_witness_gone', 'stuck_witness_static', 'stuck_witness_refuted', 'stuck_new_move'))
            L.append(f'| {words[r["id"]]} | {r["source"]["syllable"]} | {r["run"]["search_seconds"] or 0:,.0f} | {r["run"].get("mid_calls") or 0:,} | '
                     f'{f"{stuck:,}" if kind == "replay" else "-"} |')
        L.append('')
    slow = sorted(dec, key=lambda r: -tot(r['run']))[:8]
    L += ['## 오래 걸린 것', '', '| 제시 단어 | 제시한 음절 | 전체(초) | 탐색 · 증명서 쓰기 · 검증 | 증명 국면 | 막힌 곳 탐색 |', '|---|---|---:|---|---:|---:|']
    for r in slow:
        b = r['run']
        L.append(f'| {words[r["id"]]} | {r["source"]["syllable"]} | {tot(b):,.1f} | {b["search_seconds"]:.1f} · {b["proof_seconds"]:.1f} · '
                 f'{b["verify_seconds"]:.1f} | {b["proof_nodes"]:,} | {f"{(b.get("replay") or {}).get("local_calls", 0):,}" if kind == "replay" else "-"} |')
    L.append('')
    srcs = sorted((res / 'sources').glob('*/prep.json')) if (res / 'sources').exists() else []
    if srcs:
        L += ['## 이번에 준비한 원본 증명서', '', '| 음절 | 받으면 | 탐색(초) | 증명 국면 | 증명서 쓰기(초) | 검증(초) | 이 묶음에서 쓴 첫 수 |', '|---|---|---:|---:|---:|---:|---:|']
        ts = tp = tv = 0
        for p in srcs:
            j = json.loads(p.read_text(encoding='utf-8'))
            ts += j['search_seconds_spent']; tp += j['proof_seconds'] or 0; tv += j['verify_seconds'] or 0
            L.append(f'| {j["syllable"]} | {"승" if j["result_for_receiver"] == "W" else "패"} | {j["search_seconds_spent"]:,.1f}'
                     f'{" (하한)" if j.get("spent_is_lower_bound") else ""} | {j["proof_nodes"]:,} | {j["proof_seconds"]:.1f} | {j["verify_seconds"]:.1f} | '
                     f'{len(by.get(j["syllable"], []))} |')
        L += [f'| **합계** | | **{ts:,.0f}** | | **{tp:,.0f}** | **{tv:,.0f}** | |', '',
              '- 원본 증명서도 모두 검증기를 통과했습니다. 원본은 힌트일 뿐이고, 각 첫 수는 자기 국면의 증명서로 확정합니다.', '']
    rel = index.get('release')
    files = index['certificate_files']
    L += ['## 보관', '']
    if rel:
        L += [f'- 증명서 파일 {files}개({index["certificate_bytes"] / 1e6:,.0f}MB)는 저장소에 넣지 않습니다. GitHub 릴리스 `{rel["tag"]}`의 첨부파일로 둡니다.',
              ('- 상태: **릴리스에 올렸습니다.** 올린 파일을 모두 다시 내려받아 sha256이 색인과 같음을 확인했습니다'
               f'({rel.get("checked", "")}). 주소: {rel["url"]}' if rel['status'].startswith('uploaded') else
               '- 상태: 아직 릴리스에 올리지 않았습니다. 파일은 세션 브랜치의 `release_staging/`에 있습니다.'
               if rel['status'].startswith('staged') else f'- 상태: {rel["status"]}'),
              '- 저장소에는 국면(`archive/<사례>/pos.json`), 입력(`in.txt`), 보관본을 다시 검증한 기록(`verify.json`), 그리고 파일마다 sha256과 주소를 적은 색인(`archive/INDEX.json`)이 있습니다.',
              f'- 다시 확인하려면: `python3 replay_archive.py {name} --check-release 1` (주소마다 다시 내려받아 sha256 비교).', '']
    elif files:
        L += [f'- 증명서 파일 {files}개는 `archive/certs/`에 있습니다.', '']
    else:
        L += ['- 확정된 첫 수가 없어 보관할 증명서가 없습니다. 실행 기록은 `*.phase1.json`에 있습니다.', '']
    L += ['## 조건', '',
          (f'- 재생만 돌렸습니다(`--kinds replay --emit-check 0`). 한도 {recs[0]["seconds_limit"]:.0f}초, 저장표 {recs[0]["tt_mb"]}MB, 막힌 곳 예산 {recs[0]["stuck_nodes"]:,}국면, 동시에 {recs[0].get("jobs", 1)}개.'
           if kind == 'replay' else
           f'- 직접 탐색만 돌렸습니다(`--kinds direct`: 기본 계산기 `solver_v5`, 원본 증명서를 쓰지 않음). 한도 {recs[0]["seconds_limit"]:.0f}초, 저장표 {recs[0]["tt_mb"]}MB, 동시에 {recs[0].get("jobs", 1)}개.'),
          '- 대상은 실행 전에 `cases.json`으로 고정해 먼저 커밋했습니다.',
          f'- 실행 파일 sha256 앞 16자: ' + (f'재생 계산기 `{recs[0]["replay_solver_sha256"][:16]}`' if kind == 'replay' else f'계산기 `{recs[0]["solver_sha256"][:16]}`')
          + f', 검증기 `{recs[0]["verifier_sha256"][:16]}`.',
          '- 사례별 숫자는 `TABLES.md`와 `*.phase1.json`에 있습니다.', '']
    (res / 'README_KO.md').write_text('\n'.join(L), encoding='utf-8')
    with open(res / 'TABLES.md', 'w', encoding='utf-8') as f:
        subprocess.run([sys.executable, str(HERE / 'replay_table.py'), name], stdout=f, check=True)
    if (HERE / f'{name}_cases.json').exists():
        shutil.copyfile(HERE / f'{name}_cases.json', res / 'cases.json')
    print(res / 'README_KO.md', len(L), 'lines')


if __name__ == '__main__':
    main()
