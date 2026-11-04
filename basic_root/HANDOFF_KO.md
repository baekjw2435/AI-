# 인수인계: 기초사전 루트 817단어 연구 → 다음 연구(구없샘 루트)

이 문서 하나로 이전 채팅방의 작업을 이어받을 수 있게 정리했습니다. 브랜치 `claude/word-chain-korean-dict-root-n47fzp`.

## 1. 연구 대상과 용어

- 끝말잇기 루트 연구. 사전은 "루트 단어 목록"만 씁니다(817 연구는 `words_817.txt`, 격언 포함).
- 규칙: 표준두음법칙(ㄹ+ㅑㅕㅖㅛㅠㅣ→ㅇ, ㄹ+그 밖→ㄴ, ㄴ+ㅕㅛㅠㅣ→ㅇ), 한 경기 안 단어 재사용 금지, 낼 단어가 없으면 패배.
- **받는 쪽**: 그 음절로 시작해야 하는 사람(먼저 둠). **낸 쪽**: 그 음절을 넘긴 사람.
- **첫 제시 기준**: 그 음절을 루트 목록 밖의 단어로 넘겨받아, 목록 단어가 하나도 안 쓰인 국면. 목록 안의 단어로 넘겨받으면(예: 명칭으로 받은 칭) 다른 국면입니다.
- 결과 표기: 받으면 승 / 받으면 패. "지는 쪽의 모든 수는 끝까지 확인, 이기는 쪽은 이기는 수 하나만 증명"이 원칙입니다.

## 2. 817 연구 결과 (끝남)

