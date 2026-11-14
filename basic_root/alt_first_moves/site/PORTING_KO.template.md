# 제시 단어 수순 지도: 이식용 묶음 ({{date}})

폴더 `presentation-map/` 하나를 정적 웹 서버에 올리면, 주소 하나(`index.html`)에서 제시 단어를 고르고 그 수순에 필요한 표 파일만 불러옵니다. 서버 쪽 프로그램은 필요 없습니다. 기존 지도에 연결하던 {{old}}개도 표를 묶음 안에 넣었습니다. 바깥 주소는 글꼴(Google Fonts)과 증명서 내려받기 링크(GitHub 릴리스)뿐이고, 둘 다 없어도 화면과 판정은 작동합니다.

## 1. 크기

| 항목 | 값 |
|---|---|
| 파일 수 | {{files}}개 (표 {{tables}}개, 페이지·엔진·목록 5개, 이 설명서, `SHA256SUMS.txt`) |
| 전체 용량 | {{total_bytes}}바이트 (약 {{total_mb}}MB). 이 중 표 {{tables}}개가 {{table_bytes}}바이트 |
| 가장 큰 파일 | `{{largest_path}}`: {{largest_bytes}}바이트 (약 {{largest_mb}}MB) |
| 표 파일 하나의 크기 | 모두 {{table_max_mb}}MB 이하 |
| 한 수순에 내려받는 양 | 수순을 한 수 진행할 때 보통 표 파일 0~1개. {{test_browser_fetch}} |

ZIP 파일의 크기와 sha256은 ZIP 안에 넣을 수 없어서 저장소의 `SHA256SUMS_portable.txt`와 릴리스 설명에 따로 적습니다.

## 2. 들어 있는 것

| 파일 | 크기(바이트) | 하는 일 |
|---|---:|---|
| `index.html` | {{size:index.html}} | 화면: 음절 지도 → 제시 단어 목록 → 수순 |
| `site-engine.js` | {{size:site-engine.js}} | 판정 엔진. 기존 '루트 수순 지도'와 같은 파일 |
| `model.json` | {{size:model.json}} | 817단어 모델(단어 묶음과 음절) |
| `manifest.json` | {{size:manifest.json}} | 표 목록: 책 {{books}}개, 파일 {{tables}}개, 항목 {{entries}}개 |
| `pindex.json` | {{size:pindex.json}} | 제시 자리 {{targets}}개 목록(자체 {{own}} · 기존 {{old}} · 미확정 {{open}})과 진행률 |
| `t/<책>/NN.wasm` | {{table_bytes}} ({{tables}}개) | 승리수 표 |
| `README_KO.md` | | 이 설명서 |
| `SHA256SUMS.txt` | | 파일마다 sha256 |

표(책)는 두 종류입니다.

| 표 | 책 | 파일 | 크기 | 항목 |
|---|---:|---:|---:|---:|
| 자체 수순: 이 연구의 v4 증명서로 만든 표 (이름이 `p`로 시작, 자리마다 하나) | {{own_books}} | {{own_files}} | {{own_bytes}} | {{own_entries}} |
| 기존 수순: 기존 지도에서 {{old}}개 증명이 들어 있는 표만 그대로 복사 | {{old_books}} | {{old_files}} | {{old_bytes}} | {{old_entries}} |

`.wasm`은 표를 WebAssembly 파일의 사용자 구역에 감싼 것입니다. 기존 지도와 같은 형식입니다. 페이지는 이 파일을 실행하지 않고 바이트로 읽기만 하므로, 서버가 어떤 형식(MIME)으로 보내든 상관없습니다.

## 3. 실행하는 방법

```sh
unzip {{zip_name}}      # presentation-map/ 폴더가 생깁니다
cd presentation-map
sha256sum -c SHA256SUMS.txt                # 파일이 온전한지 확인(선택)
python3 -m http.server 8000                # 아무 정적 서버나 됩니다
# 브라우저에서 http://localhost:8000/ 을 엽니다
```

- 파일을 더블클릭해 `file://`로 열면 작동하지 않습니다. 브라우저가 `file://`에서는 파일 불러오기(fetch)를 막기 때문입니다. 꼭 웹 서버로 엽니다.
- 처음 열 때 `model.json`, `manifest.json`, `pindex.json`(합계 약 {{boot_mb}}MB)을 받습니다. 표 파일은 수순을 볼 때 필요한 것만 그때그때 받습니다.

## 4. 이식하는 방법

