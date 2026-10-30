// make_catalog.js BOOKDIR : writes catalog.json (first-move classification) and lines/<id>.json (readable trees)
// using engine.js itself, so the published lines are exactly what the engine plays.
"use strict";
const fs = require("fs"), path = require("path");
const dir = process.argv[2];
const E = require(path.join(dir, "engine.js"));
const model = JSON.parse(fs.readFileSync(path.join(dir, "model.json"), "utf8"));
const meta = JSON.parse(fs.readFileSync(path.join(dir, "_proofs.json"), "utf8"));
E.init(model);
const load = (id) => { const b = fs.readFileSync(path.join(dir, E.bucketFile(id))); E.addBucket(id, b.buffer.slice(b.byteOffset, b.byteOffset + b.length)); };
function our(start, h) {
  for (;;) {
    try { return E.ourMove(start, h); } catch (e) { if (e.needBucket === undefined) throw e; load(e.needBucket); }
  }
}
const TREE_DEPTH = 3;  // opponent moves shown in lines/<id>.json

// opponent replies grouped by word group (words of one group lead to the same canonical position)
function replies(start, h) {
  const seen = new Map();
  for (const w of E.legalWords(start, h)) {
    const g = E.groupOf(w);
    if (!seen.has(g)) seen.set(g, []);
    seen.get(g).push(w);
  }
  return [...seen.values()];
}

let missing = 0;
function oppNode(start, h, depth) {
  const out = [];
  for (const words of replies(start, h)) {
    const hh = h.concat([words[0]]), mv = our(start, hh);
    if (!mv) { missing++; out.push({ words, answer: null }); continue; }
    const node = { words, answer: { word: mv.word, how: mv.how, alts: mv.alts } };
    const next = hh.concat([mv.word]);
    if (!E.legalWords(start, next).length) node.end = true;
    else if (mv.how === "되받기") node.note = "짝으로 되받아 직전 국면으로 돌아감";
    else if (depth > 1) node.replies = oppNode(start, next, depth - 1);
    out.push(node);
  }
  return out;
}

const catalog = { format: "route-book-1", dictionary_sha256: model.dictionary_sha256, verifier: {
  "verify_v2.py": "9019cd1da696c7cc2db7faf6a37a6fe69614f83697a855884bcbdcca6360e69f",
  "verify.py": "b08c2491b95d6ccc477b385e648581f970d48961df06ceb6f2a9bd81ad1b5ec3" },
  proofs: meta.proofs, starts: {} };
fs.mkdirSync(path.join(dir, "lines"), { recursive: true });
for (const start of [...new Set(meta.proofs.map((p) => p.start))]) {
  const proofs = meta.proofs.filter((p) => p.start === start);
  const rootProof = proofs.find((p) => p.history.length === 0);
  const rootMove = our(start, []);
  const first = [];
  for (const words of replies(start, [])) {
    const g = E.groupOf(words[0]);
    const entry = { words, group: g };
    const own = proofs.find((p) => p.history.length === 1 && E.groupOf(p.history[0]) === g);
    if (own && own.result_for_player_to_move === "W") {
      const mv = our(start, [words[0]]);
      Object.assign(entry, { result: "loss", proof: own.id, refutation: { word: mv.word, how: mv.how, alts: mv.alts } });
    } else if (own) {
      Object.assign(entry, { result: "win", proof: own.id });
    } else if (rootMove && rootMove.group === g) {
      Object.assign(entry, { result: "win", proof: rootProof.id });
    } else {
      const astra = (meta.astra_records[start] || {});
      const rec = words.map((w) => astra[w]).find(Boolean);
      const pend = words.map((w) => (meta.pending[start] || {})[w]).find(Boolean);
      if (rec) Object.assign(entry, { result: rec === "W" ? "win" : "loss", proof: null, source: "아스트라 기존 기록 (이 묶음에 증명 표 없음)" });
      else Object.assign(entry, { result: "pending", proof: null, note: pend || "미확정" });
    }
    first.push(entry);
  }
  catalog.starts[start] = { receiver_wins: !!rootProof && rootProof.result_for_player_to_move === "W", first_moves: first };
  // readable trees: every first move the bundle can play out
  for (const p of proofs) {
    let tree;
    if (p.history.length === 0) {
      tree = { start, history: [], to_move: "receiver (우리)", answer: { word: rootMove.word, how: rootMove.how, alts: rootMove.alts },
               replies: oppNode(start, [rootMove.word], TREE_DEPTH) };
    } else if (p.result_for_player_to_move === "W") {
      const mv = our(start, p.history);
      tree = { start, history: p.history, to_move: "presenter (우리)", answer: { word: mv.word, how: mv.how, alts: mv.alts },
               replies: oppNode(start, p.history.concat([mv.word]), TREE_DEPTH) };
    } else {
      tree = { start, history: p.history, to_move: "presenter (상대)", replies: oppNode(start, p.history, TREE_DEPTH) };
    }
    tree.proof = { id: p.id, nodes: p.nodes, proof_sha256: p.proof_sha256 };
    fs.writeFileSync(path.join(dir, "lines", p.id + ".json"), JSON.stringify(tree));
  }
}
fs.writeFileSync(path.join(dir, "catalog.json"), JSON.stringify(catalog, null, 1));
console.log(JSON.stringify({ missing_answers: missing, starts: Object.keys(catalog.starts) }));
if (missing) process.exit(1);
