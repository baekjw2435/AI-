# 저장 상태 백업

이 파일은 `backup_states.py`가 `INDEX.json`에서 만듭니다. 직접 고치지 마세요.

- 저장 상태(`state.tt`)를 gzip으로 묶어 GitHub 릴리스에 첨부한 목록입니다. 작업 환경이 바뀌어도 이어 풀 수 있게 하려는 것입니다.
- 저장 상태는 다시 계산하기 가장 비싼 기록 200만 개만 남깁니다. 불러와 이어 풀어도 끊기지 않은 것과 같지는 않습니다.
- 판정이 아닙니다. 확정은 검증을 통과한 증명서로만 합니다.
- 되돌리기: `python3 backup_states.py restore /home/user/AI-/.work [태그]`

| 태그 | 국면 | 되돌릴 경로 | 든 탐색(초) | 크기(MB) | 올린 뒤 확인 | 지금 |
|---|---|---|---:|---:|---|---|
| `alt817-states-2026-11-14a` | 극 받음, 극언 | `direct1/run/d01/direct.state.tt` | 600 | 47 | 2026-11-14 05:36:29 | 미확정 |
| `alt817-states-2026-11-14a` | 식 받음, 식곤증 | `direct1/run/d02/direct.state.tt` | 600 | 47 | 2026-11-14 05:36:29 | 미확정 |
| `alt817-states-2026-11-14a` | 탄 받음, 탄핵 | `direct1/run/d03/direct.state.tt` | 600 | 47 | 2026-11-14 05:36:29 | 미확정 |
| `alt817-states-2026-11-14a` | 야 받음, 야식 | `direct1/run/d04/direct.state.tt` | 600 | 47 | 2026-11-14 05:36:29 | 미확정 |
| `alt817-states-2026-11-14a` | 행 받음, 행정구역 | `direct1/run/d05/direct.state.tt` | 600 | 47 | 2026-11-14 05:36:29 | 미확정 |
| `alt817-states-2026-11-14a` | 순 받음, 순풍 | `direct1/run/d06/direct.state.tt` | 600 | 47 | 2026-11-14 05:36:29 | 미확정 |
| `alt817-states-2026-11-14a` | 격 받음, 격돌 | `direct1/run/d07/direct.state.tt` | 600 | 47 | 2026-11-14 05:36:29 | 미확정 |
| `alt817-states-2026-11-14a` | 돌 받음, 돌솥 | `direct1/run/d09/direct.state.tt` | 600 | 47 | 2026-11-14 05:36:29 | 미확정 |
| `alt817-states-2026-11-14a` | 삼 받음, 삼한사온 | `direct2/run/e01/direct.state.tt` | 600 | 47 | 2026-11-14 05:36:29 | 미확정 |
| `alt817-states-2026-11-14a` | 극 받음, 극언 | `replay10/run/u07/replay.state.tt` | 600 | 47 | 2026-11-14 05:36:29 | 미확정 |
| `alt817-states-2026-11-14a` | 삼 받음, 삼한사온 | `replay13/run/x02/replay.state.tt` | 600 | 47 | 2026-11-14 05:36:29 | 미확정 |
| `alt817-states-2026-11-14a` | 탄 받음, 탄핵 | `replay5/run/m06/replay.state.tt` | 600 | 47 | 2026-11-14 05:36:29 | 미확정 |
| `alt817-states-2026-11-14a` | 격 받음, 격돌 | `replay6/run/n24/replay.state.tt` | 600 | 47 | 2026-11-14 05:36:29 | 미확정 |
| `alt817-states-2026-11-14a` | 순 받음, 순풍 | `replay7/run/q03/replay.state.tt` | 600 | 47 | 2026-11-14 05:36:29 | 미확정 |
| `alt817-states-2026-11-14a` | 돌 받음, 돌솥 | `replay7/run/q14/replay.state.tt` | 600 | 47 | 2026-11-14 05:36:29 | 미확정 |
| `alt817-states-2026-11-14a` | 야 받음, 야식 | `replay8/run/s09/replay.state.tt` | 600 | 47 | 2026-11-14 05:36:29 | 미확정 |
| `alt817-states-2026-11-14a` | 식 받음, 식곤증 | `replay9/run/t03/replay.state.tt` | 600 | 47 | 2026-11-14 05:36:29 | 미확정 |
| `alt817-states-2026-11-14a` | 껑 받음, 단어 없음(원본) | `sources/껑/state.tt` | 300 | 47 | 2026-11-14 05:36:29 | 원본 완성(replay15) - 더 필요 없음 |
| `alt817-states-2026-11-14a` | 맹 받음, 단어 없음(원본) | `sources/맹/state.tt` | 1,800 | 48 | 2026-11-14 05:36:29 | 원본 완성(replay14) - 더 필요 없음 |
| `alt817-states-2026-11-14b` | 격 받음, 단어 없음(원본) | `sources/격/state.tt` | 3,600 | 48 | 2026-11-14 06:26:34 | 원본 완성(replay16) - 더 필요 없음 |
| `alt817-states-2026-11-14c` | 승 받음, 승격 | `replay16/run/g04/replay.state.tt` | 600 | 47 | 2026-11-14 08:14:42 | 미확정 |
| `alt817-states-2026-11-14c` | 습 받음, 습격 | `replay16/run/g07/replay.state.tt` | 600 | 47 | 2026-11-14 08:14:42 | 미확정 |
| `alt817-states-2026-11-14d` | 습 받음, 단어 없음(원본) | `sources/습/state.tt` | 1,800 | 48 | 2026-11-14 13:58:43 | 원본 미완성 |
| `alt817-states-2026-11-14d` | 활 받음, 단어 없음(원본) | `sources/활/state.tt` | 1,800 | 48 | 2026-11-14 13:58:43 | 원본 완성(replay17) - 더 필요 없음 |
| `alt817-states-2026-11-14e` | 습 받음, 단어 없음(원본) | `sources/습/state.tt` | 3,600 | 48 | 2026-11-14 14:50:56 | 원본 미완성 |
