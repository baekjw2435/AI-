#!/usr/bin/env python3
"""Write results/REPLAY_BATCHES_KO.md: one row per replay experiment/batch, computed from the records.

usage: replay_progress.py
Reads results/replay*/*.phase1.json, results/replay*/archive/INDEX.json, results/replay*/sources/*/prep.json,
targets.json and results/summary.json. Nothing in the output is typed in by hand.
"""
from collections import defaultdict
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent


def main():
    res = HERE / 'results'
    doc = json.loads((HERE / 'targets.json').read_text(encoding='utf-8'))
    summ = json.loads((res / 'summary.json').read_text(encoding='utf-8'))
    words = {t['id']: '·'.join(t['words']) for t in doc['targets']}
    known = {t['id'] for t in doc['targets'] if t['existing']['evidence'] == 'verified'}

    def again(tid, batch):  # verified before this batch: by the earlier study, or first decided in another batch
        first = next((e['batch'] for e in summ.get(tid, []) if e['decided']), batch)
        return tid in known or first != batch
    batches = sorted((p for p in res.glob('replay*') if (p / 'archive' / 'INDEX.json').exists()),
                     key=lambda p: int(re.sub(r'\D', '', p.name) or 0))
    L = ['# 재생으로 푼 묶음 정리', '',
         '이 파일은 `replay_progress.py`가 `results/replay*/`와 `results/direct*/`의 기록에서 만듭니다. 직접 고치지 마세요.', '',
         '- 확정은 모두 그 국면의 v4 증명서가 C++ `verify_v4`의 수락 조건을 통과한 것입니다.',
         '- 시간은 재생 실행만 더한 값입니다(계산기 + 검증). 원본 증명서 준비 시간은 따로 적습니다.',
         '- 묶음 1·2는 직접 탐색과 비교한 실험입니다. 여기에는 재생 쪽 숫자만 적습니다.', '',
         '| 묶음 | 첫 수 | 확정 | 지는 수 | 이기는 수 | 미확정 | 재생 시간(초) | 새 원본 | 원본 준비(초) | 증명서 파일 | 크기(MB) | 증명서 위치 |',
         '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|']
    T = defaultdict(float)
    wins, unds, staged, lows = [], [], [], []
    for b in batches:
        recs = [json.loads(p.read_text(encoding='utf-8')) for p in sorted(b.glob('*.phase1.json'))]
        idx = json.loads((b / 'archive' / 'INDEX.json').read_text(encoding='utf-8'))
        # experiments 1 and 2 also ran direct search; a case there counts as decided by replay only if the replay run decided it
        rep = [r for r in recs if r.get('replay')]
        dec = [r for r in rep if r['replay'].get('decided', r['decided'])]
        und = [r for r in rep if r not in dec]
        lose = sum(r['first_move'] == 'lose' for r in dec)
        win = sum(r['first_move'] == 'win' for r in dec)
        secs = sum(r['replay']['solver_wall_seconds'] + (r['replay'].get('verify_seconds') or 0) for r in rep)
        preps = [json.loads(p.read_text(encoding='utf-8')) for p in sorted((b / 'sources').glob('*/prep.json'))] if (b / 'sources').exists() else []
        prep_s = sum(j['search_seconds_spent'] + (j['proof_seconds'] or 0) + (j['verify_seconds'] or 0) for j in preps)
        lower = any(j.get('spent_is_lower_bound') for j in preps)
        lows += [f'{b.name}의 {j["syllable"]}' for j in preps if j.get('spent_is_lower_bound')]
        rel = idx.get('release')
        if rel:
            where = f'릴리스 `{rel["tag"]}`' + (' (확인됨)' if rel['status'].startswith('uploaded') else ' (**아직 안 올림**)')
            if not rel['status'].startswith('uploaded'):
                staged.append((rel['tag'], idx['certificate_files'], idx['certificate_bytes']))
        else:
            where = f'저장소 `results/{b.name}/archive/certs/`'
        L.append(f'| {b.name} | {len(rep)} | {len(dec)} | {lose} | {win} | {len(und)} | {secs:,.0f} | {len(preps)} | '
                 f'{prep_s:,.0f}{" 이상" if lower else ""} | {idx["certificate_files"]} | {idx["certificate_bytes"] / 1e6:,.0f} | {where} |')
        for k, v in (('n', len(rep)), ('dec', len(dec)), ('lose', lose), ('win', win), ('und', len(und)), ('secs', secs),
                     ('src', len(preps)), ('prep', prep_s), ('files', idx['certificate_files']), ('bytes', idx['certificate_bytes'])):
            T[k] += v
        wins += [(b.name, words[r['id']] + (' (이미 검증된 수를 다시 확인)' if again(r['id'], b.name) else ''), r['source']['syllable'])
                 for r in dec if r['first_move'] == 'win']
        unds += [(b.name, r['id'], words[r['id']], r['source']['syllable'], r['replay']) for r in und]
    L.append(f'| **합계** | {T["n"]:.0f} | {T["dec"]:.0f} | {T["lose"]:.0f} | {T["win"]:.0f} | {T["und"]:.0f} | {T["secs"]:,.0f} | {T["src"]:.0f} | '
             f'{T["prep"]:,.0f} 이상 | {T["files"]:.0f} | {T["bytes"] / 1e6:,.0f} | |')
    L.append('')
    # batches that ran direct search only (first moves the replay could not decide)
    dbatches = sorted((p for p in res.glob('direct*') if (p / 'archive' / 'INDEX.json').exists()),
                      key=lambda p: int(re.sub(r'\D', '', p.name) or 0))
    direct_runs = defaultdict(list)     # id -> [(batch, run record)] : every direct-search run of a first move
    for b in batches + dbatches:
        for p in sorted(b.glob('*.phase1.json')):
            r = json.loads(p.read_text(encoding='utf-8'))
            if r.get('direct'):
                direct_runs[r['id']].append((b.name, r))
    if dbatches:
        L += ['직접 탐색만 돌린 묶음(재생이 못 푼 첫 수):', '',
              '| 묶음 | 첫 수 | 확정 | 지는 수 | 이기는 수 | 미확정 | 시간(초) | 증명서 파일 | 크기(MB) | 증명서 위치 |',
              '|---|---:|---:|---:|---:|---:|---:|---:|---:|---|']
        for b in dbatches:
            recs = [json.loads(p.read_text(encoding='utf-8')) for p in sorted(b.glob('*.phase1.json'))]
            idx = json.loads((b / 'archive' / 'INDEX.json').read_text(encoding='utf-8'))
            dec = [r for r in recs if r['decided']]
            secs = sum(r['direct']['solver_wall_seconds'] + (r['direct'].get('verify_seconds') or 0) for r in recs)
            rel = idx.get('release')
            if rel:
                where = f'릴리스 `{rel["tag"]}`' + (' (확인됨)' if rel['status'].startswith('uploaded') else ' (**아직 안 올림**)')
                if not rel['status'].startswith('uploaded') and idx['certificate_files']:
                    staged.append((rel['tag'], idx['certificate_files'], idx['certificate_bytes']))
            else:
                where = f'저장소 `results/{b.name}/archive/certs/`'
            L.append(f'| {b.name} | {len(recs)} | {len(dec)} | {sum(r["first_move"] == "lose" for r in dec)} | {sum(r["first_move"] == "win" for r in dec)} | '
                     f'{len(recs) - len(dec)} | {secs:,.0f} | {idx["certificate_files"]} | {idx["certificate_bytes"] / 1e6:,.0f} | {where} |')
            wins += [(b.name + ' (직접 탐색)', words[r['id']], r['source']['syllable']) for r in dec if r['first_move'] == 'win']
        L.append('')
    L += ['- 같은 첫 수를 두 묶음에서 돌린 경우가 있어, 확정 합계는 새로 확정된 첫 수의 수와 다를 수 있습니다. 정확한 수는 `TARGETS_KO.md`에 있습니다.',
          "- 원본 준비의 '이상'은 재시작으로 잃은 계산이 있어 하한이라는 뜻입니다" + (f'({", ".join(lows)}).' if lows else '.'), '']
    left = [t for t in doc['targets'] if t['existing']['evidence'] != 'verified' and not any(e['decided'] for e in summ.get(t['id'], []))]
    by = defaultdict(int)
    for t in left:
        by[t['words'][0][-1]] += 1
    L += ['## 아직 미검증인 첫 수', '', f'- **{len(left)}개**가 남았습니다. 넘겨주는 음절별: ' +
          ', '.join(f'{s} {n}' for s, n in sorted(by.items(), key=lambda x: (-x[1], x[0]))), '']
    if unds:
        def far(x):     # where an undecided run stood when it stopped
            return f'{x["search_seconds"] or 0:,.0f}초' + (f', pn {x["end_pn"]:,} / dn {x["end_dn"]:,}' if 'end_pn' in x else '')

        L += ['## 재생이 한도 안에 못 푼 첫 수', '',
              '| 재생 묶음 | 첫 수 | 넘겨준 음절 | 재생이 멈춘 곳 | 직접 탐색 | 지금 |', '|---|---|---|---|---|---|']
        seen = set()
        n_left = 0
        for bn, tid, w, s, rr in unds:
            if tid in seen:
                continue
            seen.add(tid)
            d = [f'{dn}: ' + ('확정' if r['direct']['decided'] else f'미확정({far(r["direct"])})') for dn, r in direct_runs.get(tid, [])]
            first = next((e for e in summ.get(tid, []) if e['decided']), None)
            now = '미확정' if first is None else ('**지는 수**' if first['first_move'] == 'lose' else '**이기는 수**') + f' ({first["batch"]})'
            n_left += first is None
            L.append(f'| {bn} | {w} | {s} | {far(rr)} | {", ".join(d) if d else "안 해 봄"} | {now} |')
        L += ['', f'- 이 가운데 지금도 미확정인 것은 {n_left}개입니다.',
              '- pn·dn은 탐색이 멈출 때 뿌리의 증명수·반증수입니다. pn이 작으면 "그 첫 수가 지는 수"라는 증명에, dn이 작으면 "이기는 수"라는 증명에 가까웠다는 뜻입니다. '
              '더 오래 돌릴 대상을 고르는 참고일 뿐이고, 판정이 아닙니다.', '']
    if wins:
        L += ['## 확정된 이기는 첫 수 (묶음 1부터)', '', '| 묶음 | 첫 수 | 넘겨준 음절 |', '|---|---|---|']
        L += [f'| {bn} | {w} | {s} |' for bn, w, s in wins]
        L.append('')
    if staged:
        L += ['## 아직 릴리스에 올리지 못한 증명서', '',
              '| 릴리스 태그 | 파일 | 크기(MB) |', '|---|---:|---:|']
        L += [f'| `{t}` | {n} | {b / 1e6:,.0f} |' for t, n, b in staged]
        L += ['', '- 파일은 세션 브랜치 `ccr-e9c317a6-opqe7c`의 `release_staging/<태그>/`에 있습니다. 그 폴더의 `README_KO.md`에 올리는 법이 있습니다.',
              '- 올린 뒤 `python3 replay_archive.py <묶음> --check-release 1`로 다시 내려받아 sha256을 확인합니다.', '']
    (res / 'REPLAY_BATCHES_KO.md').write_text('\n'.join(L), encoding='utf-8')
    print(res / 'REPLAY_BATCHES_KO.md', len(L), 'lines')


if __name__ == '__main__':
    main()
