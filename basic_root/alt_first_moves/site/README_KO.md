# 제시 단어 수순 지도 (2026-11-14)

음절을 **어떤 단어로 제시했는지**(`~t` 단어, 용어는 `../TERMS_KO.md`)에 따른 판정과 그 뒤의 수순을 보는 페이지입니다. 기존 '루트 수순 지도'(`basic_root/route-site/`)와 같은 엔진과 모양을 씁니다.

| 부분 | 주소 | 제시한 음절 | 제시 자리 | 승리수 표 항목 | 파일 | 크기 |
|---|---|---:|---:|---:|---:|---:|
| 갑~야 | https://claude.ai/artifact/KndUJijNUK7UTLzaZRvYSQ | 40 | 165 | 52,445,702 | 248 | 210MB |
| 약~환 | https://claude.ai/artifact/UjKQseRTnnTwckdBwJGxFN | 49 | 222 | 54,636,509 | 302 | 216MB |
| 활~흥 | https://claude.ai/artifact/FUZuSEw5kddKQTz14NxQbt | 6 | 9 | 8,151,140 | 31 | 34MB |

- 기존 지도(https://claude.ai/artifact/JCQ7dShxzrUdjhbxyNJPmP)의 첫 화면에서 세 부분으로 연결됩니다.
- 기존 지도는 표만 217MB라 아티팩트 한 버전의 한도(256MB)에 거의 닿아 있습니다. 그래서 새 표는 따로 나눴습니다. 부분마다 표를 어림값 225MB까지 담고, 넘치면 음절 순서대로 다음 부분으로 넘깁니다(2026-11-14 활 4개를 더하면서 활~흥이 세 번째 부분이 됨).
- 각 부분의 목록에는 이 연구의 497개 국면이 모두 나옵니다.
  - 396개: 그 자리의 v4 증명서로 만든 표가 있어 끝까지 수순을 볼 수 있음
  - 77개: 예전 연구(verify_v2)의 증명. 기존 지도의 그 음절 수순으로 연결
  - 24개: 미확정
- 진행률(473/497)은 이번 추가 조사 대상의 것입니다. 모든 제시 단어나 모든 후속 갈래의 비율이 아닙니다.

## 지키는 원칙

- **자리마다 표 하나.** 'w로 t 제시'(w를 이미 썼고 상대가 t를 받은 자리)마다, 그 자리의 v4 증명서 하나에서만 승리수 표를 만듭니다. 엔진은 진입점의 표만 찾으므로, 다른 이력(다른 제시 단어, 빈 사전에서 받은 국면)의 결과를 쓰지 않습니다.
- **사용 이력 그대로.** 진입점의 제시 단어는 증명서를 검증할 때 쓴 단어입니다(`pos.json`의 history). 같은 국면이 되는 다른 단어는 '같은 자리'로만 적습니다.
- **승패는 누구 기준인지 함께.** '제시자 패 · 받은 쪽 승' 또는 '제시자 승 · 받은 쪽 패'.
- **이기는 쪽의 다른 선택지는 미확인.** 증명이 고른 수만 '이기는 수'입니다. 다만 엔진이 같은 표만으로 한 수 앞까지 증명할 수 있는 수는 '이 수도 이김'으로 보입니다(기존 지도와 같은 규칙).
- **축약은 실제 단어로.** 증명서는 단어 묶음과 줄인 국면(왕복 쌍 지움, 정적 판정)으로 적혀 있습니다. 엔진이 실제 단어로 되돌려 보여 줍니다: 되받기, 정적, 한 수.

## 만든 방법

1. `site_model.py`: 사이트의 모델(`model.json`)과 v4 증명서의 모델(ModelV3)을 단어 단위로 맞춥니다. 817에는 공유 묶음이 없고, 718개 묶음·짝 46개·자기 연결 35개·단어 수가 모두 같습니다. 무작위 국면 6,000개에서 정준형이 모두 같았습니다.
2. `cert2site.cpp`: 증명서를 뿌리부터 검증기와 같은 방식으로 따라가며, 이기는 쪽이 둘 차례인 국면마다 사이트의 48비트 열쇠와 증명서가 고른 묶음을 적습니다. 엔진이 스스로 판정하는 국면(정적, 정적으로 지는 자리로 보내는 한 수)은 기존 지도처럼 뺍니다.
3. `build_site_tables.py`: 보관 색인(`results/*/archive/INDEX.json`)의 검증된 증명서마다 위를 돌립니다. 증명서 파일은 sha256이 보관된 값과 같아야 씁니다.
4. `site_books.py`: 자리마다 표(책) 하나로 묶습니다(RSB1, 기존 지도의 형식). 열쇠가 겹치면 핵심 크기 경계에서 파일을 나눕니다(전체에서 1건, 명곡). 같은 핵심 크기에서 겹치면 멈춥니다.
5. `make_pages.py`: 제시한 음절 순서로 여러 부분에 나눠 담고, 표를 기존 지도처럼 WebAssembly 사용자 구역으로 감싸고, 공통 목록(`pindex.json`)을 씁니다.

## 시험

- `check_tables.js`: 모든 표 파일을 사이트 엔진의 해독기로 끝까지 풀어, 만든 때 적은 sha256과 비교(566개 파일, 다른 것 0)
- `test_books.js`: 기존 지도의 시험(`route-site/build/test_site.js`)과 같습니다. 자리마다 뿌리 판정이 검증 결과와 같은지, 그리고 무작위 대국(지는 쪽은 아무 단어나, 이기는 쪽은 표의 수)에서 끝날 때까지 모든 국면이 판정되는지(396개 자리, 1,980판, 41,827수, 실패 0)
- 브라우저(Chromium)로 지도 → 음절 → 자리 → 수순을 눌러 확인(콘솔 오류 0)

## 다시 만들기

```sh
g++ -O2 -std=c++17 -o /home/user/AI-/.work/measure/cert2site cert2site.cpp -lz
M=.../model.json      # 기존 지도의 model.json과 catalog.json이 같은 폴더에 있어야 함 (Artifact read로 받음)
python3 build_site_tables.py $M /home/user/AI-/.work/site_tables --jobs 3     # 약 25분, 기록 2GB
python3 make_pages.py /home/user/AI-/.work/site_tables /home/user/AI-/.work/site_pages --model $M --parts-json published/urls.json
for k in 0 1 2; do node check_tables.js /home/user/AI-/.work/site_pages/part$k /home/user/AI-/.work/site_pages/part$k/site-engine.js; done
for k in 0 1 2; do node test_books.js /home/user/AI-/.work/site_pages/part$k /home/user/AI-/.work/site_pages/part$k/site-engine.js 5; done
```

- 게시는 한 번에 64MB·255개 파일까지라, 부분마다 4번에 나눠 올렸습니다(같은 주소에 더하기).
- 새로 확정된 자리가 생기면 `build_site_tables.py`를 다시 돌리면 그 자리만 새로 뽑습니다. 그 뒤 `make_pages.py`와 시험을 거쳐, 바뀐 파일만 다시 올리면 됩니다.
- `published/`: 게시한 두 부분의 `manifest.json`, `pindex.json`, 크기 요약, 주소

## 이식용 묶음

두 부분과 기존 지도의 77개 표를 주소 하나에 모은 폴더입니다. 다른 사이트로 옮길 때 씁니다. 실행·이식 방법과 크기는 `PORTING_KO.md`에 있습니다.

- `make_portable.py`: 묶음 폴더 만들기(`--page-only`는 화면만 다시 만들기)
- `test_portable.js`: 묶음에서 자체 392개와 기존 77개의 무작위 대국 시험
- `pack_portable.py`: `docs`는 `PORTING_KO.template.md`에 묶음의 숫자와 시험 기록(`portable_tests.json`)을 채워 설명서와 `SHA256SUMS.txt`를 씁니다. `zip`은 같은 파일에서 항상 같은 바이트가 나오는 전체 ZIP과, 이전 릴리스에서 바뀐 파일만 담은 갱신본 ZIP을 만듭니다.
- `SHA256SUMS_portable.txt`: 지금 묶음의 파일 806개, 그리고 전체 ZIP과 갱신본 ZIP의 sha256
- 올린 곳: 전달용 저장소 https://github.com/baekjw2435/presentation-map (폴더째), ZIP은 그 저장소의 릴리스(`presentation-map-2026-11-14`, 최신 `presentation-map-2026-11-14b`)
- `PORTING_KO.md`는 묶음 안의 `README_KO.md`와 같은 파일이고, `pack_portable.py docs`가 템플릿에서 만듭니다. 고칠 때는 템플릿을 고친 뒤 묶음과 ZIP을 다시 만들고 전달용 저장소도 함께 바꿉니다.

## 증명서를 다시 만든 15개

이번 연구 첫 묶음(2026-11-11)에서 검증한 15개는 증명서를 그 작업 환경에만 두어 남아 있지 않았습니다. 수순을 보이려고 다시 풀어 검증했고(`../results/recert1/`), 15개 모두 그때의 판정과 같았습니다.
