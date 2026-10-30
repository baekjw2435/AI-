// make_readme.js BOOKDIR : writes README_KO.md for the bundle in BOOKDIR from catalog.json and model.json,
// so the contents, proof table and numbers always match the data that ships with it.
"use strict";
const fs = require("fs"), path = require("path");
const dir = path.resolve(process.argv[2]);
const catalog = JSON.parse(fs.readFileSync(path.join(dir, "catalog.json"), "utf8"));
const model = JSON.parse(fs.readFileSync(path.join(dir, "model.json"), "utf8"));
const tdir = path.join(dir, "tables");
const tbytes = fs.readdirSync(tdir).reduce((s, f) => s + fs.statSync(path.join(tdir, f)).size, 0);
const mb = (b) => (b / 1e6).toFixed(b < 1e7 ? 2 : 0) + "MB";
const E = require(path.join(dir, "engine.js"));
E.init(model, catalog);
const our = (start, h) => { for (;;) { try { return E.ourMove(start, h); } catch (e) {
  if (e.needBucket === undefined) throw e; const b = fs.readFileSync(path.join(dir, E.bucketFile(e.needBucket))); E.addBucket(e.needBucket, b); } } };
const st = catalog.stats;
const n = (x) => x.toLocaleString("en-US");
const starts = Object.keys(catalog.starts);
const jong = (w) => { const c = w.charCodeAt(w.length - 1) - 0xac00; return c >= 0 && c < 11172 ? c % 28 : 0; };
const name = starts.join("·");
const proofs = catalog.proofs;
const L = [];
L.push(`# ${name} 필승 수순 묶음 (route-book-1)`, "",
  `기초사전 루트 817단어(격언 포함)에서 검증된 ${name} 수순을 엔진 하나와 표 하나로 묶었습니다. 사이트 엔진에 넣는 용도입니다. 서버나 데이터베이스 없이 정적 파일만 있으면 됩니다.`, "",
  "## 전제", "",
  `- 사전: 817단어, sha256 \`${model.dictionary_sha256}\``,
  "- 규칙: 표준두음법칙, 한 경기 안에서 단어 재사용 금지, 낼 단어가 없으면 패배",
  `- 판정 근거: 수정하지 않은 \`verify_v2.py\`(sha256 \`${catalog.verifier["verify_v2.py"].slice(0, 8)}…\`)와 \`verify.py\`(\`${catalog.verifier["verify.py"].slice(0, 8)}…\`)로 검증한 증명 ${proofs.length}개`,
  `- 받는 쪽: 상대가 넘긴 음절(${starts.join(", ")})로 시작해야 하는 사람. 낸 쪽: 그 음절을 넘긴 사람.`,
  "- 시작 음절을 받는 순간 817단어가 하나도 쓰이지 않은 국면의 수순입니다. 그 음절을 넘긴 단어가 817단어 중 하나라면(예: 맹공격, 습격) 다른 국면입니다. 첫 수 분류도 이 처음 국면에서만 맞고, 수순 중간에는 같은 단어라도 결과가 바뀔 수 있습니다.", "",
  "## 파일", "",
  "| 파일 | 내용 |", "|---|---|",
  "| `engine.js` | `RouteBook` 엔진(일반 `<script>`와 Node용). 국면 정리(정준화: 결과가 같은 국면을 한 모양으로 맞춤), 남은 단어 연결만으로 승패 판정(정적 역산), 되받기, 승리수 표 찾기 |",
  "| `engine.mjs` | 같은 엔진의 ES 모듈판(`import RouteBook from \"./engine.mjs\"`). 모듈 워커나 `type: module` 사이트에서 씁니다 |",
  "| `model.json` | 음절, 묶음(시작·끝 음절이 같은 단어 모음), 단어. 번호는 verify_v2.py와 같습니다 |",
  "| `catalog.json` | 시작 음절별 첫 수 분류와 증명의 출처(파일 지문인 sha256, 증명 크기) |",
  `| \`tables/b00.bin\` ~ \`tables/bff.bin\` | 승리수 표 256개 파일. 항목 합계 ${n(model.entries)}개, 전체 ${n(tbytes)}바이트(약 ${mb(tbytes)}), 파일당 약 ${mb(tbytes / 256)} |`,
  "| `lines/<증명 id>.json` | 엔진이 두는 수순을 상대 세 수까지 펼친 나무 |",
  "| `LINES_KO.md` | 사람이 읽는 수순 요약. 첫 수 분류와 상대 두 수까지의 수순 |",
  "| `index.html` | 데모 페이지. 파일을 두 번 눌러 열면 자료를 읽지 못합니다. 묶음 폴더에서 `python3 -m http.server`를 실행한 뒤 브라우저로 여세요 |",
  "| `test_book.js` | Node로 돌리는 무작위 대국 시험 |",
  "| `build/` | 표를 만든 도구. 증명에서 표 추출(`proof2tab.c`), 합치기(`build_book.py`), 분류·수순·설명서 생성 |", "",
  "## 무엇이 들어 있나", "",
  "| 시작 | 받는 쪽 첫 수 | 결과 | 엔진이 맡는 쪽 |", "|---|---|---|---|");
