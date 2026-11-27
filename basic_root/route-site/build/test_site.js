// test_site.js OUTDIR [PLAYOUTS] : checks the site tables against every proof they came from.
//  1. each proof root analyses to its verified result; at an L root every move is answered
//  2. random games from each root: the winning side plays the engine's move, the losing side a random move;
//     every position on the way must be decided (no "?") until the loser has no word left
"use strict";
const fs = require("fs"), path = require("path");
const dir = path.resolve(process.argv[2]), plays = +(process.argv[3] || 20);
const E = require(path.join(__dirname, "..", "site-engine.js"));
const model = JSON.parse(fs.readFileSync(path.join(dir, "model.json"), "utf8"));
const manifest = JSON.parse(fs.readFileSync(path.join(dir, "manifest.json"), "utf8"));
E.init(model, manifest, (p) => { const b = fs.readFileSync(path.join(dir, p)); return b.buffer.slice(b.byteOffset, b.byteOffset + b.length); });
let seed = 12345;
const rnd = (n) => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed % n; };
let fails = 0, games = 0, plies = 0, roots = 0;
const fail = (msg) => { fails++; if (fails <= 30) console.log("FAIL", msg); };
(async () => {
  for (const book of manifest.books) {
    for (const p of book.proofs) {
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
          if (x.status === "W") { h.push(x.best.words[0]); }
          else if (x.status === "L") {
            const bad = x.moves.filter((mv) => mv.status !== "lose");
            if (bad.length) { fail(`${p.id} ${h.join(",")}: losing side's ${bad.map((m) => m.words[0] + ":" + m.status).join(" ")}`); break; }
            const mv = x.moves[rnd(x.moves.length)];
            h.push(mv.words[rnd(mv.words.length)]);
          } else { fail(`${p.id} ${h.join(",")}: undecided (${x.syllable})`); break; }
          plies++;
        }
        // the side that cannot move must be the root's loser
        const lastMoverIsRootSide = h.length % 2 === 1;
        if ((want === "W") !== lastMoverIsRootSide) fail(`${p.id}: game ${h.join(",")} ended for the wrong side`);
        games++;
        E.clear();
      }
    }
  }
  console.log(JSON.stringify({ roots, games, plies, fails }));
  process.exit(fails ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
