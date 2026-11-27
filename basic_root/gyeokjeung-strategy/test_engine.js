const fs = require("fs"); const E = require("./engine.js");
const model = JSON.parse(fs.readFileSync("model.json", "utf8"));
const games = Number(process.argv[2] || 200); let seed = Number(process.argv[3] || 1);
const rnd = () => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648; };
const buf = f => { const b = fs.readFileSync(f); return b.buffer.slice(b.byteOffset, b.byteOffset + b.length); };
let fails = 0, maxLen = 0; const how = {}, perShard = {}, samples = [];
for (let gi = 0; gi < games; gi++) {
  E.init(model); let loaded = null;
  const h = [model.first];
  while (true) {
    const opp = E.legalWords(h);
    if (!opp.length) break;
    h.push(opp[Math.floor(rnd() * opp.length)]);
    const sh = E.shardFor(h);
    if (sh && loaded !== sh) { if (loaded) throw new Error("shard changed"); E.addTable(buf(model.shards[sh].file)); loaded = sh; }
    const mv = E.ourMove(h);
    if (!mv) { fails++; console.log("FAIL", h.join(">")); break; }
    how[mv.how] = (how[mv.how] || 0) + 1; h.push(mv.word);
    if (rnd() < 0.01) samples.push(h.slice());
  }
  perShard[loaded] = (perShard[loaded] || 0) + 1; maxLen = Math.max(maxLen, h.length);
}

console.log(JSON.stringify({ games, fails, maxLen, how, perShard, samples: samples.length }));
