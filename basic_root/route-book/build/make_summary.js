// make_summary.js BOOKDIR : writes LINES_KO.md (사람이 읽는 수순 요약) from catalog.json and lines/*.json
"use strict";
const fs = require("fs"), path = require("path");
const dir = path.resolve(process.argv[2]);
const catalog = JSON.parse(fs.readFileSync(path.join(dir, "catalog.json"), "utf8"));
const DEPTH = 2;  // opponent moves shown here; lines/*.json go one deeper
const tag = (a) => (a.how === "증명" ? "" : ` [${a.how}]`) + (a.alts.length ? ` (같은 효과: ${a.alts.join(", ")})` : "");
const same = (a) => (a.alts.length ? `(${a.alts.join("·")}도 같음)` : "");
const out = [];
const starts = Object.keys(catalog.starts);
out.push(`# ${starts.join("·")} 필승 수순 요약 (기초사전 루트 817단어)`, "",
  "규칙: 표준두음법칙을 적용하고, 한 경기에서 쓴 단어는 다시 쓸 수 없으며, 낼 단어가 없으면 집니다.", "",
  `- **받는 쪽**: 상대가 ${starts.map((x) => "~" + x).join(", ")}처럼 그 음절로 끝나는 단어를 내서, 그 음절로 시작해야 하는 사람입니다.`,
  "- **낸 쪽**: 그 음절을 넘긴 사람입니다.",
  "- 첫 수 분류(이기는 수·지는 수)는 시작 음절을 받는 순간 817단어가 하나도 쓰이지 않았을 때만 맞습니다. 그 음절을 넘긴 단어가 817단어 중 하나면 다른 국면입니다. 수순 중간에는 같은 단어라도 결과가 바뀝니다.",
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
for (const [start, info] of Object.entries(catalog.starts)) {
  out.push(`## ${start}: ${info.receiver_wins ? "받는 쪽 승리" : "낸 쪽 승리"}`, "");
  out.push("| 첫 수 (받는 쪽) | 분류 | 근거 | 낸 쪽의 반박 |", "|---|---|---|---|");
  for (const f of info.first_moves) {
    const proof = f.proof ? catalog.proofs.find((p) => p.id === f.proof) : null;
    const basis = proof ? `증명(국면 ${proof.nodes.toLocaleString("en-US")}개, ${proof.proof_sha256.slice(0, 12)}…)` : (f.source || f.note || "");
    out.push(`| ${f.words.join("·")} | ${names[f.result]} | ${basis} | ${f.refutation ? f.refutation.word : ""} |`);
  }
  out.push("");
  for (const p of catalog.proofs.filter((q) => q.start === start)) {
    const t = JSON.parse(fs.readFileSync(path.join(dir, "lines", p.id + ".json"), "utf8"));
    const firstWords = (w) => { const g = catalog.starts[start].first_moves.find((f) => f.words.includes(w)); const o = g ? g.words.filter((x) => x !== w) : []; return o.length ? `${w}(${o.join("·")}도 같음)` : w; };
    if (p.history.length === 0) {
      out.push(`### ${start} → ${t.answer.word} (받는 쪽이 이기는 수)`, "", `받는 쪽이 ${reul(t.answer.word)} 낸 뒤, 낸 쪽의 응수에 따라 받는 쪽은 이렇게 둡니다.`, "");
    } else if (t.answer) {
      out.push(`### ${start} → ${p.history[0]} (지는 수): 낸 쪽이 ${ro(t.answer.word)} 반박`, "",
        `받는 쪽이 ${reul(firstWords(p.history[0]))} 내면 낸 쪽이 ${ro(t.answer.word + same(t.answer))} 받습니다. 그 뒤 받는 쪽의 응수에 따라 낸 쪽은 이렇게 둡니다.`, "");
    } else {
      out.push(`### ${start} → ${p.history[0]} (받는 쪽이 이기는 수)`, "", `받는 쪽이 ${reul(p.history[0])} 낸 뒤, 낸 쪽의 응수에 따라 받는 쪽은 이렇게 둡니다.`, "");
    }
    walk(t.replies, DEPTH, "");
    out.push("");
  }
}
fs.writeFileSync(path.join(dir, "LINES_KO.md"), out.join("\n"));
console.log("lines", out.length);