- `SOLVED_KO.md`: 추정표 94음절 전부 확정(받으면 승 64, 받으면 패 30), 첫 수와 반박 수, 증명 크기와 sha256.
- 추정표(다른 분의 '한기사 시작글자별 유불리 추정표')와 반대: 탑·객·균·습·표.
- 적은 아스트라(GPT) 쪽 연구 결과를 씀(받는 쪽 승, 그쪽 검증기).
- 칭·존을 817 안의 단어로 넘겨받은 국면: `scan/RESULTS_SCAN.md`.
- 클릭해서 수순을 따라가는 사이트: 아티팩트 '루트 수순 지도'(https://claude.ai/artifact/JCQ7dShxzrUdjhbxyNJPmP), 코드는 `route-site/`.
- 증명 파일 원본(수십 GB)은 이전 컨테이너에만 있었고 저장소에는 없습니다. sha256과 국면 수는 `scan/*_confirmed.json`, `SOLVED_KO.md`, `route-site/catalog.json`에 남아 있습니다.

## 3. 도구

| 무엇 | 위치 | 비고 |
|---|---|---|
| 검증기 (원본, 수정 금지) | `verifier/route-verifier-v2/verify_v2.py`, `verify.py` | sha256 `9019cd1da696c7cc…`, `b08c2491b95d6ccc…`. 판정은 이것으로만 확정. 종료 코드 0 + `verified: true` + 결과 일치 확인 |
| 계산기 | `solver_v3/solver_v3.cpp` | df-pn, route-proof-v2 증명 출력. `--seconds --tt-mb --threads 1 --proof OUT.jsonl.gz`, 이어 하기 `--tt-save F --tt-load F --checkpoint-seconds 600` |
| 입력 만들기 | `solver_v3/tools/mkinput.py DICT POS.json OUT.txt` | POS.json = `{"initial_syllable": "탑", "history": []}` |
| 첫 수별 분할 | `solver_v3/tools/children.py POS.json OUTDIR PREFIX` | 정준화 후 남는 수마다 자식 국면 |
| 증명 합치기 | `solver_v3/tools/merge_root.py DICT ROOT_POS.json OUT.jsonl.gz CHILD...` | 이기는 루트는 지는 자식 하나, 지는 루트는 모든 자식 |
| 사이트 | `route-site/` (`README_KO.md`) | `site_build.py`(증명→표) → `test_site.js` → `make_site_catalog.js` → `pack_site.py` |
| 정리 문서 생성 | `scan/gen_solved.py CATALOG OUT.md [STATUS.json]` | 사이트 목록 파일에서 SOLVED_KO.md 생성 |

새 컨테이너에서 준비(도구들이 `/home/user/AI-/.work` 경로를 씀, `.work`는 git 제외):

```sh
cd /home/user/AI- && echo ".work/" >> .git/info/exclude
mkdir -p .work/measure .work/site2 && cp -r basic_root/verifier .work/verifier && cp basic_root/words_817.txt .work/basic_root.txt
g++ -O3 -march=native -std=c++17 -o .work/measure/solver_v3r basic_root/solver_v3/solver_v3.cpp -lz -pthread
gcc -O2 -o .work/site2/site2tab basic_root/route-site/build/site2tab.c -lz
```

## 4. 푸는 순서 (817에서 쓴 방식)

1. 음절마다 시작 국면을 짧게(3분) 풀고, 결론 나면 바로 검증.
2. 안 풀리면 10분, 40분으로 늘림(40분부터는 `--tt-save`로 이어 하기 가능하게).
3. 그래도 안 풀리면 첫 수별로 나눠(children.py) 각각 풀고, 필요하면 둘째 수까지 나눔. 결론 나면 merge_root.py로 합쳐 검증.
4. 받는 쪽이 이기는 첫 수 하나만 찾으면 그 음절은 승, 모든 첫 수가 지면 패.

## 5. 운영 주의 (겪은 문제)

- **검증기 메모리**: 1,000만 국면대 증명은 verify_v2가 10GB 가까이 씀. 큰 검증 두 개를 동시에 돌리면 OOM으로 같이 죽음. 하나씩.
- **컨테이너 재시작**: 몇 시간마다 재시작되며 돌던 계산이 모두 죽음(파일은 남음). 긴 작업은 `setsid nohup`으로 떼어 놓고, 다시 걸 수 있게(이미 끝난 것은 건너뛰게) 짤 것. 이어 하기 캐시 저장 권장.
- **백그라운드 작업 2시간 제한**: 도구로 띄운 작업은 2시간에 끊김. 긴 것은 떼어 놓고 감시용만 도구로.
- **디스크**: 증명·캐시가 금방 수십 GB. 끝난 캐시와 합쳐진 자식 증명은 지울 것.
- **기다림 조건에 pgrep 쓰지 말 것**: 명령 문자열에 같은 글자가 있으면 영원히 기다리는 일이 있었음(한글 패턴은 아예 안 맞기도 함). 파일 표시로 기다릴 것.
- **아티팩트**: 버전 전체 256MB, 한 번 게시 64MB·255파일. 일반 이진 파일 불가 → 표는 데이터만 담은 `.wasm`으로 감싸 올림(`pack_site.py`).

## 6. 사용자와 일하는 방식

- 한국어로, 짧고 쉽게. 결론부터.
- 아스트라(GPT)에게는 무거운 계산을 시키지 않음(사용량). 검토·의견만 요청.
- 커밋 메시지에 모델 이름 넣지 않음. PR은 요청할 때만. 주간 사용량이 빠듯할 때가 있으니 도구 호출을 아낄 것.

## 7. 구없샘 루트로 바꿀 때 확인할 것

- 새 루트 단어 목록 파일이 필요합니다(한 줄에 한 단어, UTF-8).
- 검증기는 단어 수를 기본 817로 검사합니다. `verify_v2.py --expected-word-count N`으로 맞추면 수정 없이 씁니다.
- 검증기는 **첫 음절이 두음법칙으로 바뀌는 단어**(예: 라면, 녀석)가 있으면 거부합니다. 구없샘 목록에 그런 단어가 있으면 그대로는 못 쓰니 먼저 확인하고, 처리 방식은 사용자·아스트라와 정할 것.
- 위 파이썬 도구들(`mkinput.py`, `children.py`, `merge_root.py`, `site_build.py` 등)은 모델을 만들 때 817을 기본으로 씁니다. 새 사전이면 단어 수를 넘기도록 고쳐야 합니다.
- 사전 경로(`.work/basic_root.txt`)와 사전 sha256 확인 코드도 새 사전에 맞춰야 합니다.
- 적 판정(아스트라 자료)과 추정표 대조는 817 전용입니다.