const missing = [];
for (const s of starts) {
  const fm = catalog.starts[s].first_moves;
  const wins = fm.filter((f) => f.result === "win" && f.proof), losses = fm.filter((f) => f.result === "loss" && f.proof);
  if (wins.length) L.push(`| ${s} | ${wins.map((f) => f.words.join("·")).join(", ")} | 받는 쪽 승리 | 받는 쪽 |`);
  if (losses.length) L.push(`| ${s} | ${losses.map((f) => f.words.join("·")).join(", ")} | 받는 쪽 패배 (낸 쪽의 반박: ${losses.map((f) => f.refutation.word).join(", ")}) | 낸 쪽 |`);
  for (const f of fm.filter((x) => !x.proof)) missing.push({ s, f });
}
L.push("");
if (missing.length) {
  L.push("**들어 있지 않은 것**");
  for (const { s, f } of missing) L.push(`- ${s} → ${f.words.join("·")}: ${f.result === "pending" ? "보류. " + f.note + "." : (f.result === "win" ? "이기는 수" : "지는 수") + ", " + f.source}`);
  L.push("");
}
L.push("## 쓰는 법", "", "```js",
  "const model = await (await fetch(\"model.json\")).json();",
  "const catalog = await (await fetch(\"catalog.json\")).json();",
  "RouteBook.init(model, catalog);", "",
  "const load = (id) => fetch(RouteBook.bucketFile(id)).then((r) => r.arrayBuffer());",
  "// 시작 음절과, 그 음절부터 실제로 둔 단어들을 넘기면 지금 둘 차례인 쪽의 필승 수를 돌려줍니다.");
