const fs = require("fs");
const E = require("./engine.js");
const model = JSON.parse(fs.readFileSync("model.json", "utf8"));
const buf = fs.readFileSync("strategy.bin");
E.init(model, buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.length));
let seed = Number(process.argv[3] || 1);
const rnd = () => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648; };
const games = Number(process.argv[2] || 200), how = {}, samples = [];
let maxLen = 0, fails = 0;
for (let gi = 0; gi < games; gi++) {
  const h = ["역습"];
  while (true) {
    const opp = E.legalWords(h);
    if (!opp.length) break;                       // opponent stuck: we won
    h.push(opp[Math.floor(rnd() * opp.length)]);
    const mv = E.ourMove(h);
    if (!mv) { fails++; console.log("FAIL", h.join(">")); break; }
    how[mv.how] = (how[mv.how] || 0) + 1;
    h.push(mv.word);
    if (rnd() < 0.02) samples.push(h.slice());
  }
  maxLen = Math.max(maxLen, h.length);
}

console.log(JSON.stringify({ games, fails, maxLen, how, samples: samples.length }));
