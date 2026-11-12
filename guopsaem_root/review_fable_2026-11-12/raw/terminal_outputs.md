# 화면으로만 본 출력 (2026-11-12, 525799d 빌드)

파일로 남기지 않은 실행의 명령과 출력입니다. 출력은 그대로 옮겼습니다.
`$SP`는 그때의 임시 폴더, `$REV`는 525799d 체크아웃입니다.

## 1. 빨리 돌려 보는 확인 (검토 요청서 8절): 격 → 격멸

```sh
solver_v5 in.txt --seconds 120 --tt-mb 1024 --threads 1 --proof p.gz --proof-format v4
```
```
{"result":"win","reason":"none","mid_calls":10226199,"child_gens":24695608,"tt_entries":6302054,"tt_capacity":33554432,"tt_mb":1024,"tt_stores":10226273,"tt_replacements":10573,"seconds":13.826180,"pn":0,"dn":4294967295,"best_group":161,"threads":1,"eps":0.25,"init":1,"wpn":0,"proof_nodes":108307,"emit_resolves":37,"emit_resolve_mid":37,"emit_crosschecks":110320,"emit_seconds":1.852382,"selfchecks":0,"proof_error":"","tt_loaded":0,"tt_load_seconds":0.000000,"tt_saves":0,"tt_saved":0,"tt_save_seconds":0.000000,"tt_save_error":"","tt_load_open_capped":0,"tt_load_proven_in_cache":0,"tt_load_proven_kept":0,"proven_load_cap":0}
```
- C++ `verify_v4`: 통과, 둘 차례 W, 108,307국면, 4.8초. 출력은 `../proofs/격_격멸/verify.json`.
- Python `verify_v4.py`: 통과, 둘 차례 W, 108,307국면, 45.9초.

## 2. 독립 대조 예비 실행 (`scripts/indep.py`)

초기본(사전 단어 4~15개), 사전 60개, 씨앗 1, 변형 300번:
```
{"dicts": 60, "positions": 175, "accepted": 175, "mismatch": 0, "not_decided": 0, "shared_dicts": 22, "py_checked": 24, "py_disagree": 0, "fuzz": 271, "fuzz_accepted": 0, "fuzz_wrong_accepted": 0, "multi_node_proofs": 12}
```
최종본(사전 단어 8~18개), 사전 400개, 씨앗 2, 변형 3,000번:
```
{"dicts": 400, "positions": 1199, "accepted": 1199, "mismatch": 0, "not_decided": 0, "shared_dicts": 161, "py_checked": 163, "py_disagree": 0, "fuzz": 2791, "fuzz_accepted": 1, "fuzz_wrong_accepted": 0, "multi_node_proofs": 204}
```
본 실행(씨앗 11·12·13, 사전 3,000개씩, 변형 25,000번씩)은 `indep11.out`, `indep12.out`, `indep13.out`.

## 3. 저장소의 모델 대조 시험

```sh
python3 verifier_v3/test_v3_bruteforce.py 300 1
```
```
{'dictionaries': 300, 'with_shared_groups': 84, 'positions': 1175, 'static_labels_checked': 1646, 'ok': True}
```

## 4. 두음법칙 표 비교 (`scripts/conv_vs_engine.py`)

```
differences over 11172 syllables: 0
```

## 5. 저장 상태 손실 재현 (`scripts/loss_paths.py`, 525799d의 solve_common.py)

```
A: {'result': 'win', 'proof_error': 'cannot create proof body', 'seconds': 23.922063, 'tt_saves': 7, 'tt_saved': 2000000} | saved state still on disk: False
C: note = 'no state saving (free disk 5.0 GB)' | --tt-load in command: False | --tt-save in command: False
C: after an undecided run with 3.9 GB free, saved state still on disk: False
```
- A: 격 → 격멸을 256MB 저장표, 3초 간격 저장으로 풀되 증명서 경로만 못 쓰게 했습니다. 풀렸지만 증명서가 없고, 저장 파일도 지워졌습니다.
- C: 남은 디스크를 5.0GB로 속이고 2,048MB 작업을 만들면 불러오기와 저장이 모두 빠집니다. 3.9GB에서는 미확정으로 끝난 뒤 저장 파일이 지워졌습니다.

## 6. 저장 타이머가 증명 생성에 주는 영향 (격 → 격멸)

저장표 16MB:
```
none {'result': 'win', 'mid_calls': 25676658, 'seconds': 27.53981, 'proof_nodes': 102682, 'emit_resolves': 10392, 'emit_resolve_mid': 114137, 'emit_seconds': 1.675294, 'tt_saves': 0, 'proof_error': '', 'tt_capacity': 524288}
ckpt {'result': 'win', 'mid_calls': 27646765, 'seconds': 29.51109, 'proof_nodes': 109472, 'emit_resolves': 11587, 'emit_resolve_mid': 117135, 'emit_seconds': 1.783924, 'tt_saves': 29, 'proof_error': '', 'tt_capacity': 524288}
```
저장표 1MB:
```
none {'result': 'win', 'mid_calls': 24347302, 'seconds': 23.437425, 'proof_nodes': 111387, 'emit_resolves': 4052, 'emit_resolve_mid': 363109, 'emit_seconds': 2.16581, 'tt_saves': 0, 'proof_error': '', 'tt_capacity': 32768}
ckpt {'result': 'win', 'mid_calls': 40114822, 'seconds': 40.261686, 'proof_nodes': 103764, 'emit_resolves': 3756, 'emit_resolve_mid': 405378, 'emit_seconds': 2.123652, 'tt_saves': 40, 'proof_error': '', 'tt_capacity': 32768}
```
- `ckpt`는 `--tt-save st.tt --checkpoint-seconds 1`을 더한 실행입니다(16MB는 `--tt-save-max 100000`, 1MB는 `1000`).
- 증명 생성 시간 차이는 작았습니다. 1초마다 저장하면 탐색 국면이 늘지만(1MB에서 65%), 실제 실행은 저장표 1GB에 60초 간격입니다.

## 7. 재생 가능성 시험: 승급 (`scripts/replay_probe.py 승 승급 120 20`)

```
{"case": "승/승급", "hands_over": "급", "old_root": {"result": "win", "search_nodes": 552430, "proof_nodes": 8247, "seconds": 0.742163}, "replay_root_value_for_mover": "W", "first_move": "lose", "replay_new_nodes": 8254, "replay_python_seconds": 1.4, "stats": {"new_nodes": 8254, "static_leaf": 1152}, "stuck_calls": 0, "stuck_biggest": []}
```
즉흥·편싸움·증가율은 `replay_probe_*.out`. 낙엽은 결과 줄 없이 끝났습니다(`replay_probe_낙엽.out`에는 종료 코드 124만 있음).

## 8. 같은 국면 세기 (`scripts/canon_dups.py`)

```
('differs_2_3', 'verified') 1
('differs_by_1_word', 'open') 400
('differs_by_1_word', 'verified') 90
('differs_more', 'open') 2
('differs_more', 'verified') 4
open targets identical to the handed-over syllable root: 0 | of these, t root is one of the 94 solved: 0
canonical states shared by 2+ targets: 0 covering 0 targets; distinct canonical states among 497: 497
open targets whose canonical state equals an already verified target: 0
```

## 9. 기록 점검 (`scripts/check_records.py`)

```
44 records; flagged 2
24 decided records
```
표시된 2개는 손으로 적은 중단 기록(p05, p10의 phase2a)이고, 문제가 아닙니다.
