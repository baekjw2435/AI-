# verify_v4: 작은 증명서(route-proof-v4)와 빠른 재생 검증

## 무엇이 바뀌었나

- **증명서에서 국면을 뺐습니다.** v3는 줄마다 꼭짓점과 묶음 2,613개의 남은 개수(16진수 5,226자)를 적었습니다. v4는 결과와 수만 적습니다.

  ```
  {"format":"route-proof-v4","groups":2613,"vertices":461,"root":R}
  {"id":i,"r":"W","m":[[묶음,자식id]]}
  ```

  형식 전체는 `FORMAT.md`(영어)에 있습니다.
- **검증기가 국면을 직접 다시 만듭니다.** 요청한 국면(첫 음절, history, initial_used_words)에서 시작해 증명서의 수를 따라가며 매 국면을 `model.child(...)`로 계산합니다. 모델(꼭짓점·묶음·정규형·두음법칙)은 검토한 `../verifier_v3/verify_v3.py`의 `ModelV3`를 그대로 가져다 씁니다.
- **같은 마디에 다시 오면 국면이 바이트까지 같아야 합니다.** 처음 도착할 때 만든 국면을 압축해 둡니다(루트 국면을 사전으로 쓰는 deflate, 국면당 약 110바이트). 다음 도착 때 압축을 풀어 2,613바이트 전체를 비교합니다. v3는 SHA-256 요약값을 비교했으므로 기본 동작은 v3보다 엄격합니다. 메모리가 모자라면 `--digest-only`로 요약값만 둘 수 있습니다(직접 골라야 켜짐).
- **C++ 검증기 `verify_v4`를 새로 만들었습니다.** 계산기 코드를 쓰지 않고 명세(verify_v3.py, README)만 보고 썼습니다. UTF-8·한글·사전 읽기·국면 재생·JSON·SHA-256·gzip을 모두 따로 구현했습니다. 플래그와 결과 JSON 필드는 Python판과 같습니다.
- **계산기 패치** `solver_proof_v4.patch`: 증명서를 쓰는 부분만 고칩니다. `--proof-format v4`를 주면 v4로 씁니다. 기본값은 v3 그대로입니다. 탐색 부분은 건드리지 않습니다.
- **`merge_root_v4.py`**: 첫 수 뒤 국면들의 v4 증명서를 하나로 합쳐 루트 증명서를 만듭니다.

## 왜 약해지지 않았나

- v3는 줄에 적힌 국면이 정규형인지 보고, 각 수의 `model.child(...)`가 자식 줄에 적힌 국면과 같은지 봤습니다.
- v4에서는 그 `model.child(...)` 값이 곧 자식 국면입니다. 다른 길로 같은 자식에 오면 그 값이 처음 값과 정확히 같아야 합니다.
- 마디마다 하는 검사는 v3와 같습니다.
  - 국면을 다시 정규화해도 그대로인지
  - 고정 라벨 마디는 수가 없고 결과가 라벨과 같은지
  - W는 수 하나로 L 자식에게 가는지
  - L은 모든 합법 묶음을 한 번씩 적고 자식이 모두 W인지
  - 묶음이 합법인지, 중복이 없는지
  - 자식 id가 자기 id보다 작은지
  - id가 0부터 빈틈없는 정수인지(true·1.0 거부)
  - 루트가 마지막이고 요청 국면과 같은지
  - input_sha256 확인, JSON 키 중복 거부
- 그 위에 다음을 더 거부합니다.
  - 모르는 키
  - 그룹 번호 범위 밖
  - gzip이 잘렸거나 뒤에 다른 데이터가 붙음
- 루트에서 닿지 않는 마디는 어떤 국면도 주장하지 않습니다. 문법만 검사하고 개수를 `unreached_nodes`로 알립니다. 계산기가 쓴 증명서에서는 항상 0입니다.

## 사용

```sh
# 증명서 만들기 (패치한 계산기)
g++ -O3 -march=native -std=c++17 -o build/solver_v4_pf build/solver_v4_pf.cpp -lz -pthread
build/solver_v4_pf IN.txt --seconds 600 --tt-mb 2048 --threads 1 --proof OUT.jsonl.gz --proof-format v4

# C++ 검증기 (빠름)
g++ -O2 -std=c++17 -o build/verify_v4 verify_v4.cpp -lz
build/verify_v4 --dictionary ../words_3436.txt --expected-word-count 3436 \
  --position POS.json --proof OUT.jsonl.gz --input IN.txt

# Python 검증기 (모델은 verify_v3의 ModelV3)
python3 verify_v4.py --dictionary ../words_3436.txt --expected-word-count 3436 \
  --position POS.json --proof OUT.jsonl.gz --input IN.txt   # [--digest-only]

# 첫 수별 증명서 합치기 (CHILD_POS = ROOT의 history에 단어 하나를 더한 국면)
python3 merge_root_v4.py ../words_3436.txt 3436 ROOT.json ROOT.jsonl.gz \
  C1.json:C1.jsonl.gz C2.json:C2.jsonl.gz ... --input ROOT_IN.txt
```

종료 코드 0과 `"verified": true`, 그리고 `result_for_player_to_move`를 확인합니다.

## 시험 (`tests/`)

- `random_v4.py SOLVER VERIFY_CPP WORKDIR [N] [SEED]`
  - 무작위 작은 사전으로 v3·v4 증명서를 만듭니다.
  - verify_v3, verify_v4.py, verify_v4(C++)를 각각 기본 모드와 `--digest-only`로 돌립니다.
  - 결과를 단어 수준 완전 탐색과 맞춰 봅니다.
  - v4 파일이 v3 파일에서 v·c만 뺀 것과 같은지도 봅니다.
- `real_v4.py`: 실제 3,436단어 국면. 크기·시간·최대 메모리를 잽니다.
- `corrupt_v4.py`: 망가뜨린 증명서 40종을 두 v4 검증기가 모두 거부하는지 봅니다.
- `merge_test_v4.py`: 자식 증명서를 합친 루트 증명서를 검증합니다(W 루트와 L 루트).

결과 수치는 아래에 적습니다.
