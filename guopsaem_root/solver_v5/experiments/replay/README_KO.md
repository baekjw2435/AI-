# 전략 재생 실험 (solver_v5_replay, 2026-11-12)

이미 푼 국면의 증명서를 **조금 다른 국면**에 따라가 보고, 따라갈 수 없는 곳만 다시 푸는 방법입니다.
한기사의 '다른 첫 수'에서는 넘겨준 음절의 증명서를 '단어 하나 빠진 국면'에 씁니다.

- 결과와 시간 비교: `basic_root/alt_first_moves/results/replay1/README_KO.md`
- 계산기: `solver_v5_replay.cpp` (`../../solver_v5.cpp`에 재생 단계만 더한 사본. `--replay`를 안 주면 solver_v5와 같습니다.)
- 실행 도구: `basic_root/alt_first_moves/replay_prep.py`(원본 증명 준비), `replay_test.py`(직접 탐색과 비교)

## 하는 일

```sh
solver_v5_replay 새국면.txt --replay 옛증명.v4.gz [--replay-stuck-nodes 200000] \
    --seconds 600 --tt-mb 1024 --proof 새증명.v4.gz --proof-format v4
```

1. **재생.** 옛 증명서를 뿌리부터 읽으면서, 새 국면에서 같은 묶음의 수를 똑같이 둡니다.
   - 옛 증명서에서 쓰는 것은 "이 마디에서 어느 수를 뒀는가"뿐입니다.
   - 새 국면의 상태는 계산기가 실제로 만듭니다. 남은 단어 수, 짝 지우기, 고정 라벨, 둘 수 있는 수가 모두 새 국면 기준입니다.
2. **기록.** 새 국면에서 실제로 증명된 것만 저장표에 적습니다.
   - 승: 그 국면의 자식 하나가 패로 증명됨.
   - 패: 그 국면에서 **지금 둘 수 있는 모든 수**의 자식이 승으로 증명됨.
   - 기록의 열쇠는 새 국면 자체(128비트 해시)입니다. 옛 증명의 마디 번호로 국면을 구분하지 않습니다.
3. **막힌 곳.** 아래 경우에는 옛 증명을 따라갈 수 없습니다. 그 국면만 정해진 예산(기본 20만 국면)으로 다시 탐색합니다.

   | 출력 이름 | 뜻 |
   |---|---|
   | `stuck_witness_gone` | 옛 증명의 이기는 수가 새 국면에는 없음 |
   | `stuck_witness_static` | 그 수가 새 국면에서는 바로 지는 수 |
   | `stuck_witness_refuted` | 그 수를 따라가 보니 상대가 이기는 것으로 증명됨 |
   | `stuck_new_move` | 새 국면에 옛 마디에 없던 수가 있음 |
   | `stuck_old_leaf` | 옛 마디는 고정 라벨로 끝났는데 새 국면은 아님 |

4. **남은 탐색.** 재생으로 뿌리가 증명되지 않으면, 지금까지의 기록을 가진 채 보통 탐색을 이어 갑니다. 시간 한도(`--seconds`)에는 재생 시간도 들어갑니다. 한도 안에 못 풀면 결과는 `unknown`(미확정)입니다.
5. **증명서.** 기존 증명 생성 코드가 그대로 씁니다. 기준 정규화로 뿌리부터 다시 재생하며 모든 마디를 대조합니다.

## 정확성을 지키는 방법

- 결과물은 **새 국면의 보통 route-proof-v4 증명서**입니다. 검증기(`verify_v4`)와 수락 조건은 그대로입니다. 검증을 통과해야만 확정합니다.
- 옛 증명서는 힌트입니다. 틀린 증명서나 다른 국면의 증명서를 줘도 틀린 판정이 나올 수 없습니다. 느려질 뿐입니다.
- 재생 기록은 저장표의 다른 기록과 같은 힌트입니다. 잘못 적혔다면 증명 생성이나 검증에서 실패합니다.

## 시험 (`test_replay_random.py`)

무작위 작은 사전에서 '시작 국면의 증명서'를 '단어가 빠지거나 한 수 둔 국면'에 재생했습니다. 세 번에 한 번은 일부러 다른 시작 음절의 증명서를 줬습니다. 계산기 자체 점검(`--selfcheck 1`)을 켰고, 결과는 규칙 글만 보고 짠 단어 수준 완전탐색과 비교했습니다.

결과는 `basic_root/alt_first_moves/results/replay1/README_KO.md`의 '무작위 시험'에 적었습니다.

```sh
M=/home/user/AI-/.work/measure
g++ -O3 -march=x86-64-v3 -std=c++17 -o $M/solver_v5_replay solver_v5_replay.cpp -lz -pthread
python3 test_replay_random.py $M/solver_v5 $M/solver_v5_replay $M/verify_v4 /home/user/AI-/.work/replay_rnd 2000 11
```

## 출력에 더해진 값

| 이름 | 뜻 |
|---|---|
| `replay_root` | 재생만으로 뿌리가 증명됐는가. 1 = 둘 차례 승, 0 = 패, -1 = 아님, -2 = 재생 안 함 |
| `replay_old_nodes` | 옛 증명서의 마디 수 |
| `replay_load_seconds` | 옛 증명서를 읽은 시간(`seconds`에 들어가지 않음) |
| `replay_seconds` | 재생 단계 시간(막힌 곳 탐색 포함, `seconds`에 들어감) |
| `replay_nodes`, `replay_proven` | 재생이 새로 본 국면 수, 그중 증명해 적은 수 |
| `replay_stuck_*` | 위 표의 막힌 곳 수 |
| `replay_local_calls`, `replay_local_solved`, `replay_local_mid` | 막힌 곳 탐색 횟수, 풀린 횟수, 그 탐색의 국면 수 |
| `replay_unknown_below` | 아래쪽이 풀리지 않아 증명하지 못한 마디 수 |
| `replay_flips` | 옛 증명에서는 패였지만 새 국면에서는 승으로 증명된 마디 수 |

## 한계

- 한 번에 옛 증명서 하나만 재생합니다.
- 막힌 곳 탐색이 예산 안에 안 끝나면 그 위쪽 마디는 재생 단계에서 증명되지 않습니다. 남은 탐색이 처음부터 다시 내려가며 풉니다.
- 옛 증명서는 계산기가 쓰는 줄 형식(`{"id":…,"r":"W","m":[[묶음,자식],…]}`)만 읽습니다.
- 한 스레드로만 재생합니다.
