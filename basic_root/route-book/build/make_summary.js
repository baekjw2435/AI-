// make_summary.js BOOKDIR : writes LINES_KO.md (사람이 읽는 수순 요약) from catalog.json and lines/*.json
"use strict";
const fs = require("fs"), path = require("path");
const dir = path.resolve(process.argv[2]);
const catalog = JSON.parse(fs.readFileSync(path.join(dir, "catalog.json"), "utf8"));
const DEPTH = 2;  // opponent moves shown here; lines/*.json go one deeper
const tag = (a) => (a.how === "증명" ? "" : ` [${a.how}]`) + (a.alts.length ? ` (같은 효과: ${a.alts.join(", ")})` : "");
const out = [];
out.push("# 역·격 필승 수순 요약 (기초사전 루트 817단어)", "",
  "표준두음법칙, 한 경기 안 단어 재사용 금지, 낼 단어가 없으면 패배. 시작 음절을 받는 순간 817단어가 모두 남아 있는 경우입니다.", "",
  "- **받는 쪽**: 상대가 ~역, ~격처럼 그 음절로 끝나는 단어를 내서, 그 음절로 시작해야 하는 사람입니다.",
  "- **낸 쪽**: 그 음절을 넘긴 사람입니다.",
  "- 아래 수순은 엔진(`engine.js`)이 실제로 두는 수를 그대로 적은 것입니다. 상대 응수는 두 수까지만 펼쳤습니다. 더 깊은 수순은 `lines/*.json`(상대 세 수)과 엔진으로 끝까지 볼 수 있습니다.",
  "- 표시: [되받기] 상대가 왕복 쌍의 한쪽을 내면 짝으로 받아 직전 국면으로 돌려놓는 수, [정적] 남은 길만으로 승패가 정해진 자리의 수, (끝) 그 수 뒤 상대가 낼 단어가 없음.", "");
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
    const basis = proof ? `증명 ${proof.nodes.toLocaleString("en-US")}노드 (${proof.proof_sha256.slice(0, 12)}…)` : (f.source || f.note || "");
    out.push(`| ${f.words.join("·")} | ${names[f.result]} | ${basis} | ${f.refutation ? f.refutation.word : ""} |`);
  }
  out.push("");
  for (const p of catalog.proofs.filter((q) => q.start === start)) {
    const t = JSON.parse(fs.readFileSync(path.join(dir, "lines", p.id + ".json"), "utf8"));
    if (p.history.length === 0) {
      out.push(`### ${start} → ${t.answer.word} (받는 쪽이 이기는 수)`, "", `받는 쪽이 ${ro(t.answer.word)} 받은 뒤 낸 쪽의 응수별:${tag(t.answer)}`, "");
    } else if (t.answer) {
      out.push(`### ${start} → ${p.history[0]} (지는 수): 낸 쪽이 ${ro(t.answer.word)} 반박`, "", `받는 쪽이 ${reul(p.history[0])} 내면 낸 쪽이 ${ro(t.answer.word)} 받습니다.${tag(t.answer)} 그 뒤 받는 쪽의 응수별:`, "");
    } else {
      out.push(`### ${start} → ${p.history[0]} (받는 쪽이 이기는 수)`, "", `받는 쪽이 ${reul(p.history[0])} 낸 뒤, 낸 쪽의 응수별 받는 쪽의 승리수:`, "");
    }
    walk(t.replies, DEPTH, "");
    out.push("");
  }
}
fs.writeFileSync(path.join(dir, "LINES_KO.md"), out.join("\n"));
console.log("lines", out.length);
