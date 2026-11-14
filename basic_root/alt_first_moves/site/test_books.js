// test_books.js DIR ENGINE [PLAYOUTS] : the site's own test (route-site/build/test_site.js), for the books of DIR.
//  1. each position analyses to its verified result; at an L root every move is answered
//  2. random games: the winning side plays the engine's move, the losing side a random word; every position on the way
//     must be decided (no "?") until the loser has no word left, and the game must end for the right side
"use strict";
const fs = require("fs"), path = require("path");
const dir = path.resolve(process.argv[2]), E = require(path.resolve(process.argv[3])), plays = +(process.argv[4] || 20);
const model = JSON.parse(fs.readFileSync(path.join(dir, "model.json"), "utf8"));
const manifest = JSON.parse(fs.readFileSync(path.join(dir, "manifest.json"), "utf8"));
function unwasm(b) {   // the site's packing: one custom section of an empty WebAssembly module
  const u = new Uint8Array(b.buffer, b.byteOffset, b.length); let p = 9;
  const leb = () => { let r = 0, s = 1, x; do { x = u[p++]; r += (x & 0x7f) * s; s *= 128; } while (x & 0x80); return r; };
  const size = leb(), end = p + size, nl = leb(); p += nl;
  if (u[0] !== 0 || u[1] !== 0x61 || end !== u.length) throw new Error("bad wasm wrap");
  return b.buffer.slice(b.byteOffset + p, b.byteOffset + end);
}
const load = (dir, p, manifest) => { const b = fs.readFileSync(path.join(dir, p)); return manifest.encoding === "wasm-custom" ? unwasm(b) : b.buffer.slice(b.byteOffset, b.byteOffset + b.length); };
E.init(model, manifest, (p) => load(dir, p, manifest));
let seed = 20261114;
const rnd = (n) => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed % n; };
let fails = 0, games = 0, plies = 0, roots = 0, maxLen = 0;
const hows = {};
const fail = (msg) => { fails++; if (fails <= 30) console.log("FAIL", msg); };
(async () => {
  for (const book of manifest.books) for (const p of book.proofs) {
    roots++;
    const entry = { start: p.start, prefix: p.history, book: book.id };
    const a = await E.analyze(entry, []);
    const want = p.result_for_player_to_move;
    if (a.status !== want) { fail(`${p.id}: root ${a.status} (${a.how}), verified ${want}`); continue; }
    if (want === "L") for (const mv of a.moves) if (mv.status !== "lose") fail(`${p.id}: root move ${mv.words.join("·")} is ${mv.status}`);
    for (let k = 0; k < plays; k++) {
      const h = [];
      for (;;) {
        const x = await E.analyze(entry, h);
        if (x.end) break;
        if (x.status === "W") { hows[x.how] = (hows[x.how] || 0) + 1; h.push(x.best.words[0]); }
        else if (x.status === "L") {
          const bad = x.moves.filter((mv) => mv.status !== "lose");
          if (bad.length) { fail(`${p.id} ${h.join(",")}: losing side's ${bad.map((m) => m.words[0] + ":" + m.status).join(" ")}`); break; }
          const mv = x.moves[rnd(x.moves.length)];
          h.push(mv.words[rnd(mv.words.length)]);
        } else { fail(`${p.id} ${h.join(",")}: undecided (${x.syllable})`); break; }
        plies++;
      }
      if ((want === "W") !== (h.length % 2 === 1)) fail(`${p.id}: game ${h.join(",")} ended for the wrong side`);
      maxLen = Math.max(maxLen, h.length); games++; E.clear();
    }
  }
  console.log(JSON.stringify({ roots, games, plies, longest_game: maxLen, winner_move_reasons: hows, fails }));
  process.exit(fails ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
