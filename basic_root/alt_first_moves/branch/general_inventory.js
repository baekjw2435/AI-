// general_inventory.js MAIN_DIR OUT.json
// The shallowest 미확인 moves of the existing route map (the general lines that start when a syllable is received with
// no word used), counted with the map's own engine (site-engine.js) and tables. No search, nothing is proven here.
//   receiver loses at the root: every first move of the receiver loses; after each, the winner (the other side) has the
//     proof's answer and maybe other moves the engine cannot decide -> 2nd-move 미확인
//   receiver wins at the root: the receiver's other FIRST moves are the 497-position study (alt_first_moves); after the
//     proof's first move and each reply of the other side, the receiver may have other moves -> 3rd-move 미확인
// A move counts as decided when the engine marks it win or lose (proof, static, one move, 되받기, or 'this also wins').
"use strict";
const fs = require("fs"), path = require("path");
const [dir, out] = process.argv.slice(2);
const E = require(path.join(__dirname, "../../route-site/site-engine.js"));
const model = JSON.parse(fs.readFileSync(path.join(dir, "model.json"), "utf8"));
const manifest = JSON.parse(fs.readFileSync(path.join(dir, "manifest.json"), "utf8"));
const catalog = JSON.parse(fs.readFileSync(path.join(dir, "catalog.json"), "utf8"));
function unwasm(b) {
  const u = new Uint8Array(b.buffer, b.byteOffset, b.length); let p = 9;
  const leb = () => { let r = 0, s = 1, x; do { x = u[p++]; r += (x & 0x7f) * s; s *= 128; } while (x & 0x80); return r; };
  const size = leb(), end = p + size, nl = leb(); p += nl;
  return b.buffer.slice(b.byteOffset + p, b.byteOffset + end);
}
E.init(model, manifest, (p) => { const b = fs.readFileSync(path.join(dir, p)); return manifest.encoding === "wasm-custom" ? unwasm(b) : b.buffer.slice(b.byteOffset, b.byteOffset + b.length); });

(async () => {
  const rows = [];
  for (const e of catalog.entries.filter((x) => x.kind === "fresh")) {
    const entry = { start: e.start, prefix: [], book: e.book };
    const root = await E.analyze(entry, []);
    const row = { syllable: e.syllable, root: root.status, places: [] };
    if (root.status === "L") {                       // the receiver loses: 2nd-move choices of the winner
      for (const mv of root.moves) {
        const a = await E.analyze(entry, [mv.words[0]]);
        const open = a.moves.filter((x) => x.status === "?").map((x) => x.words);
        row.places.push({ line: [mv.words[0]], toMove: a.toMove, status: a.status, best: a.best && a.best.words, open });
      }
    } else if (root.status === "W" && root.best) {   // the receiver wins: 3rd-move choices of the receiver
      const w = root.best.words[0];
      const a1 = await E.analyze(entry, [w]);
      for (const mv of a1.moves) {
        const a = await E.analyze(entry, [w, mv.words[0]]);
        const open = a.moves.filter((x) => x.status === "?").map((x) => x.words);
        row.places.push({ line: [w, mv.words[0]], toMove: a.toMove, status: a.status, best: a.best && a.best.words, open });
      }
    }
    row.open = row.places.reduce((s, p) => s + p.open.length, 0);
    rows.push(row);
  }
  fs.writeFileSync(out, JSON.stringify(rows, null, 1));
  const L = rows.filter((r) => r.root === "L"), W = rows.filter((r) => r.root === "W");
  const sum = (rs) => rs.reduce((s, r) => s + r.open, 0);
  console.log(JSON.stringify({ roots: rows.length, receiver_loses: L.length, open_2nd_move: sum(L), receiver_wins: W.length, open_3rd_move: sum(W),
    other: rows.filter((r) => r.root !== "L" && r.root !== "W").map((r) => r.syllable) }));
})();
