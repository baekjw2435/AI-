#!/usr/bin/env python3
"""Collect batch results and rebuild the target documents of the 817 'other first moves' study.

usage: report.py [NAME=WORKDIR ...]
  NAME=WORKDIR  copy WORKDIR/<pick>/phase*.json into results/NAME/ (the small result records; certificates
                stay in the work area, their sha256 is in the records)
Then, from targets.json and every record under results/:
  results/summary.json   one entry per position that was run: verdict (only if its certificate was accepted),
                         reply, certificate hash and size, search / certificate-writing / verification time
  TARGETS_KO.md          counts, how 438 and 374 were counted, per-syllable table
  TARGETS_LIST_KO.md     every first move of the 64 syllables with its status and evidence
A new verdict that contradicts an earlier verified verdict stops the script.
"""
from collections import Counter, defaultdict
import json
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
RES = HERE / 'results'
sys.path.insert(0, str(HERE))
from phase_time import phase_key, totals  # noqa: E402
KO = {'win': '승', 'lose': '패'}


def load_runs():
    runs = defaultdict(list)
    for f in sorted(RES.glob('*/*.phase*.json')):
        r = json.loads(f.read_text(encoding='utf-8'))
        r['batch'] = f.parent.name
        runs[r['id']].append(r)
    return runs


def summarize(runs):
    out = {}
    for tid, rs in runs.items():
        by_batch = defaultdict(list)
        for r in rs:
            by_batch[r['batch']].append(r)
        for batch, bs in by_batch.items():
            bs.sort(key=lambda r: phase_key(r['phase']))
            dec = next((r for r in bs if r.get('decided')), None)
            last = dec or bs[-1]
            e = {'id': tid, 'batch': batch, 'name': last['name'], 'phases': len(bs),
                 'search_seconds_total': last['search_seconds_total'], 'mid_calls_total': sum(r.get('mid_calls') or 0 for r in bs),
                 'decided': bool(dec)}
            # all search time used on the position (also what a restart lost), next to the carried total above
            _, spent, lower = totals(bs[:bs.index(last) + 1])
            e['spent_seconds_total'] = spent
            if lower:
                e['spent_is_lower_bound'] = True
            if dec:
                v = dec['verify']
                e.update(first_move=dec['first_move'], reply=dec.get('reply'), proof_nodes=dec['proof_nodes'],
                         proof_bytes=dec['proof_bytes'], proof_seconds=dec['proof_seconds'],
                         verify_seconds=dec['verify_seconds'], proof_sha256=v['proof_sha256'],
                         position_sha256=v['position_sha256'], input_sha256=v['input_sha256'], verifier=v['verifier'])
            else:
                e.update(reason=last.get('reason'), pn=last.get('pn'), dn=last.get('dn'))
            out.setdefault(tid, []).append(e)
    return out


