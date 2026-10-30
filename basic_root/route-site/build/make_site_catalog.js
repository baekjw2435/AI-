// make_site_catalog.js OUTDIR ASTRA_DIST : writes OUTDIR/catalog.json (entries, first moves, syllable grid) with the site
// engines themselves, so the catalog shows exactly what the explorer computes.
"use strict";
const fs = require("fs"), path = require("path");
const dir = path.resolve(process.argv[2]), astraDir = path.resolve(process.argv[3]);
const E = require(path.join(__dirname, "..", "site-engine.js"));
globalThis.RouteSite = E;
const A = require(path.join(__dirname, "..", "astra-adapter.js"));
const model = JSON.parse(fs.readFileSync(path.join(dir, "model.json"), "utf8"));
const manifest = JSON.parse(fs.readFileSync(path.join(dir, "manifest.json"), "utf8"));
const read = (p) => { const b = fs.readFileSync(p); return b.buffer.slice(b.byteOffset, b.byteOffset + b.length); };
E.init(model, manifest, (p) => read(path.join(dir, p)));

// 다른 분의 '한기사 시작글자별 유불리 추정표' 최신판(빨간 원 = 받으면 불리). 표의 칸 순서 그대로.
const GRID = `갑 객 격 곡 교 군 권 규 균 극 급 깽 능 돌 득 락 랑 력 렵 룩 률 릉 맥 맹 멸 명 박 법 벽 변 병 삭 삼 색 섭 솥 숙 순 습 승 식 십
압 야 약 언 업 역 엽 온 완 왕 운 움 웅 율 적 절 젓 존 죄 죽 준 즉 증 직 진 찬 축 충 칙 칠 칭 쾌 큼 탁 탄 탑 탕 퇴 편 폭 표 풍
학 할 합 항 행 향 혁 혈 홍 환 활 훈 휘 흑 흔 흥`.split(/\s+/);
const CIRCLED = new Set("갑 곡 능 룩 맥 벽 삭 색 솥 습 십 약 업 엽 웅 젓 존 죄 충 칙 칭 쾌 큼 탑 혁 활 훈 흔".split(" "));
const NOT_IN_TABLE = new Set(["온", "락", "랑", "력", "렵", "률", "릉"]);  // 온은 그 표에 없고, 락·랑·력·렵·률·릉 칸은 받은 그림에서 가려져 있었음

// 증명 없이 기록만 있는 첫 수(route-book build_book.py의 ASTRA·PENDING과 같은 내용)
const NOTES = {
  "역": Object.fromEntries(Object.entries({ "역할": "W", "역기능": "W", "역세권": "L", "역할극": "L", "역병": "L", "역순": "L", "역전승": "L",
    "역사적": "L", "역설적": "L", "역적": "L", "역동적": "L", "역행": "L" }).map(([w, r]) => [w, r === "W" ? "아스트라 기록상 이기는 수 (이 사이트에는 증명 없음)" : "아스트라 기록상 지는 수 (이 사이트에는 증명 없음)"])),
  "격": { "격돌": "격돌과 돌격이 서로 맞물리는 짝이라 따로 계산해야 해서 아직 판정하지 않음" },
};
const summary = (a) => ({
  status: a.status, how: a.how, best: a.best ? { words: a.best.words, how: a.best.how } : null,
  moves: a.moves.map((m) => ({ words: m.words, status: m.status, how: m.how, reply: m.reply ? { word: m.reply.word, how: m.reply.how } : null })),
});

(async () => {
  const entries = [];
  for (const book of manifest.books) {
    for (const p of book.proofs) {
      const fresh = p.via === 0 && p.history.length === 0, via = p.via === 1 && p.history.length === 1;
      if (!fresh && !via) continue;
      const entry = { start: p.start, prefix: p.history, book: book.id };
      const a = await E.analyze(entry, []);
      if (a.status !== (p.result_for_player_to_move)) throw new Error(`${p.id}: ${a.status} ≠ ${p.result_for_player_to_move}`);
      entries.push({
        id: fresh ? p.syllable : `${p.syllable}<${p.history[0]}`, kind: fresh ? "fresh" : "via", syllable: p.syllable,
        start: p.start, prefix: p.history, via: via ? p.history[0] : null, book: book.id, bookName: book.name,
        proof: { id: p.id, nodes: p.nodes, sha256: p.proof_sha256, source: p.source },
        proofs: book.proofs.map((q) => ({ id: q.id, start: q.start, history: q.history, result: q.result_for_player_to_move, nodes: q.nodes, sha256: q.proof_sha256 })),
        receiverWins: a.status === "W", root: summary(a), notes: fresh ? NOTES[p.syllable] || null : null,
      });
      E.clear();
    }
  }
  // 적: 아스트라의 증명 색인과 계산 엔진
  const gameData = JSON.parse(fs.readFileSync(path.join(astraDir, "game-data.json"), "utf8"));
  await A.init(gameData, read(path.join(astraDir, "proof-817.bin")), new Uint8Array(read(path.join(astraDir, "engine.wasm"))), model);
  const ja = await A.analyze({ start: "적", prefix: [] }, [], 50000);
  entries.push({ id: "적", kind: "astra", syllable: "적", start: "적", prefix: [], via: null, book: "astra", bookName: "적(아스트라)",
                 proof: { id: "astra.jeok", nodes: gameData.proof.states, sha256: gameData.proof.graphSha256, source: "아스트라 적색 루트 연습실 v3" },
                 proofs: [], receiverWins: ja.status === "W", root: summary(ja) });
  const fresh = new Map(entries.filter((e) => e.kind !== "via").map((e) => [e.syllable, e]));
  const grid = GRID.map((s) => {
    const base = E.dueum(s), e = fresh.get(base) || null;
    let inModel = true;
    try { E.position(base, []); } catch (_) { inModel = false; }
    const est = NOT_IN_TABLE.has(s) ? null : CIRCLED.has(s) ? "불리" : "유리";
    return { s, base, entry: e ? e.id : null, inModel, estimate: est,
             agrees: e && est && e.root.status !== "?" ? (est === "유리") === e.receiverWins : null };
  });
  const catalog = { format: "route-site-1", dictionary_sha256: model.dictionary_sha256, entries, grid,
                    verifier: { "verify_v2.py": "9019cd1da696c7cc2db7faf6a37a6fe69614f83697a855884bcbdcca6360e69f",
                                "verify.py": "b08c2491b95d6ccc477b385e648581f970d48961df06ceb6f2a9bd81ad1b5ec3" },
                    totals: { entries: entries.length, table_entries: manifest.total_entries, table_bytes: manifest.total_bytes } };
  fs.writeFileSync(path.join(dir, "catalog.json"), JSON.stringify(catalog));
  console.log(JSON.stringify({ entries: entries.length, receiverWins: entries.filter((e) => e.receiverWins).map((e) => e.id).join(" "),
                               receiverLoses: entries.filter((e) => !e.receiverWins).map((e) => e.id).join(" "), jeok: ja.status,
                               mismatches: grid.filter((g) => g.agrees === false).map((g) => g.s) }));
})().catch((e) => { console.error(e); process.exit(2); });
