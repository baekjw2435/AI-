// make_summary.js BOOKDIR : writes LINES_KO.md (사람이 읽는 수순 요약) from catalog.json and lines/*.json
"use strict";
const fs = require("fs"), path = require("path");
const dir = path.resolve(process.argv[2]);
const catalog = JSON.parse(fs.readFileSync(path.join(dir, "catalog.json"), "utf8"));
const DEPTH = 2;  // opponent moves shown here; lines/*.json go one deeper
const tag = (a) => (a.how === "증명" ? "" : ` [${a.how}]`) + (a.alts.length ? ` (같은 효과: ${a.alts.join(", ")})` : "");
const same = (a) => (a.alts.length ? `(${a.alts.join("·")}도 같음)` : "");
const out = [];
const positions = catalog.positions || Object.entries(catalog.starts).map(([s, v]) => ({ syllable: s, start: s, prefix: [], via: null, ...v }));
const starts = [...new Set(positions.map((q) => q.syllable))];
out.push(`# ${starts.length > 4 ? starts.length + "개 음절" : starts.join("·")} 필승 수순 요약 (기초사전 루트 817단어)`, "",
  ...(starts.length > 4 ? [`음절: ${starts.join(", ")}`, ""] : []),
  "규칙: 표준두음법칙을 적용하고, 한 경기에서 쓴 단어는 다시 쓸 수 없으며, 낼 단어가 없으면 집니다.", "",
  `- **받는 쪽**: 상대가 ${starts.map((x) => "~" + x).join(", ")}처럼 그 음절로 끝나는 단어를 내서, 그 음절로 시작해야 하는 사람입니다.`,
  "- **낸 쪽**: 그 음절을 넘긴 사람입니다.",
  positions.some((q) => q.via)
    ? "- 첫 수 분류(이기는 수·지는 수)는 그 음절을 넘겨받는 순간의 국면에서만 맞습니다. '817단어 밖의 단어로 넘겨받음'은 817단어가 하나도 쓰이지 않은 국면이고, '명칭으로 넘겨받음'처럼 적힌 국면은 그 단어 하나만 쓰인 국면입니다. 수순 중간에는 같은 단어라도 결과가 바뀝니다."
    : "- 첫 수 분류(이기는 수·지는 수)는 시작 음절을 받는 순간 817단어가 하나도 쓰이지 않았을 때만 맞습니다. 그 음절을 넘긴 단어가 817단어 중 하나면 다른 국면입니다. 수순 중간에는 같은 단어라도 결과가 바뀝니다.",
  "- 아래 수순은 엔진(`engine.js`)이 실제로 두는 수를 그대로 적은 것입니다. 상대 응수는 두 수까지만 펼쳤습니다. 더 깊은 수순은 `lines/*.json`(상대 세 수)과 엔진으로 끝까지 볼 수 있습니다.",
  "- 읽는 법: ‘상대 X → **Y**’는 상대가 X를 내면 엔진 쪽이 Y로 받는다는 뜻입니다. 가운뎃점(·)으로 묶은 단어는 시작과 끝 음절이 같아서 결과도 같습니다.",
  "- 표시: [되받기] 상대가 왕복 쌍(끝과 시작이 서로 맞물리는 두 단어)의 한쪽을 내면 나머지 짝으로 받아, 상대가 지는 직전 국면으로 돌려놓는 수. [정적] 남은 단어들의 연결만 따져도 승패가 이미 정해진 자리에서 두는 수. (끝) 그 수 뒤 상대가 낼 단어가 없음.", "");