1. **폴더 구조와 파일 이름을 그대로 둡니다.** 페이지는 모든 파일을 자기 위치 기준의 상대 경로(`manifest.json`, `t/…/NN.wasm`)로 부릅니다. 그래서 기존 연습실의 하위 폴더(예: `…/presentation-map/`)에 통째로 넣어도 됩니다.
2. **표 파일은 고치거나 다시 압축하지 않습니다.** 바이트가 하나라도 바뀌면 판정이 틀어집니다. 옮긴 뒤 `sha256sum -c SHA256SUMS.txt`로 확인합니다.
3. **한 주소에 모두 올립니다.** {{old}}개 기존 수순의 표도 묶음 안에 있으므로, 기존 지도 주소가 없어도 됩니다. 페이지 안의 연결은 모두 같은 페이지 안(`#e…`)입니다.
4. 올릴 곳에 용량 제한이 있으면 다음 수치를 보면 됩니다: 전체 약 {{total_mb}}MB, 파일 {{files}}개, 가장 큰 파일 약 {{largest_mb}}MB. 표를 다른 주소에 따로 두려면 `index.html`의 파일 경로를 고쳐야 하고, 그 주소는 CORS(다른 주소에서 파일을 읽도록 허락)를 열어 두어야 합니다.
5. 기존 연습실 페이지 안에 직접 넣으려면 `index.html`의 `<style>`·`<script>` 부분과 `site-engine.js`를 옮기고, 같은 폴더 기준 경로가 맞는지 확인합니다. 화면 요소의 id(`#tally`, `#line`, `#now`, `#moves` 등)는 페이지 안에서 겹치지 않아야 합니다.
6. **새 확정이 생겼을 때.** 릴리스에 전체 ZIP과 함께 갱신본(`…-update.zip`)을 냅니다. 갱신본에는 이전 묶음에서 새로 생기거나 바뀐 파일, `SHA256SUMS.txt`, 안내 `UPDATE_KO.txt`가 들어 있습니다. 이미 올린 폴더 위에 풀어 덮어쓰고(지울 파일이 있으면 `UPDATE_KO.txt`에 적혀 있음), `sha256sum -c SHA256SUMS.txt`로 확인합니다. 이미 있는 표 파일은 바뀌지 않으므로 새로 올릴 양이 적습니다.

## 5. 보이는 내용과 지키는 원칙

- **세 가지 구분**
  - 자체 수순 {{own}}개: 그 자리(w로 t 제시)의 v4 증명서(verify_v4 통과) 하나로 만든 표입니다.
  - 기존 수순 {{old}}개: 예전 연구의 증명(verify_v2 통과)입니다. 기존 '루트 수순 지도'에서 그 증명이 들어 있는 표로 엽니다.
  - 미확정 {{open}}개: 표가 없고, 목록에 '미확정'으로만 보입니다.
- **제시자 / 받은 쪽.** 제시자는 `~t` 단어를 내서 상대에게 t를 넘긴 사람(낸 쪽)이고, 받은 쪽은 t를 받은 사람입니다. 판정은 항상 '제시자 패 · 받은 쪽 승'처럼 두 사람을 함께 적습니다. 차례도 '제시자(합격을 낸 사람) 차례'처럼 보입니다. 용어는 `../TERMS_KO.md`를 따릅니다.
- **사용 이력 유지.** 자리마다 검증할 때 쓴 이력 그대로 엽니다. 자체 수순은 그 자리의 증명서 표만 씁니다. 기존 수순은 '시작 음절 s를 받고 w를 낸 자리'로 엽니다. 기존 지도에서 s를 고르고 w를 눌렀을 때와 같은 국면이고, 같은 표입니다. 다른 제시 단어의 결과를 가져다 붙이지 않습니다.
- **연쇄 표.** 기존 지도에는 격·역·칭존처럼 증명 여러 개를 한 표에 모은 것이 있습니다. {{old}}개는 각각 그 자리의 증명(시작 s, 이력 w)이 실제로 들어 있는 표에 연결했습니다. 예를 들어 명칭·삼인칭·극존칭·병존은 칭존 표에 연결됩니다.
- **이기는 쪽의 다른 선택지는 미확인.** 증명이 고른 수만 '이기는 수'로 보입니다. 엔진이 같은 표로 한 수 앞까지 확인한 수는 '이 수도 이김'으로 보입니다. 기존 지도와 같은 규칙입니다.
- **진행률 {{verified}}/{{targets}}**은 이번 추가 조사 대상의 진행률입니다. 모든 제시 단어나 모든 후속 갈래를 분석한 비율이 아닙니다.

## 6. 확인한 것

| 시험 | 결과 |
|---|---|
| `check_tables.js`: 표 {{test_check_files}}개를 엔진의 해독기로 끝까지 풀어 sha256 비교 | 다른 것 {{test_check_bad}} |
| `test_portable.js`: 자리마다 뿌리 판정을 확인하고 무작위 대국 진행(지는 쪽은 아무 단어, 이기는 쪽은 표의 수) | {{test_portable}} |
| 브라우저(Chromium): {{test_browser_words}}을 5수씩 진행 | {{test_browser}} |

## 7. 다시 만들기

```sh
# 부분들(make_pages.py 결과)과 기존 지도의 파일(model.json, manifest.json, catalog.json, t/…)이 있어야 합니다
python3 make_portable.py /home/user/AI-/.work/site_pages MAIN_DIR /home/user/AI-/.work/portable/presentation-map
python3 make_portable.py --page-only OUT_DIR           # 화면(index.html)만 다시 만들 때
node check_tables.js OUT_DIR OUT_DIR/site-engine.js
node test_portable.js OUT_DIR 2 5
python3 pack_portable.py docs OUT_DIR --tests portable_tests.json --date DATE --zip-name NAME.zip   # 설명서·SHA 목록
python3 pack_portable.py zip OUT_DIR NAME.zip [--base-sums 이전_SHA256SUMS.txt --update-zip NAME-update.zip]
```

설명서의 숫자는 `pack_portable.py docs`가 묶음과 시험 기록(`portable_tests.json`)에서 채웁니다. ZIP은 같은 파일에서 항상 같은 바이트가 나오게 만듭니다. 항목은 이름순이고, 시각은 2026-11-14 00:00으로 고정하며, 모든 파일을 deflate(9단계)로 압축합니다. 표는 이미 촘촘하게 부호화되어 있어 약 3%만 줄어듭니다.
