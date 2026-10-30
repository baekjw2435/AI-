# 루트 수순 지도 (route-site)

기초사전 루트 817단어 끝말잇기에서, 검증을 마친 증명으로 수순을 한 수씩 눌러 따라가는 페이지입니다.

- `index.html`: 페이지(지도 + 수순 탐색기). 아티팩트로 게시할 때 문서 틀이 붙습니다.
- `site-engine.js`: 국면 판정 엔진. verify_v2.py와 같은 정준화로 국면 열쇠를 만들고, 승리수 표를 찾아
  한 국면의 모든 후보 단어에 이기는 수 / 지는 수 / 미확인을 붙입니다(근거: 증명, 정적, 한 수, 되받기).
- `astra-adapter.js`: 적 국면 판정. 아스트라 '적색 루트 연습실' v3의 증명 색인(proof-817.bin)과 계산 엔진(engine.wasm)을
  그 사이트와 같은 방식으로 씁니다. 적은 이 저장소의 verify_v2로 검증한 것이 아닙니다.
- `build/site2tab.c`: 증명 하나의 승리수 기록 추출(route-book의 proof2tab에 정준 핵심 크기를 더함).
- `build/site_build.py`: 모든 검증 증명(sha256·국면 수·결과를 verify_v2 출력과 대조)을 묶음별로 모아
  핵심 크기 구간 파일(RSB1: 48비트 열쇠를 Rice 부호, 수는 10비트)로 씁니다.
- `build/make_site_catalog.js`: 진입 국면 목록과 첫 수 분류, 음절 지도(추정표 대조 포함).
- `build/test_site.js`: 모든 증명 루트가 검증 결과와 같은지, 무작위 대국에서 이기는 쪽 수가 비지 않는지 검사.
- `build/pack_site.py`: 게시용 폴더. 아티팩트가 이진 파일을 받지 않아 표를 base64 텍스트로 바꿉니다.

다시 만들기:

```sh
gcc -O2 -o site2tab build/site2tab.c -lz
python3 -I build/site_build.py ./site2tab OUT
node build/test_site.js OUT 3
node build/make_site_catalog.js OUT ASTRA_DIST
python3 -I build/pack_site.py OUT ASTRA_DIST PUB
```

첫 게시(2026-10-30): 증명 72개, 승리수 표 22,267,330항목(117MB, base64로 172MB). 루트 72개 모두 검증 결과와 일치,
무작위 대국 216판(4,062수)에서 미확인 국면 0.
