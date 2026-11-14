// test_portable.js DIR [GAMES_OWN] [GAMES_OLD] : every openable position of the bundle's pindex.json
//  1. the position analyses to its recorded verdict (W: t's receiver wins = the presenter loses; L: the presenter wins)
//  2. random games: the winning side plays the engine's move, the losing side a random word; every position on the way is
//     decided until the loser has no word left, and the game ends for the right side
"use strict";
const fs = require("fs"), path = require("path");
const dir = path.resolve(process.argv[2]), gOwn = +(process.argv[3] || 2), gOld = +(process.argv[4] || 5);
const E = require(path.join(dir, "site-engine.js"));
const model = JSON.parse(fs.readFileSync(path.join(dir, "model.json"), "utf8"));
const manifest = JSON.parse(fs.readFileSync(path.join(dir, "manifest.json"), "utf8"));
const pindex = JSON.parse(fs.readFileSync(path.join(dir, "pindex.json"), "utf8"));
function unwasm(b) {
  const u = new Uint8Array(b.buffer, b.byteOffset, b.length); let p = 9;
  const leb = () => { let r = 0, s = 1, x; do { x = u[p++]; r += (x & 0x7f) * s; s *= 128; } while (x & 0x80); return r; };
  const size = leb(), end = p + size, nl = leb(); p += nl;
  return b.buffer.slice(b.byteOffset + p, b.byteOffset + end);
}
E.init(model, manifest, (p) => unwasm(fs.readFileSync(path.join(dir, p))));
let seed = 7;
const rnd = (n) => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed % n; };
const res = { own: { roots: 0, games: 0, plies: 0 }, old: { roots: 0, games: 0, plies: 0 } }; let fails = 0;
const fail = (m) => { fails++; if (fails <= 30) console.log("FAIL", m); };
(async () => {
  for (const g of pindex.groups) for (const it of g.items) {
    if (it.kind === "open") continue;
    const r = res[it.kind]; r.roots++;
    const entry = { start: it.start, prefix: [it.words[0]], book: it.book };
    const a = await E.analyze(entry, []);
    if (a.status !== it.status) { fail(`${it.id} (${it.kind}): root ${a.status} (${a.how}), recorded ${it.status}`); continue; }
    for (let k = 0; k < (it.kind === "own" ? gOwn : gOld); k++) {
      const h = [];
      for (;;) {
        const x = await E.analyze(entry, h);
        if (x.end) break;
        if (x.status === "W") h.push(x.best.words[0]);
        else if (x.status === "L") {
          const bad = x.moves.filter((mv) => mv.status !== "lose");
          if (bad.length) { fail(`${it.id} ${h.join(",")}: losing side's ${bad.map((m) => m.words[0] + ":" + m.status).join(" ")}`); break; }
          const mv = x.moves[rnd(x.moves.length)]; h.push(mv.words[rnd(mv.words.length)]);
        } else { fail(`${it.id} ${h.join(",")}: undecided (${x.syllable})`); break; }
        r.plies++;
      }
      if ((it.status === "W") !== (h.length % 2 === 1)) fail(`${it.id}: game ended for the wrong side`);
      r.games++; E.clear();
    }
  }
  console.log(JSON.stringify({ ...res, fails }));
  process.exit(fails ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