let ex = proofs.find((p) => p.history.length === 1 && p.result_for_player_to_move === "W");
const lostRoot = proofs.find((p) => p.history.length === 0 && p.result_for_player_to_move === "L");
if (!ex && lostRoot) ex = { start: lostRoot.start, history: [catalog.starts[lostRoot.start].first_moves[0].words[0]] };
if (ex) {
  const mv = our(ex.start, ex.history);
  L.push(`const mv = await RouteBook.ourMoveAsync(${JSON.stringify(ex.start)}, ${JSON.stringify(ex.history)}, null, load);`,
    `// mv = ${JSON.stringify({ word: mv.word, group: mv.group, how: mv.how, alts: mv.alts }).replace(/,/g, ", ").replace(/:/g, ": ")}`,
    "// group은 model.json의 묶음 번호입니다. 사이트 game-data.json의 묶음 번호와 다릅니다(아래 '사이트에 넣기').");
}
L.push("```", "",
  "- `ourMoveAsync(start, history, initialUsed, loadBucket)`: 필요한 표 조각을 불러온 뒤 수를 돌려줍니다. 한 수에 조각 하나만 씁니다.",
  "- `ourMove(start, history, initialUsed)`: 동기 버전입니다. 필요한 조각이 없으면 `err.needBucket`(조각 번호)를 단 오류를 던집니다. 그 번호의 파일(`bucketFile(id)`)을 받아 `addBucket(id, arrayBuffer)`로 넣은 뒤 다시 부르세요.",
  "- `start`는 시작 음절입니다. 두음 전 모양(예: 력)을 넣어도 verify.py와 같은 규칙으로 바꿔서 찾습니다.",
  "- 돌려주는 값: `{ word, group, how, alts }` 또는 `null`.",
  "  - `how`가 `\"증명\"`이면 검증된 증명의 승리수입니다. 계산 없이 상대를 정적으로 지는 자리로 보내는 수도 여기에 들어갑니다.",
  "  - `\"정적\"`이면 남은 길만으로 승패가 정해진 자리의 수입니다.",
  "  - `\"되받기\"`이면 상대가 왕복 쌍(격돌과 돌격처럼 끝과 시작이 서로 맞물리는 두 단어)의 한쪽을 냈을 때, 나머지 짝으로 받아 그 수 직전 국면으로 돌려놓는 수입니다. 엔진은 그 직전 국면이 상대에게 증명된 패배일 때만 되받기를 돌려줍니다(직전 수가 엔진의 승리수였거나, 증명의 루트에서 둘 차례인 쪽이 지는 국면이거나, 정적으로 지는 국면). 그 밖에는 `null`입니다.",
  "  - `alts`는 같은 묶음의 다른 단어입니다. 어느 것을 내도 결과가 같습니다.",
  "  - `null`이면 그 국면이 표에 없거나, 둘 차례인 쪽이 지는 국면입니다. 엔진은 둘을 구별하지 않습니다. `null`이 아니면 항상 검증된 근거가 있는 승리수입니다.",
  "- `legalWords(start, history, initialUsed)`: 지금 낼 수 있는 단어 목록입니다.",
  "- `firstMoves(start)`: `catalog.json`의 첫 수 분류입니다.",
  "- `initialUsed`: 시작 음절을 받기 전에 이미 쓴 단어들입니다. 보통은 `null`입니다. 넣으면 그 국면의 정준형을 표에서 찾습니다. 찾으면 검증된 승리수입니다. 다만 이 표는 817단어가 모두 남은 시작 국면에서 뻗은 수순만 담고 있어서, 대부분은 찾지 못합니다.", "",
  "**사이트 쪽 주의**",
  "- 표 파일은 `fetch`로 받는 바이너리 파일입니다. 서버가 `.bin` 파일을 그대로 내려 주기만 하면 되고, 파일 형식 지정(MIME)은 상관없습니다.",
  `- 표 전체는 약 ${mb(tbytes)}지만, 한 판에 받는 파일은 보통 10개 안팎, 많아도 30개 정도입니다(파일당 약 ${mb(tbytes / 256)}).`, "",
  "## 사이트(적색 루트 연습실)에 넣기", "",
  "아스트라 사이트 `jeoksaek-route-lab-v3`의 코드와 대조한 내용입니다.", "",
  "**같은 것:** 단어 817개(사전 sha256 동일), 160개 음절의 번호와 순서, 모든 단어의 시작·끝 음절(두음 규칙 결과)이 같습니다.", "",
  "**다른 것:** 묶음 번호입니다. 사이트는 격언 묶음을 맨 끝(717번)에 둡니다. 이 묶음의 0~12번은 사이트에서도 같은 번호이고, 13번(격언)은 사이트 717번, 14번부터는 사이트에서 1 작은 번호입니다. 817단어 전부에서 이 대응을 확인했습니다. 그래도 엔진과는 단어 문자열로만 주고받는 것이 안전합니다.", "",
  "**넣기 전에 꼭 알아야 할 것:** 지금 사이트는 적색·적갈색·적회색·적자생존 중 하나를 먼저 쓰고 시작합니다. 이 묶음은 아무 단어도 쓰이지 않은 채 시작 음절을 받은 국면만 다룹니다. 그래서 지금 사이트 수순에 그대로 붙이면 거의 답하지 못합니다(역·격을 함께 담은 묶음으로 검토했을 때, 사이트 무작위 300판에서 사이트가 이긴다고 확인한 자리 859곳 중 27곳만 답함). 사이트에 '빈 음절에서 시작' 모드를 새로 만들어야 합니다.", "",
  "**넣는 순서 (사이트 파일 기준 제안)**",
  "1. 묶음을 `dist/routebook/`에 복사합니다(engine.mjs, model.json, catalog.json, tables/). 사이트는 `dist`를 정적 파일로 내보내므로 빌드 단계가 따로 필요 없습니다. 호스팅 용량 제한이 있는지는 확인하지 못했습니다.",
  "2. `worker.js`의 `ready()`에서 `engine.mjs`를 import 하고, `routebook/model.json`과 `catalog.json`을 받아 `RouteBook.init`을 부릅니다. 표 파일은 `id => fetch('./routebook/' + RouteBook.bucketFile(id)).then(r => r.arrayBuffer())`로 받습니다. 모듈 워커에서는 `importScripts`를 쓸 수 없습니다.",
  "3. `model.js`의 `STARTS`에 시작 음절을 추가하고, `RouteModel.set`이 첫 단어 없이 시작 음절에서 출발할 수 있게 합니다(첫 단어가 없으면 `syllable = data.nodes.indexOf(variant)`). `presetsFor`에 이 음절용 분기를 넣고, `index.html`에 해당 `data-variant` 버튼을, `app.js`의 `renderContext`에서 적색 전용 문구를 건너뛰는 분기를 넣습니다.",
  "4. `worker.js`의 `start()`에서 이 음절 모드일 때만 `await RouteBook.ourMoveAsync(variant, path, null, loadBucket)`를 부릅니다. 돌려받은 단어는 `data.words`에서 찾아 사이트 묶음 번호로 바꿔 씁니다. 처음 국면의 첫 수 분류는 `RouteBook.firstMoves(variant)`를 씁니다.",
  "5. 적색 시작 수순에는 지금처럼 사이트 자체 판정(proof-817.bin, engine.wasm)을 쓰고, 이 엔진을 부르지 않습니다.", "",
  "## 자료 형식", "",
  "**표 조각 `tables/bXX.bin` (YSK1)**",
  "- 머리: `\"YSK1\"` 4바이트, 항목 수 n(u32, 리틀엔디언)",
  "- 키: (a, b) 쌍 n개(각 u32). (a, b) 순으로 정렬",
  "- 승리 묶음: n개(각 u16)",
  "- 조각 번호 = a의 최상위 바이트(a >>> 24)", "",
  "**국면 키**",
  "1. verify_v2.py와 같은 정준화를 합니다. 순서는 왕복 쌍 제거, 자기 연결 짝수 제거, 도달 불가 제거, 정적 역산, 미확정 핵심 추출입니다.",
  "2. 바이트열 [현재 음절 번호 & 255, 현재 음절 번호 >> 8, 묶음별 남은 개수…]를 만듭니다.",
  "3. 이 바이트열에 FNV-1a 32비트 해시를 두 번 계산합니다. a는 앞에서부터(시작값 2166136261), b는 뒤에서부터(시작값 0x9747b28c)입니다. 두 값 (a, b)가 국면 키(표에서 찾는 번호)입니다.", "",
  "증명 노드의 `v`(현재 음절)와 `c`(묶음별 남은 개수)로 같은 키를 만들었습니다. 만들 때 별도의 64비트 국면 해시로 확인했고, 서로 다른 국면이 같은 키를 갖는 경우는 0건이었습니다.", "",
  "**표에 넣지 않은 국면:** 아래 두 경우는 엔진이 표를 찾기 전에 직접 계산하므로 표에 없습니다.",
  "- 둘 차례인 쪽이 이기는 국면(W) 중, 고른 수 뒤 상대가 남은 연결만으로 이미 지는 국면(증명에서 수가 없는 L)으로 가는 경우",
  "- 남은 연결만으로 이미 이기는 국면(증명에서 수가 없는 W, 정적 승리)", "",
  `**여러 증명에 나온 국면:** 같은 국면이 여러 증명에 있으면 하나만 남겼습니다. 증명별 항목 합계 ${n(st.records)}개에서 중복 ${n(st.duplicate_records_removed)}개를 빼서 ${n(st.unique_states)}개가 됐습니다. 그중 ${n(st.states_with_different_moves)}개 국면은 증명마다 고른 승리수가 달랐습니다. 어느 쪽이든 검증된 승리수이고, 표에는 목록에서 앞에 있는 증명의 수를 넣었습니다.`, "",
  "**`lines/<id>.json`:** `{ start, history, to_move, answer?, replies: [ { words, answer: {word, how, alts}, end?, note?, replies? } ], proof }`. `words`는 결과가 같은 상대 단어 묶음입니다. `to_move`는 `\"receiver\"` 또는 `\"presenter\"` 뒤에, 엔진 쪽이면 `(우리)`, 상대 쪽이면 `(상대)`를 붙인 값입니다. `end: true`는 그 수 뒤 상대가 낼 단어가 없다는 뜻입니다.", "",
  `## 근거 (증명 ${proofs.length}개)`, "",
  "| id | 시작 → 수순 | 둘 차례 | 결과 | 증명 노드 | proof_sha256 앞 16자 |", "|---|---|---|---|---:|---|");
for (const p of proofs) {
  const who = p.player_to_move === "receiver" ? "받는 쪽" : "낸 쪽";
  let res = p.result_for_player_to_move === "W" ? "승" : "패";
  if (p.result_for_player_to_move === "W") {
    const t = JSON.parse(fs.readFileSync(path.join(dir, "lines", p.id + ".json"), "utf8"));
    res += ` (${t.answer.word})`;
  }
  L.push(`| ${p.id} | ${[p.start].concat(p.history).join(" → ")} | ${who} | ${res} | ${n(p.nodes)} | ${p.proof_sha256.slice(0, 16)} |`);
}
L.push("", "표를 만들 때 각 증명 파일의 sha256이 검증기가 보고한 값과 같은지 먼저 확인했습니다. 증명 파일은 커서 이 묶음에 넣지 않았습니다. `catalog.json`의 `verify_seconds`는 각 증명을 검증할 때 걸린 시간입니다.", "");
const extra = path.join(dir, "VERIFY_LOG_KO.md");
if (fs.existsSync(extra)) L.push(fs.readFileSync(extra, "utf8").trim(), "");
fs.writeFileSync(path.join(dir, "README_KO.md"), L.join("\n"));
console.log("README lines", L.length);
