# 역습 필승 수순 (817단어 루트)

역을 받은 쪽이 역습으로 이기는 전략을, 상대 응수마다 이기는 응수로 알려 주는 정적 웹 모듈입니다.
서버나 데이터베이스는 필요 없습니다.

## 전제

- 사전: 기초사전 루트 817단어(격언 포함). words.txt의 sha256은 `aa37031019f1e2a95b422ffc2f8d8d1b76b03ca88163b03b17af16ff90c79273`입니다.
- 규칙: 표준두음법칙을 적용하고, 한 경기에서 단어를 다시 쓰지 않으며, 낼 단어가 없으면 집니다.
- 역을 받는 순간 817단어가 모두 남아 있어야 합니다. 루트 안의 단어(능력, 권력 등)로 역을 넘겨받았다면 다른 국면이므로 이 표를 쓰면 안 됩니다.

## 파일

| 파일 | 내용 |
|---|---|
| `index.html` | 단독 실행 페이지: 수순 따라가기와 상대 네 번째 응수까지의 수순표 |
| `engine.js` | 정준화, 정적 역산, 되받기, 승리수 표 조회 |
| `model.json` | 음절 160개, 묶음 718개, 묶음별 단어 (verify_v2.py와 같은 정렬 번호) |
| `strategy.bin` | 승리수 표 655,925개 (헤더 `YSK1`, 개수 u32, 키 u32×2, 묶음 번호 u16, 리틀 엔디언) |
| `test_engine.js` | Node로 돌리는 무작위 대국 시험 |

## 근거

- 승리수 표는 `root_yeok_W_via_yeokseup.jsonl.gz`에서 뽑았습니다. 이 증명은 1,406,006노드이고, sha256은 `5638fbb94a56254229556f08057778da1ab7ce9e3f4af579f8286147242e7d48`입니다.
- 이 증명은 수정하지 않은 verify_v2.py(sha256 `9019cd1d…`)로 검증했습니다. 위치 파일은 `{"initial_syllable":"역","history":[]}`였습니다.
- 표에 없는 자리는 두 가지 규칙으로 처리합니다.
  - 정적 역산: verify_v2의 고정점 규칙과 같습니다.
  - 되받기: 상대가 왕복 쌍이나 짝수로 지운 자기 연결 단어를 내면 그 짝으로 받습니다.
- `engine.js`의 정준화 결과는 verify_v2.py와 782개 국면에서 일치했습니다.
- 무작위 상대 25,000판 이상에서 실패가 0번이었습니다.

## 아스트라 사이트(jeoksaek-route-lab)에 붙이는 방법

1. **별도 페이지로 붙이기 (가장 간단):** 이 폴더를 `dist/yeokseup/`로 복사합니다. `/yeokseup/`에서 바로 열리며, 기존 사이트 파일은 건드리지 않습니다.
2. **기존 화면에 넣기:**
   ```html
   <script src="yeokseup/engine.js" charset="utf-8"></script>
   ```
   ```js
   const [model, buf] = await Promise.all([
     fetch('yeokseup/model.json').then(r => r.json()),
     fetch('yeokseup/strategy.bin').then(r => r.arrayBuffer()),
   ]);
   YeokEngine.init(model, buf);
   // history: 역에서 시작한 실제 단어 순서. 첫 단어는 역습입니다.
   YeokEngine.legalWords(['역습']);            // 상대가 낼 수 있는 단어
   YeokEngine.ourMove(['역습', '습격']);       // { word: '격식', how: '증명', alts: [...] }
   ```
   `how` 값은 `증명`, `되받기`, `정적` 중 하나입니다. `null`이 나오면 이 표의 범위 밖입니다.
3. **주의:** 사이트의 `game-data.json`과 이 `model.json`은 음절·묶음 번호 체계가 다릅니다. 둘을 섞지 말고, 단어 문자열로만 주고받으세요.

## 시험

```sh
node test_engine.js 2000 5   # 무작위 상대 2,000판, 난수 시드 5
```

출력의 `fails`가 0이어야 합니다.
