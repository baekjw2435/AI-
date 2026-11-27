// AstraRoute: 아스트라의 '적색 루트 연습실'(jeoksaek-route-lab v3) 자료로 적 국면을 판정합니다.
//
// 증명 색인(proof-817.bin, RLP2: 133개 증명에서 뽑은 정준 국면 649,013개)과 계산 엔진(engine.wasm)을
// 그 사이트의 proof.js·worker.js와 같은 방식으로 씁니다. 판정 근거는 아스트라의 증명과 검증 기록이며,
// 이 저장소의 verify_v2.py로 검증한 것은 아닙니다. 단어 묶음 번호는 단어 이름으로 맞춥니다.
var AstraRoute = (function () {
  var U64 = function (x) { return BigInt.asUintN(64, x); };
  var data, oracle, engine, ourModel, toTheir, fromTheir, nodeOf, ourOwner;

  // 아스트라 proof.js의 ProofOracle (동작은 같고, 모듈 문법만 뺐습니다)
  function ProofOracle(d, buffer) {
    this.data = d; this.view = new DataView(buffer);
    if (buffer.byteLength < 48 || new TextDecoder().decode(new Uint8Array(buffer, 0, 4)) !== "RLP2") throw Error("적 검증 자료의 형식이 맞지 않아요.");
    this.size = this.view.getUint32(4, true);
    var fingerprint = Array.from(new Uint8Array(buffer, 12, 32), function (x) { return x.toString(16).padStart(2, "0"); }).join("");
    if (d.dictionaryMode !== "817_with_gyeogeon" || d.proof.format !== "RLP2" || this.view.getUint16(8, true) !== d.nodes.length ||
        this.view.getUint16(10, true) !== d.groups.length || fingerprint !== d.proof.graphSha256 || buffer.byteLength !== 48 + this.size * 18)
      throw Error("적 단어 목록과 검증 자료가 맞지 않아요.");
    var self = this;
    this.out = Array.from(d.nodes, function () { return []; }); this.inc = Array.from(d.nodes, function () { return []; });
    var pairs = new Map(d.groups.map(function (g, i) { return [g.u + ":" + g.v, i]; }));
    this.reverse = d.groups.map(function (g) { var r = pairs.get(g.v + ":" + g.u); return r === undefined ? -1 : r; });
    d.groups.forEach(function (g, i) { self.out[g.u].push(i); self.inc[g.v].push(i); });
    var seed = 0x49256188fba2213n;
    var mix = function () { seed = U64(seed + 0x9e3779b97f4a7c15n); var z = seed; z = U64((z ^ (z >> 30n)) * 0xbf58476d1ce4e5b9n); z = U64((z ^ (z >> 27n)) * 0x94d049bb133111ebn); return z ^ (z >> 31n); };
    this.za = []; this.zb = []; this.na = []; this.nb = [];
    for (var g = 0; g < d.groups.length; g++) { this.za[g] = [0n]; this.zb[g] = [0n]; for (var k = 1; k < 8; k++) { this.za[g][k] = mix(); this.zb[g][k] = mix(); } }
    for (var u = 0; u < d.nodes.length; u++) { this.na[u] = mix(); this.nb[u] = mix(); }
  }
  ProofOracle.prototype.lookup = function (a, b) {
    var lo = 0, hi = this.size, v = this.view;
    while (lo < hi) { var m = (lo + hi) >>> 1, p = 48 + m * 18, x = v.getBigUint64(p, true), y = v.getBigUint64(p + 8, true); if (x < a || (x === a && y < b)) lo = m + 1; else hi = m; }
    return lo < this.size && v.getBigUint64(48 + lo * 18, true) === a && v.getBigUint64(56 + lo * 18, true) === b ? v.getInt16(64 + lo * 18, true) : 0;
  };
  ProofOracle.prototype.normalize = function (s, raw) {
    var c = raw.slice(), groups = this.data.groups, nodes = this.data.nodes, g, u;
    for (g = 0; g < c.length; g++) { var r = this.reverse[g]; if (r === g) c[g] &= 1; else if (r > g) { var t = Math.min(c[g], c[r]); c[g] -= t; c[r] -= t; } }
    var status = new Int8Array(nodes.length).fill(-1), left = new Uint16Array(nodes.length), loops = new Int16Array(nodes.length).fill(-1), queue = [], action = -1;
    for (u = 0; u < nodes.length; u++) { this.out[u].forEach(function (g2) { if (c[g2]) { if (groups[g2].v === u) loops[u] = g2; else left[u] += c[g2]; } }); if (!left[u]) { status[u] = loops[u] >= 0 ? 1 : 0; if (u === s) action = loops[u]; queue.push(u); } }
    for (var at = 0; at < queue.length; at++) {
      var v = queue[at], inc = this.inc[v];
      for (var i = 0; i < inc.length; i++) {
        g = inc[i]; u = groups[g].u;
        if (!c[g] || status[u] !== -1) continue;
        if (status[v] === 0) { status[u] = 1; if (u === s) action = g; queue.push(u); }
        else { left[u] -= c[g]; if (!left[u]) { status[u] = loops[u] >= 0 ? 1 : 0; if (u === s) action = loops[u]; queue.push(u); } }
      }
    }
    if (status[s] !== -1) return { value: Boolean(status[s]), action: action };
    var seen = new Uint8Array(nodes.length); queue.length = 0; queue.push(s); seen[s] = 1;
    for (at = 0; at < queue.length; at++) this.out[queue[at]].forEach(function (g2) { var v2 = groups[g2].v; if (c[g2] && status[v2] === -1 && !seen[v2]) { seen[v2] = 1; queue.push(v2); } });
    var a = this.na[s], b = this.nb[s];
    for (g = 0; g < c.length; g++) if (c[g] && seen[groups[g].u] && status[groups[g].v] === -1) { a ^= this.za[g][c[g]]; b ^= this.zb[g][c[g]]; }
    var answer = this.lookup(a, b);
    return { value: answer ? answer > 0 : null, action: answer > 0 && answer < 32767 ? answer - 1 : -1 };
  };
  ProofOracle.prototype.evaluate = function (s, counts) {
    var root = this.normalize(s, counts);
    if (root.value === false || (root.value === true && root.action >= 0)) return root;
    var out = this.out[s];
    for (var i = 0; i < out.length; i++) {
      var g = out[i];
      if (!counts[g]) continue;
      counts[g]--; var child = this.normalize(this.data.groups[g].v, counts); counts[g]++;
      if (child.value === false) return { value: true, action: g };
    }
    return root;
  };

  function init(gameData, proofBuffer, wasmBytes, model) {
    data = gameData; ourModel = model;
    oracle = new ProofOracle(data, proofBuffer);
    var nodeIndex = new Map(data.nodes.map(function (s, i) { return [s, i]; }));
    nodeOf = model.syllables.map(function (s) { var i = nodeIndex.get(s); if (i === undefined) throw Error("적 자료에 없는 음절: " + s); return i; });
    ourOwner = Object.create(null);
    model.words.forEach(function (list, g) { list.forEach(function (w) { ourOwner[w] = g; }); });
    toTheir = new Array(model.edges.length).fill(-1); fromTheir = new Array(data.groups.length).fill(-1);
    data.groups.forEach(function (tg, i) {
      var ours = tg.words.map(function (w) { return ourOwner[data.words[w].text]; });
      if (ours.some(function (g) { return g !== ours[0]; }) || ours[0] === undefined || model.words[ours[0]].length !== tg.words.length) throw Error("적 단어 묶음이 맞지 않아요.");
      toTheir[ours[0]] = i; fromTheir[i] = ours[0];
    });
    if (toTheir.some(function (x) { return x < 0; })) throw Error("적 단어 묶음이 맞지 않아요.");
    return WebAssembly.instantiate(wasmBytes, {}).then(function (mod) {
      engine = mod.instance.exports;
      if (engine.group_count() !== data.groups.length || engine.node_count() !== data.nodes.length) throw Error("적 계산 엔진과 단어 목록이 맞지 않아요.");
      engine.init();
    });
  }

  function theirCounts(counts) { var c = new Uint8Array(data.groups.length); for (var g = 0; g < counts.length; g++) c[toTheir[g]] = counts[g]; return c; }

  // 아스트라 worker.js의 evaluate: 증명 색인, 없으면 한도 안의 완전 탐색(한도를 넘으면 미확인)
  function evaluate(s, counts, budget) {
    var proven = oracle.evaluate(s, counts);
    if (proven.value === false || (proven.value === true && proven.action >= 0)) return { value: proven.value, action: proven.action, how: "아스트라 증명" };
    new Uint8Array(engine.memory.buffer, engine.input_ptr(), counts.length).set(counts);
    var raw = engine.solve(s, budget), value = raw === 2 ? null : Boolean(raw);
    if (value !== null && proven.value !== null && value !== proven.value) throw Error("적 판정 자료가 서로 맞지 않는 수순이에요.");
    if (value === null) return { value: proven.value, action: proven.action, how: proven.value === null ? "" : "아스트라 증명" };
    return { value: value, action: engine.action(), how: "아스트라 계산" };
  }

  // RouteSite.analyze와 같은 모양의 결과
  function analyze(entry, history, budget) {
    budget = budget || 50000;
    var p = RouteSite.position(entry.start, entry.prefix.concat(history)), s = nodeOf[p.cur], c = theirCounts(p.counts);
    var res = { syllable: ourModel.syllables[p.cur], toMove: history.length % 2 ? "presenter" : "receiver", status: "?", how: "", best: null, moves: [], end: false, source: "astra" };
    var legal = ourModel.outgoing[p.cur].filter(function (g) { return p.counts[g] > 0; });
    if (!legal.length) { res.end = true; res.status = "L"; res.how = "낼 단어 없음"; return Promise.resolve(res); }
    var root = evaluate(s, c, budget);
    res.moves = legal.map(function (g) {
      var words = ourModel.words[g].filter(function (w) { return !p.used[w]; }), tg = toTheir[g], mv = { group: g, words: words, status: "?", how: "", reply: null };
      c[tg]--; var child = evaluate(data.groups[tg].v, c, budget); c[tg]++;
      if (child.value === false) { mv.status = "win"; mv.how = child.how; }
      else if (child.value === true) {
        mv.status = "lose"; mv.how = child.how;
        if (child.action >= 0) {
          var rg = fromTheir[child.action], used2 = Object.assign(Object.create(null), p.used); used2[words[0]] = true;
          var rw = ourModel.words[rg].filter(function (w) { return !used2[w]; });
          if (rw.length) mv.reply = { group: rg, word: rw[0], how: child.how };
        }
      }
      return mv;
    });
    var byGroup = {}; res.moves.forEach(function (mv) { byGroup[mv.group] = mv; });
    if (root.value === true) {
      res.status = "W"; res.how = root.how;
      if (root.action >= 0) res.best = byGroup[fromTheir[root.action]] || null;
      if (!res.best) res.best = res.moves.filter(function (mv) { return mv.status === "win"; })[0] || null;
      if (res.best && res.best.status === "?") { res.best.status = "win"; res.best.how = root.how; }
    } else if (root.value === false) {
      res.status = "L"; res.how = root.how;
      res.moves.forEach(function (mv) { if (mv.status === "?") { mv.status = "lose"; mv.how = root.how; } });
    } else {
      var win = res.moves.filter(function (mv) { return mv.status === "win"; })[0];
      if (win) { res.status = "W"; res.how = win.how; res.best = win; }
      else if (res.moves.every(function (mv) { return mv.status === "lose"; })) { res.status = "L"; res.how = "모든 수가 짐"; }
    }
    res.moves.sort(function (a, b) { return a.words[0] < b.words[0] ? -1 : a.words[0] > b.words[0] ? 1 : 0; });
    return Promise.resolve(res);
  }

  return { init: init, analyze: analyze };
})();
if (typeof module !== "undefined" && module.exports) module.exports = AstraRoute;
else if (typeof globalThis !== "undefined") globalThis.AstraRoute = AstraRoute;
