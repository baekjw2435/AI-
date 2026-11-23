// 시험: 사이트가 쓰는 eoin_solver.wasm을 Node에서 그대로 불러, data.json의 확정 자리(verify_v4 통과) 47,344개의 판정과 맞춥니다.
// 자리마다 사이트와 같은 방법(그 자리의 실제 개수 → set_count/set_cur → position_value)으로 값을 계산합니다.
// 확정된 수는 모두 그 자체가 확정 자리이므로, 이것으로 사이트에 보이는 확정 수의 판정도 모두 맞춰 봅니다.
// usage: node eoinjeong_root/site/test_wasm.js [최대 자리 수]
"use strict";
const fs = require("fs");
const path = require("path");
const D = JSON.parse(fs.readFileSync(path.join(__dirname, "data.json"), "utf8"));
const limit = +(process.argv[2] || Infinity);
(async () => {
  const { instance } = await WebAssembly.instantiate(fs.readFileSync(path.join(__dirname, "eoin_solver.wasm")), {});
  const A = instance.exports, M = D.model;
  M.groups.forEach((g, i) => A.set_group(i, g[0], g[1], g[2]));
  if (A.init(M.vertices, M.groups.length) !== 0) throw new Error("init");
  const known = new Map();
  for (const line of D.nodes) { const [k, v] = line.split(" "); known.set(k, v[0]); }
  let n = 0, same = 0, diff = [];
  const t0 = Date.now();
  for (const [k, r] of known) {
    if (n >= limit) break;
    n++;
    const p = k.split(".").map(Number), h = p.slice(1);
    const cnt = M.groups.map(g => g[2]);
    let cur = D.syllables[p[0]].v;
    for (const w of h) { const g = M.word_group[w]; cnt[g]--; cur = M.groups[g][1]; }
    cnt.forEach((c, g) => A.set_count(g, c));
    A.set_cur(cur);
    let v; do v = A.position_value(1 << 30); while (v === -1);
    const win = v === 1;
    if ((win ? "W" : "L") === r) same++; else diff.push(k);
  }
  console.log(JSON.stringify({ positions: n, same, differ: diff.length, differ_examples: diff.slice(0, 5),
    nodes: A.node_count(),
    seconds: (Date.now() - t0) / 1000 }));
  process.exit(diff.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