def main():
    for arg in sys.argv[1:]:
        name, work = arg.split('=', 1)
        dst = RES / name
        dst.mkdir(parents=True, exist_ok=True)
        for f in sorted(Path(work).glob('*/phase*.json')):
            shutil.copyfile(f, dst / f'{f.parent.name}.{f.name}')
    doc = json.loads((HERE / 'targets.json').read_text(encoding='utf-8'))
    targets = doc['targets']
    c = doc['counts']
    summ = summarize(load_runs())
    (RES / 'summary.json').write_text(json.dumps(summ, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    new = {}
    for t in targets:
        es = [e for e in summ.get(t['id'], []) if e['decided']]
        vs = {e['first_move'] for e in es}
        assert len(vs) <= 1, f'{t["id"]}: batches disagree'
        ex = t['existing']
        if es:
            if ex['evidence'] == 'verified':
                assert ex['verdict'] in vs, f'{t["id"]}: new verdict contradicts the earlier verified one'
            new[t['id']] = es[0]
    searched = {t['id']: max((e['search_seconds_total'] for e in summ.get(t['id'], [])), default=0) for t in targets}

    def status(t):
        ex, n = t['existing'], new.get(t['id'])
        parts = []
        if ex['evidence'] == 'verified':
            parts.append(f'**{KO[ex["verdict"]]}** (기존 검증' + (f', 반박 {ex["reply"]}' if ex.get('reply') else '') + ')')
        if n:
            rep = f', 반박 {"·".join(n["reply"])}' if n.get('reply') else ''
            parts.append(('다시 확인: 같음' if ex['evidence'] == 'verified' else f'**{KO[n["first_move"]]}** (이번 검증{rep})'))
        if ex['evidence'] == 'relayed':
            parts.append(f'전달 기록: {KO[ex["verdict"]]} (아스트라, 여기서 검증 안 함)' + (' → 일치' if n and n['first_move'] == ex['verdict'] else (' → **다름**' if n else '')))
        if ex['evidence'] == 'solver_only':
            parts.append(f'탐색기 기록만: {KO[ex["verdict"]]} (검증 기록 없음)' + (' → 일치' if n and n['first_move'] == ex['verdict'] else (' → **다름**' if n else '')))
        if not parts:
            parts.append(f'미확정 (누적 탐색 {searched[t["id"]]:.0f}초)' if searched[t['id']] else '미확인')
        elif not n and ex['evidence'] != 'verified' and searched[t['id']]:
            parts.append(f'미확정 (누적 탐색 {searched[t["id"]]:.0f}초)')
        return '; '.join(parts)

    def decided(t):
        return t['existing']['evidence'] == 'verified' or t['id'] in new
    # ---- per-syllable table
    rows = []
    tot = Counter()
    for s in sorted({t['syllable'] for t in targets}):
        ts = [t for t in targets if t['syllable'] == s]
        old_w = sum(1 for t in ts if t['existing']['evidence'] == 'verified' and t['existing']['verdict'] == 'win')
        old_l = sum(1 for t in ts if t['existing']['evidence'] == 'verified' and t['existing']['verdict'] == 'lose')
        nw = sum(1 for t in ts if t['existing']['evidence'] != 'verified' and t['id'] in new and new[t['id']]['first_move'] == 'win')
        nl = sum(1 for t in ts if t['existing']['evidence'] != 'verified' and t['id'] in new and new[t['id']]['first_move'] == 'lose')
        rel = sum(1 for t in ts if t['existing']['evidence'] in ('relayed', 'solver_only') and t['id'] not in new)
        left = sum(1 for t in ts if not decided(t))
        pair = sum(1 for t in ts if t['root_form'] == 'pair_cancelled')
        rows.append(f'| {s} | {"조정용" if ts[0]["split"] == "tune" else "비교용"} | {sum(len(t["words"]) for t in ts)} | {len(ts)} | {pair} | {old_w} / {old_l} | {nw} / {nl} | {rel} | {left} |')
        tot.update(words=sum(len(t['words']) for t in ts), pos=len(ts), pair=pair, old_w=old_w, old_l=old_l, nw=nw, nl=nl, rel=rel, left=left)
    rows.append(f'| **합계** | | **{tot["words"]}** | **{tot["pos"]}** | **{tot["pair"]}** | **{tot["old_w"]} / {tot["old_l"]}** | **{tot["nw"]} / {tot["nl"]}** | **{tot["rel"]}** | **{tot["left"]}** |')
    jeok = doc.get('jeok')
    extra_w = ['·'.join(t['words']) for t in targets if t['existing']['evidence'] == 'verified' and t['existing']['verdict'] == 'win'
               and t['existing']['proof']['kind'] == '첫 수 따로 증명' and 'also' not in t['existing']]
    extra_l = Counter(t['syllable'] for t in targets if t['existing']['evidence'] == 'verified' and t['existing']['verdict'] == 'lose')
    extra_l_txt = ', '.join(f'{k} {v}개' for k, v in sorted(extra_l.items()))
    md = f"""# 한기사(817단어) 이기는 쪽의 다른 첫 수: 대상 목록

이 파일은 `report.py`가 `targets.json`과 `results/`에서 만듭니다. 직접 고치지 마세요.

- **용어와 읽는 법:** `TERMS_KO.md`. 제시자 = `~t` 단어를 내서 상대에게 t를 넘기는 사람(낸 쪽). ‘지는 수’ = 그 단어를 낸 쪽(제시자) 패, t를 받은 쪽 승. 497개 중 검증 수는 이번 추가 조사 대상의 진행률입니다.

## 무엇을 세었나

받는 쪽이 이기는 음절 64개(`SOLVED_KO.md`)에서, 받는 쪽이 낼 수 있는 **모든 첫 단어**를 세었습니다. 시작 국면을 단순화하기 전의 원래 단어 기준입니다.

| 단계 | 개수 | 뜻 |
|---|---:|---|
| 원래 합법 첫 단어 | {c['legal_first_words']} | 64개 음절에서 낼 수 있는 단어 전부 |
| 낸 뒤의 국면 | {c['distinct_positions']} | 단어를 낸 뒤의 국면이 정확히 같은 단어끼리 묶음 |
| 그중 시작 국면을 단순화해도 남는 수 | {c['canonical_first_moves_438']} | 지난번에 센 '438' |
| 그중 단순화에서 빠지는 수 (왕복 짝) | {c['root_form']['pair_cancelled']} | 예: 격돌(돌격과 짝), 역풍(풍력과 짝) |

- **'정확히 같은 국면'의 기준:** 검증기 모델로 만든 국면(지금 음절과 단어 묶음별 남은 개수)이 바이트 단위로 같을 때만 묶었습니다.
  - 첫 음절과 끝 음절이 같은 단어들이 이렇게 묶입니다(예: 운송업·운수업). 규칙상 서로 구별되지 않습니다.
  - 서로 다른 음절에서 온 국면이 같아지는 경우는 없었습니다.
- **왕복 짝 수:** 시작 국면을 단순화하면 '가는 단어'와 '돌아오는 단어'가 서로 지워져 첫 수 목록에서 빠집니다. 하지만 실제로는 낼 수 있는 수이고, 승패도 따로 계산해야 합니다.
- 첫 단어를 낸 뒤 단순화만으로 바로 판정되는 국면은 {c['child_static']}개입니다. 모두 탐색이 필요합니다.

## 지난번 숫자(438, 374)는 무엇이었나

- **438** = 시작 국면을 단순화한 뒤 남는 첫 수 묶음입니다. 왕복 짝 {c['root_form']['pair_cancelled']}개가 빠져 있어서 '모든 첫 수'가 아니었습니다.
- **374** = 438 − 64(음절마다 이미 증명한 이기는 수 하나)입니다. 두 가지가 틀렸습니다.
  1. 왕복 짝 {c['root_form']['pair_cancelled']}개를 세지 않았습니다.
  2. 이미 검증된 수를 음절마다 하나씩만 뺐습니다. 실제로는 이기는 수 {len(extra_w)}개({', '.join(extra_w)})와 지는 수 {sum(extra_l.values())}개({extra_l_txt})가 더 검증돼 있었습니다.
     - 명칭·삼인칭은 칭·존 연구('명칭으로 넘겨받은 칭' 등)에서 증명한 국면입니다. 그 국면이 바로 '명 → 명칭', '삼 → 삼인칭'입니다.
- **바로잡은 수:** 국면 {c['distinct_positions']}개 중 검증 기록이 있는 것은 {c['verified_win'] + c['verified_lose']}개(승 {c['verified_win']}, 패 {c['verified_lose']})이고, 검증 기록이 없는 것은 **{c['not_verified_total']}개**입니다.
  - 단순화해도 남는 수 {c['not_verified_canonical']}개, 왕복 짝 {c['not_verified_pair_cancelled']}개
  - 전달받은 기록만 있는 것 {c['relayed_win'] + c['relayed_lose']}개(역: 승 {c['relayed_win']}, 패 {c['relayed_lose']}), 탐색기 기록만 있는 것 {c['solver_only']}개(탑승권), 아무 기록 없는 것 {c['no_record']}개

## 근거의 종류

| 표시 | 뜻 |
|---|---|
| 기존 검증 | 이전 연구에서 증명을 만들어 원본 검증기 `verify_v2.py`로 확인한 것. 증명의 sha256이 `route-site/catalog.json`에 있습니다. |
| 이번 검증 | 이번에 증명(route-proof-v4)을 만들어 C++ 검증기 `verify_v4`로 확인한 것. 기록은 `results/`에 있습니다. |
| 전달 기록 | 아스트라 쪽 기록만 있는 것. 이 저장소에서 검증한 적이 없습니다. |
| 탐색기 기록만 | 글에 '탐색기가 확정했다'고만 적혀 있고 검증 기록이 없는 것. |
| 미확인 / 미확정 | 기록이 없거나, 탐색했지만 결론이 나지 않은 것. |

- 한기사에서는 두 검증기의 모델이 같은 게임입니다. 음절 {doc['model_check']['v3_vertices']}개, 단어 묶음 {doc['model_check']['v3_groups']}개가 일대일로 대응합니다(`build_targets.py`가 확인).
- 받는 쪽이 지는 음절 30개는 이 목록에 없습니다. 그 음절은 모든 첫 수가 지는 수이고, 반박까지 이미 증명돼 있습니다.

## 조정용과 비교용

- 음절 64개를 미리 둘로 나눴습니다. 조정용 {c['split_syllables']['tune']}개, 비교용 {c['split_syllables']['final']}개입니다.
- 규칙: 음절을 정해진 해시 순서로 늘어놓고 번갈아 배정했습니다. 어떤 결과도 보기 전에 정했습니다.
- 같은 음절의 다른 첫 수들은 국면이 단어 하나만 달라서 서로 매우 비슷합니다. 그래서 음절 단위로 나눴습니다.
- 새 방법을 고칠 때는 조정용만 보고, 마지막 비교는 비교용으로 합니다.

## 음절별 현황

'검증 승 / 패'는 첫 수가 받는 쪽에게 이기는 수인지 지는 수인지입니다.

| 음절 | 용도 | 첫 단어 | 국면 | 왕복 짝 | 기존 검증 승 / 패 | 이번 검증 승 / 패 | 전달·탐색기 기록만 | 남은 미검증 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
""" + '\n'.join(rows) + '\n'
    if jeok:
        md += f"""
## 적 (따로 둠)

- 적은 `SOLVED_KO.md`에서 아스트라 쪽 연구(적색 루트 연습실) 결과로 따로 적혀 있어서, 위 64개에 넣지 않았습니다.
- 적의 첫 단어는 {jeok['words']}개, 국면은 {jeok['positions']}개입니다.
  - 아스트라 기록상 이기는 수는 {jeok['relayed_win']}개 국면({', '.join(jeok['relayed_win_words'])})입니다.
  - 그중 **적자생존은 이 저장소에도 검증 기록이 있습니다.** 칭·존 연구의 '적자생존으로 넘겨받은 존' 증명({jeok['verified_here']['nodes']:,}국면, verify_v2 통과)이 바로 '적 → 적자생존 뒤 상대가 진다'는 증명입니다.
  - 그러니 '적을 받으면 이긴다'도 이 저장소의 검증 근거가 있습니다. 적갈색·적색·적회색은 전달 기록뿐입니다.
  - 나머지 {jeok['unknown']}개 국면은 기록이 없습니다.
"""
    (HERE / 'TARGETS_KO.md').write_text(md, encoding='utf-8')
    # ---- full list
    lines = ['# 한기사(817단어) 이기는 쪽의 첫 수 전체 목록', '',
             '`report.py`가 만든 파일입니다. 표시의 뜻은 `TARGETS_KO.md`에 있습니다.',
             '- 한 줄이 국면 하나입니다. 같은 줄의 단어들은 낸 뒤의 국면이 같습니다.',
             '- (짝)은 시작 국면을 단순화하면 빠지는 왕복 짝 수입니다.', '']
    for s in sorted({t['syllable'] for t in targets}):
        ts = [t for t in targets if t['syllable'] == s]
        lines += [f'## {s} ({"조정용" if ts[0]["split"] == "tune" else "비교용"})', '', '| 첫 수 | 도착 음절 | 상태 |', '|---|---|---|']
        for t in ts:
            lines.append(f'| {"·".join(t["words"])}{" (짝)" if t["root_form"] == "pair_cancelled" else ""} | {t["target"]} | {status(t)} |')
        lines.append('')
    (HERE / 'TARGETS_LIST_KO.md').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps({'positions': len(targets), 'decided_before': c['verified_win'] + c['verified_lose'],
                      'newly_verified': sum(1 for t in targets if t['existing']['evidence'] != 'verified' and t['id'] in new),
                      'rechecked_same': sum(1 for t in targets if t['existing']['evidence'] == 'verified' and t['id'] in new),
                      'left': tot['left']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