// 조사: 받침 유무(으로는 ㄹ 받침도 로)
const jong = (w) => { const c = w.charCodeAt(w.length - 1) - 0xac00; return c >= 0 && c < 11172 ? c % 28 : 0; };
const ro = (w) => w + (jong(w) === 0 || jong(w) === 8 ? "로" : "으로");
const reul = (w) => w + (jong(w) === 0 ? "를" : "을");
const names = { win: "이기는 수", loss: "지는 수", pending: "보류" };
function walk(replies, depth, indent) {
  for (const r of replies) {
    const opp = r.words.join("·");
    if (!r.answer) { out.push(`${indent}- 상대 ${opp} → (표에 없음)`); continue; }
    out.push(`${indent}- 상대 ${opp} → **${r.answer.word}**${tag(r.answer)}${r.end ? " (끝)" : ""}`);
    if (r.replies && depth > 1) walk(r.replies, depth - 1, indent + "  ");
  }
}
if (positions.length >= 3) {
  // the syllable a key move hands over, and whether this bundle shows that syllable as a loss for its receiver
  const model = JSON.parse(fs.readFileSync(path.join(dir, "model.json"), "utf8"));
  const groupOf = {}; model.words.forEach((ws, g) => ws.forEach((w) => { groupOf[w] = g; }));
  const endOf = (w) => model.syllables[model.edges[groupOf[w]][1]];
  const freshLoss = new Set(positions.filter((q) => !q.via && !q.receiver_wins).map((q) => q.syllable));
  const handTo = (w) => { const e = endOf(w); return freshLoss.has(e) ? `${e}(받으면 지는 음절)` : e; };
  out.push("## 한눈에 보기", "", "| 국면 | 받는 쪽 | 이유 (핵심 수) | 상대에게 넘어가는 음절 | 증명 크기 |", "|---|---|---|---|---:|");
  for (const pos of positions) {
    const lab = pos.syllable + (pos.via ? `(${ro(pos.via)} 넘겨받음)` : "");
    const wins = pos.first_moves.filter((f) => f.result === "win" && f.proof), losses = pos.first_moves.filter((f) => f.result === "loss" && f.proof);
    let why, hand;
    if (pos.receiver_wins) {
      why = `받는 쪽이 **${wins.map((f) => f.words.join("·")).join(", ")}**${jong(wins[0].words[0]) === 0 || jong(wins[0].words[0]) === 8 ? "로" : "으로"} 이김`;
      hand = endOf(wins[0].words[0]) === pos.syllable ? `${pos.syllable} (같은 음절로 돌아와 차례를 넘김)` : handTo(wins[0].words[0]);
    } else if (losses.length === 1 && pos.first_moves.length === 1) {
      const f = losses[0];
      const r = f.refutation.word;
      why = `낼 수 있는 첫 수가 ${f.words.join("·")} 하나뿐이고, 낸 쪽이 **${r}**${jong(r) === 0 || jong(r) === 8 ? "로" : "으로"} 이김`;
      hand = `${endOf(f.words[0])} → ${endOf(r) === endOf(f.words[0]) ? endOf(r) + " (같은 음절로 돌려보냄)" : handTo(r)}`;
    } else {
      why = `첫 수 ${losses.length}개가 모두 짐: ` + losses.map((f) => `${f.words.join("·")} → ${f.refutation.word}`).join(", ");
      hand = "";
    }
    const root = catalog.proofs.find((p) => p.start === pos.start && (p.via || 0) === pos.prefix.length && p.history.length === pos.prefix.length);
    out.push(`| ${lab} | ${pos.receiver_wins ? "승" : "패"} | ${why} | ${hand} | ${root ? root.nodes.toLocaleString("en-US") : ""} |`);
  }
  out.push("", "‘상대에게 넘어가는 음절’에서 받는 쪽이 지는 국면은 ‘받는 쪽이 넘긴 음절 → 낸 쪽이 넘긴 음절’입니다. 이 표시는 이해를 돕기 위한 것입니다. 그 음절이 이 표에서 ‘받으면 지는 음절’이어도, 실제 국면에는 앞에서 쓴 단어가 빠져 있어서 처음 국면과 같지는 않습니다. 승패의 근거는 각 증명입니다.", "");
}
for (const pos of positions) {
  const label = pos.syllable + (pos.via ? `(${ro(pos.via)} 넘겨받음)` : (catalog.positions && positions.some((q) => q.syllable === pos.syllable && q.via) ? "(817단어 밖의 단어로 넘겨받음)" : ""));
  out.push(`## ${label}: ${pos.receiver_wins ? "받는 쪽 승리" : "낸 쪽 승리"}`, "");
  out.push("| 첫 수 (받는 쪽) | 분류 | 근거 | 낸 쪽의 반박 |", "|---|---|---|---|");
  for (const f of pos.first_moves) {
    const proof = f.proof ? catalog.proofs.find((p) => p.id === f.proof) : null;
    const basis = proof ? `증명(국면 ${proof.nodes.toLocaleString("en-US")}개, ${proof.proof_sha256.slice(0, 12)}…)` : (f.source || f.note || "");
    out.push(`| ${f.words.join("·")} | ${names[f.result]} | ${basis} | ${f.refutation ? f.refutation.word : ""} |`);
  }
  out.push("");
  const mine = catalog.proofs.filter((p) => p.start === pos.start && (p.via || 0) === pos.prefix.length &&
    pos.prefix.every((w, i) => p.history[i] === w));
  for (const p of mine) {
    const t = JSON.parse(fs.readFileSync(path.join(dir, "lines", p.id + ".json"), "utf8"));
    const rel = p.history.slice(pos.prefix.length);
    const firstWords = (w) => { const g = pos.first_moves.find((f) => f.words.includes(w)); const o = g ? g.words.filter((x) => x !== w) : []; return o.length ? `${w}(${o.join("·")}도 같음)` : w; };
    if (rel.length === 0 && !t.answer) {
      out.push(`### ${label}: 받는 쪽의 모든 첫 수에 대한 낸 쪽의 반박`, "", `받는 쪽이 어떤 첫 수를 내도 낸 쪽이 이깁니다. 받는 쪽의 수에 따라 낸 쪽은 이렇게 둡니다.`, "");
    } else if (rel.length === 0) {
      out.push(`### ${label} → ${t.answer.word} (받는 쪽이 이기는 수)`, "", `받는 쪽이 ${reul(t.answer.word)} 낸 뒤, 낸 쪽의 응수에 따라 받는 쪽은 이렇게 둡니다.`, "");
    } else if (t.answer) {
      out.push(`### ${label} → ${rel[0]} (지는 수): 낸 쪽이 ${ro(t.answer.word)} 반박`, "",
        `받는 쪽이 ${reul(firstWords(rel[0]))} 내면 낸 쪽이 ${ro(t.answer.word + same(t.answer))} 받습니다. 그 뒤 받는 쪽의 응수에 따라 낸 쪽은 이렇게 둡니다.`, "");
    } else {
      out.push(`### ${label} → ${rel[0]} (받는 쪽이 이기는 수)`, "", `받는 쪽이 ${reul(rel[0])} 낸 뒤, 낸 쪽의 응수에 따라 받는 쪽은 이렇게 둡니다.`, "");
    }
    walk(t.replies, DEPTH, "");
    out.push("");
  }
}
fs.writeFileSync(path.join(dir, "LINES_KO.md"), out.join("\n"));
console.log("lines", out.length);
