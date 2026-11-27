// node test_book.js [BOOKDIR] [GAMES_PER_START] [SEED]
// Plays random games from every proof root in catalog.json (and every same-group word of its first move):
// the engine plays the proven winner, the opponent picks random legal words (often a reciprocal-pair word,
// to exercise 되받기). Fails if the engine ever has no move or the engine's side runs out of words.
"use strict";
const fs = require("fs"), path = require("path");
const dir = path.resolve(process.argv[2] || __dirname), games = +(process.argv[3] || 500);
let seed = +(process.argv[4] || 817);
const rand = () => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648; };
const E = require(path.join(dir, "engine.js"));
const model = JSON.parse(fs.readFileSync(path.join(dir, "model.json"), "utf8"));
const catalog = JSON.parse(fs.readFileSync(path.join(dir, "catalog.json"), "utf8"));
E.init(model, catalog);
function our(start, h) {
  for (;;) {
    try { return E.ourMove(start, h); } catch (e) {
      if (e.needBucket === undefined) throw e;
      const b = fs.readFileSync(path.join(dir, E.bucketFile(e.needBucket)));
      E.addBucket(e.needBucket, b.buffer.slice(b.byteOffset, b.byteOffset + b.length));
    }
  }
}
function opponentWord(start, h) {
  const legal = E.legalWords(start, h);
  if (!legal.length) return null;
  const used = new Set(h);
  const pairs = legal.filter((w) => { const r = model.rev[E.groupOf(w)]; return r >= 0 && model.words[r].some((x) => !used.has(x)); });
  const pool = pairs.length && rand() < 0.3 ? pairs : legal;
  return pool[Math.floor(rand() * pool.length)];
}
let fails = 0, total = 0;
const how = {};
for (const p of catalog.proofs) {
  // entry histories: the proof root, plus the other words of the same first-move group
  const entries = [p.history];
  if (p.history.length === 1) for (const w of model.words[E.groupOf(p.history[0])]) if (w !== p.history[0]) entries.push([w]);
  for (const root of entries) {
    const weFirst = p.result_for_player_to_move === "W";
    let maxLen = 0, wins = 0;
    for (let n = 0; n < games; n++) {
      const h = root.slice();
      let ourTurn = weFirst, ok = true;
      for (;;) {
        if (ourTurn) {
          const mv = our(p.start, h);
          if (!mv) { ok = false; break; }  // no proven move (or no word at all) on our turn
          how[mv.how] = (how[mv.how] || 0) + 1;
          h.push(mv.word);
        } else {
          const w = opponentWord(p.start, h);
          if (!w) break;  // the opponent has no word: we won
          h.push(w);
        }
        ourTurn = !ourTurn;
      }
      total++;
      maxLen = Math.max(maxLen, h.length);
      if (ok) wins++;
      else { fails++; if (fails <= 10) console.log("FAIL", p.start, h.join(" ")); }
    }
    console.log(`${p.id.padEnd(22)} ${(p.start + " " + root.join(" ")).padEnd(14)} games ${games} won ${wins} longest ${maxLen}`);
  }
}
console.log(JSON.stringify({ games: total, fails, moves_by_kind: how }));
process.exit(fails ? 1 : 0);
