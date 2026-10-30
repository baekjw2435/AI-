// RouteSite: 기초사전 루트 817단어 수순 탐색 엔진 (route-site-1).
//
// 검증된 증명(수정하지 않은 verify_v2.py 통과)에서 뽑은 승리수 표로, 한 국면의 모든 후보 단어에 승패를 붙입니다.
// 표는 묶음(진입 음절 또는 역·격·칭존 같은 계열)마다 따로 있고, 묶음 안에서는 정준 핵심 크기(남은 단어 수)
// 구간별 파일로 나뉩니다. 한 줄기를 따라 내려갈 때는 보통 파일 하나만 더 받으면 됩니다.
//
// 국면 열쇠: verify_v2.py와 같은 정준화(왕복 쌍 제거, 자기 연결 짝수 제거, 도달 불가 제거, 정적 역산,
// 미확정 핵심 추출) 뒤 [현재 음절 번호 하위 바이트, 상위 바이트, 묶음별 남은 개수...]에 대한 FNV-1a 32비트를
// 앞에서(기저 2166136261) a, 뒤에서(기저 0x9747b28c) b로 계산하고, 48비트 a·2^16 + (b >>> 16)을 씁니다.
//
// 판정 근거(how):
//   증명    표에 있는 승리수(검증된 증명의 수) 또는 그 수로 이기는 상대
//   정적    남은 단어의 연결만으로 승패가 정해진 자리
//   한 수   상대를 정적으로 지는 자리로 보내는 수가 있음(표에서 뺀 증명 국면)
//   되받기  왕복 쌍(또는 자기 연결 단어)의 한쪽을 내면 짝으로 받아, 둘 차례인 쪽이 지는 직전 국면으로 돌림
var RouteSite = (function () {
  var M, V, G, ownerOf, vertexOf, books, cache, loadFile, pending, lostRoots;

  function init(model, manifest, loader) {
    if (!model || model.format !== "route-site-1") throw new Error("model.json 형식이 맞지 않아요.");
    if (!manifest || manifest.format !== "route-site-1" || manifest.dictionary_sha256 !== model.dictionary_sha256)
      throw new Error("승리수 표와 단어 목록이 맞지 않아요.");
    M = model; V = M.syllables.length; G = M.edges.length;
    ownerOf = Object.create(null); vertexOf = Object.create(null);
    M.words.forEach(function (list, g) { list.forEach(function (w) { ownerOf[w] = g; }); });
    M.syllables.forEach(function (s, v) { vertexOf[s] = v; });
    books = Object.create(null); lostRoots = Object.create(null);
    manifest.books.forEach(function (b) { books[b.id] = b; });
    cache = new Map(); pending = new Map(); loadFile = loader; memo.clear();
    // 둘 차례인 쪽이 지는 증명의 루트(예: 격 → 격식). 표에는 이기는 국면만 있으므로 따로 기억합니다.
    manifest.books.forEach(function (b) {
      var keys = new Set();
      b.proofs.forEach(function (q) {
        if (q.result_for_player_to_move !== "L") return;
        var p = position(q.start, q.history), n = normalize(p.cur, p.counts);
        if (n.st === -1) keys.add(p.cur + ":" + key48(p.cur, n.core));
      });
      lostRoots[b.id] = keys;
    });
  }

  // verify.py의 dueum과 같은 규칙: ㄹ+ㅑㅕㅖㅛㅠㅣ → ㅇ, ㄹ+그 밖의 모음 → ㄴ, ㄴ+ㅕㅛㅠㅣ → ㅇ
  function dueum(s) {
    var off = typeof s === "string" && s.length === 1 ? s.charCodeAt(0) - 0xac00 : -1;
    if (off < 0 || off >= 11172) return s;
    var ini = Math.floor(off / 588), rest = off % 588, vowel = Math.floor(rest / 28);
    if (ini === 5) ini = [2, 6, 7, 12, 17, 20].indexOf(vowel) >= 0 ? 11 : 2;
    else if (ini === 2 && [6, 12, 17, 20].indexOf(vowel) >= 0) ini = 11;
    return String.fromCharCode(0xac00 + ini * 588 + rest);
  }

  function position(start, history) {
    var cur = vertexOf[dueum(start)], counts = M.full.slice(), used = Object.create(null), i, w, g;
    if (cur === undefined) throw new Error("단어 목록에 없는 음절이에요: " + start);
    for (i = 0; i < history.length; i++) {
      w = history[i]; g = ownerOf[w];
      if (g === undefined || used[w] || M.edges[g][0] !== cur || counts[g] <= 0) throw new Error("쓸 수 없는 단어예요: " + w);
      counts[g]--; used[w] = true; cur = M.edges[g][1];
    }
    return { cur: cur, counts: counts, used: used };
  }

  function reduce(cur, counts) {
    var r = counts.slice(), i;
    for (i = 0; i < M.pairs.length; i++) {
      var a = M.pairs[i][0], b = M.pairs[i][1], t = Math.min(r[a], r[b]);
      r[a] -= t; r[b] -= t;
    }
    for (i = 0; i < M.loops.length; i++) r[M.loops[i]] %= 2;
    var reach = new Uint8Array(V), queue = [cur];
    reach[cur] = 1;
    for (var q = 0; q < queue.length; q++) {
      var out = M.outgoing[queue[q]];
      for (i = 0; i < out.length; i++) {
        var g = out[i];
        if (r[g]) { var t2 = M.edges[g][1]; if (!reach[t2]) { reach[t2] = 1; queue.push(t2); } }
      }
    }
    for (var s = 0; s < V; s++) if (!reach[s]) { var o = M.outgoing[s]; for (i = 0; i < o.length; i++) r[o[i]] = 0; }
    return r;
  }

  function staticLabels(paired) {
    var labels = new Int8Array(V).fill(-1), succ = [], loop = new Uint8Array(V), s, g;
    for (s = 0; s < V; s++) succ.push([]);
    for (g = 0; g < G; g++) if (paired[g]) {
      var e = M.edges[g];
      if (e[0] === e[1]) loop[e[0]] = 1; else succ[e[0]].push(e[1]);
    }
    var pendingV = [];
    for (s = 0; s < V; s++) pendingV.push(s);
    while (pendingV.length) {
      var remaining = [], changed = false;
      for (var i = 0; i < pendingV.length; i++) {
        var src = pendingV[i], allWin = true, hasLose = false, list = succ[src];
        for (var j = 0; j < list.length; j++) {
          var l = labels[list[j]];
          if (l === 0) { hasLose = true; break; }
          if (l !== 1) allWin = false;
        }
        if (hasLose) { labels[src] = 1; changed = true; }
        else if (allWin) { labels[src] = loop[src]; changed = true; }
        else remaining.push(src);
      }
      if (!changed) break;
      pendingV = remaining;
    }
    return labels;
  }

  // st: -1 미확정, 0 둘 차례인 쪽이 정적으로 짐, 1 정적으로 이김
  function normalize(cur, counts) {
    var paired = reduce(cur, counts), labels = staticLabels(paired);
    if (labels[cur] !== -1) return { core: paired, st: labels[cur], paired: paired, labels: labels };
    var seen = new Uint8Array(V), queue = [cur], i, g;
    seen[cur] = 1;
    for (var q = 0; q < queue.length; q++) {
      var out = M.outgoing[queue[q]];
      for (i = 0; i < out.length; i++) {
        g = out[i];
        if (paired[g]) { var t = M.edges[g][1]; if (labels[t] === -1 && !seen[t]) { seen[t] = 1; queue.push(t); } }
      }
    }
    var core = new Array(G).fill(0);
    for (var s = 0; s < V; s++) if (seen[s]) {
      var o = M.outgoing[s];
      for (i = 0; i < o.length; i++) { g = o[i]; if (paired[g] && labels[M.edges[g][1]] === -1) core[g] = paired[g]; }
    }
    return { core: core, st: -1, paired: paired, labels: labels };
  }

  function fnv(cur, core, reverse, basis) {
    var bytes = [cur & 255, cur >> 8].concat(core), h = basis >>> 0, n = bytes.length;
    for (var i = 0; i < n; i++) {
      h ^= bytes[reverse ? n - 1 - i : i];
      h = Math.imul(h, 16777619) >>> 0;
    }
    return h >>> 0;
  }

  function key48(cur, core) { return fnv(cur, core, false, 2166136261) * 65536 + (fnv(cur, core, true, 0x9747b28c) >>> 16); }
  function coreSize(core) { var s = 0; for (var i = 0; i < core.length; i++) s += core[i]; return s; }

  // RSB1: 'RSB1', u32 n, u8 k, 3바이트 0, u32 열쇠 바이트 수, u32 0, 열쇠 비트열(첫 48비트 그대로, 이후 간격을 Rice 부호),
  // 수 비트열(10비트씩). 비트는 바이트 안에서 높은 자리부터.
  function decode(buffer) {
    var u8 = new Uint8Array(buffer), dv = new DataView(buffer);
    if (u8.length < 20 || u8[0] !== 82 || u8[1] !== 83 || u8[2] !== 66 || u8[3] !== 49) throw new Error("승리수 표 형식이 맞지 않아요.");
    var n = dv.getUint32(4, true), k = u8[8], kbytes = dv.getUint32(12, true);
    if (u8.length !== 20 + kbytes + Math.ceil(10 * n / 8)) throw new Error("승리수 표 크기가 맞지 않아요.");
    var keys = new Float64Array(n), groups = new Uint16Array(n), pos = 160, end = (20 + kbytes) * 8;
    function bits(cnt) {
      var v = 0;
      for (var i = 0; i < cnt; i++) { v = v * 2 + ((u8[pos >>> 3] >>> (7 - (pos & 7))) & 1); pos++; }
      return v;
    }
    if (n) {
      keys[0] = bits(24) * 16777216 + bits(24);
      var scale = Math.pow(2, k), hiBits = k > 24 ? k - 24 : 0, loBits = k - hiBits;
      for (var i = 1; i < n; i++) {
        var q = 0;
        while ((u8[pos >>> 3] >>> (7 - (pos & 7))) & 1) { q++; pos++; }
        pos++;
        var r = hiBits ? bits(hiBits) * 16777216 + bits(loBits) : bits(loBits);
        keys[i] = keys[i - 1] + q * scale + r;
      }
      if (pos > end) throw new Error("승리수 표가 손상됐어요.");
      pos = end;
      for (i = 0; i < n; i++) groups[i] = bits(10);
    }
    return { n: n, keys: keys, groups: groups };
  }

  function fileFor(book, size) {
    var f = book.files;
    for (var i = 0; i < f.length; i++) if (size >= f[i].core_lo && size <= f[i].core_hi) return f[i];
    return null;
  }

  function getFile(f) {
    if (cache.has(f.path)) return Promise.resolve(cache.get(f.path));
    if (!pending.has(f.path)) {
      pending.set(f.path, Promise.resolve().then(function () { return loadFile(f.path); }).then(function (buf) {
        if (buf.byteLength !== f.bytes) throw new Error("승리수 표 " + f.path + "의 크기가 맞지 않아요.");
        var T = decode(buf);
        if (T.n !== f.n) throw new Error("승리수 표 " + f.path + "의 항목 수가 맞지 않아요.");
        cache.set(f.path, T); pending.delete(f.path);
        return T;
      }, function (e) { pending.delete(f.path); throw e; }));
    }
    return pending.get(f.path);
  }

  // 그 국면에서 둘 차례인 쪽의 승리수 묶음 번호(표에 없으면 -1)
  function lookup(bookId, cur, core) {
    var book = books[bookId], f = book && fileFor(book, coreSize(core));
    if (!f) return Promise.resolve(-1);
    var key = key48(cur, core);
    return getFile(f).then(function (T) {
      var lo = 0, hi = T.n;
      while (lo < hi) { var mid = (lo + hi) >>> 1; if (T.keys[mid] < key) lo = mid + 1; else hi = mid; }
      var g = lo < T.n && T.keys[lo] === key ? T.groups[lo] : -1;
      return g >= 0 && M.edges[g][0] === cur && core[g] > 0 ? g : -1;
    });
  }

  function freeWords(g, used) { return M.words[g].filter(function (w) { return !used[w]; }); }

  // 정적으로 이기는 자리의 수(engine.js와 같은 선택): 정적으로 지는 음절로 보내는 수, 없으면 자기 연결 단어
  function staticMove(cur, counts, n) {
    var out = M.outgoing[cur], i, g;
    for (i = 0; i < out.length; i++) { g = out[i]; if (n.paired[g] && M.edges[g][1] !== cur && n.labels[M.edges[g][1]] === 0 && counts[g]) return g; }
    for (i = 0; i < out.length; i++) { g = out[i]; if (n.paired[g] && M.edges[g][1] === cur && counts[g]) return g; }
    return -1;
  }

  // 상대를 정적으로 지는 자리로 보내는 수
  function oneMoveWin(cur, counts) {
    var out = M.outgoing[cur];
    for (var i = 0; i < out.length; i++) {
      var g = out[i];
      if (!counts[g]) continue;
      var c = counts.slice(); c[g]--;
      if (normalize(M.edges[g][1], c).st === 0) return g;
    }
    return -1;
  }

  // 둘 차례인 쪽이 이기는지: { win: true|null, group, how }
  function winner(bookId, cur, counts, n) {
    if (n.st === 1) return Promise.resolve({ win: true, group: staticMove(cur, counts, n), how: "정적" });
    if (n.st === 0) return Promise.resolve({ win: false, group: -1, how: "정적" });
    var one = oneMoveWin(cur, counts);
    if (one >= 0) return Promise.resolve({ win: true, group: one, how: "한 수" });
    return lookup(bookId, cur, n.core).then(function (g) {
      if (g >= 0 && counts[g]) return { win: true, group: g, how: "증명" };
      if (lostRoots[bookId] && lostRoots[bookId].has(cur + ":" + key48(cur, n.core))) return { win: false, group: -1, how: "증명" };
      return { win: null, group: -1, how: "" };
    });
  }

  // 그 국면에서 둘 차례인 쪽이 지는 것이 한 수 앞까지로 증명되는가: 지워지지 않은 모든 수에 상대의 이기는 수가 있음
  function provenLoss(bookId, cur, counts, n) {
    if (n.st === 0) return Promise.resolve(true);
    if (n.st === 1) return Promise.resolve(false);
    var live = M.outgoing[cur].filter(function (g) { return counts[g] > 0 && n.paired[g] > 0; });
    if (!live.length) return Promise.resolve(false);
    return Promise.all(live.map(function (g) {
      var c = counts.slice(); c[g]--;
      var v = M.edges[g][1];
      return winner(bookId, v, c, normalize(v, c)).then(function (w) { return w.win === true; });
    })).then(function (all) { return all.every(Boolean); });
  }

  var memo = new Map();

  // 한 국면 분석. entry: { start, prefix, book }. history: 받는 쪽의 첫 수부터 낸 단어들.
  // 반환 { syllable, toMove: "receiver"|"presenter", status: "W"|"L"|"?", how, best, moves: [...], end }
  // moves[i] = { group, words, status: "win"|"lose"|"?", how, reply: { group, word, how } | null }
  function analyze(entry, history) {
    var full = entry.prefix.concat(history), key = entry.book + "|" + entry.start + "|" + entry.prefix.join(",") + "|" + history.join(",");
    if (memo.has(key)) return memo.get(key);
    var job = (history.length ? analyze(entry, history.slice(0, -1)) : Promise.resolve(null)).then(function (prev) {
      return analyzeAt(entry, full, history, prev);
    });
    memo.set(key, job);
    job.catch(function () { memo.delete(key); });
    return job;
  }

  function analyzeAt(entry, full, history, prev) {
    var p = position(entry.start, full), n = normalize(p.cur, p.counts), out = M.outgoing[p.cur];
    var res = { syllable: M.syllables[p.cur], toMove: history.length % 2 ? "presenter" : "receiver", status: "?", how: "", best: null, moves: [], end: false };
    var legal = out.filter(function (g) { return p.counts[g] > 0; });
    res.end = !legal.length;
    if (res.end) { res.status = "L"; res.how = "낼 단어 없음"; return Promise.resolve(res); }
    var last = full.length ? ownerOf[full[full.length - 1]] : -1;
    return Promise.all([winner(entry.book, p.cur, p.counts, n)].concat(legal.map(function (g) {
      var c = p.counts.slice(); c[g]--;
      var v = M.edges[g][1], cn = normalize(v, c);
      return winner(entry.book, v, c, cn).then(function (w) { return { g: g, c: c, v: v, w: w }; });
    }))).then(function (all) {
      var root = all[0], kids = all.slice(1);
      res.moves = kids.map(function (k) {
        var words = freeWords(k.g, p.used), mv = { group: k.g, words: words, status: "?", how: "", reply: null, _k: k };
        if (k.w.win === false) { mv.status = "win"; mv.how = k.w.how; }
        else if (k.w.win === true) {
          mv.status = "lose"; mv.how = k.w.how;
          var used2 = Object.assign(Object.create(null), p.used); used2[words[0]] = true;
          if (k.w.group >= 0) mv.reply = { group: k.w.group, word: freeWords(k.w.group, used2)[0], how: k.w.how };
        }
        return mv;
      });
      var byGroup = {}; res.moves.forEach(function (mv) { byGroup[mv.group] = mv; });
      if (root.win === true) {
        res.status = "W"; res.how = root.how; res.best = byGroup[root.group] || null;
        if (res.best && res.best.status === "?") { res.best.status = "win"; res.best.how = root.how; }
      } else if (root.win === false) {
        res.status = "L"; res.how = root.how;
      }
      // 되받기: 직전 국면에서 상대가 졌는데 상대가 왕복 쌍(또는 자기 연결 단어)의 한쪽을 냈으면, 짝이 이기는 수
      if (res.status === "?" && prev && prev.status === "L" && last >= 0) {
        var partner = M.edges[last][0] === M.edges[last][1] ? last : M.rev[last];
        if (partner >= 0 && byGroup[partner]) {
          res.status = "W"; res.how = "되받기"; res.best = byGroup[partner];
          if (res.best.status === "?") { res.best.status = "win"; res.best.how = "되받기"; }
        }
      }
      if (res.status === "?") {
        var win = res.moves.filter(function (mv) { return mv.status === "win"; })[0];
        if (win) { res.status = "W"; res.how = win.how; res.best = win; }
      }
      if (res.status === "?") {
        // 정준 국면에 남은 수(왕복 쌍·자기 연결 짝수로 지워지지 않은 수)가 모두 지면 짐
        var live = res.moves.filter(function (mv) { return n.paired[mv.group] > 0; });
        if (live.every(function (mv) { return mv.status === "lose"; })) { res.status = "L"; res.how = live.length ? "모든 수가 짐" : "정적"; }
      }
      if (res.status === "L") {
        // 지워진 수와 남은 미확인 수: 상대가 짝으로 받아 이 국면으로 돌아오면 다시 둘 차례인 쪽이 진다
        res.moves.forEach(function (mv) {
          if (mv.status !== "?") return;
          var g = mv.group, partner = M.edges[g][0] === M.edges[g][1] ? g : M.rev[g];
          var used2 = Object.assign(Object.create(null), p.used); used2[mv.words[0]] = true;
          var c = p.counts.slice(); c[g]--;
          var pw = partner >= 0 && c[partner] > 0 ? freeWords(partner, used2) : [];
          if (pw.length) { mv.status = "lose"; mv.how = "되받기"; mv.reply = { group: partner, word: pw[0], how: "되받기" }; }
        });
      }
      // 이기는 쪽의 나머지 수: 상대의 모든 응수에 이기는 수가 있으면(한 수 앞까지 증명) 이 수도 이김
      var open = res.status === "L" ? [] : res.moves.filter(function (mv) { return mv.status === "?"; });
      return Promise.all(open.map(function (mv) {
        var k = mv._k;
        return provenLoss(entry.book, k.v, k.c, normalize(k.v, k.c)).then(function (lost) {
          if (lost) { mv.status = "win"; mv.how = "증명"; }
        });
      })).then(function () {
        if (res.status === "?") {
          var win = res.moves.filter(function (mv) { return mv.status === "win"; })[0];
          if (win) { res.status = "W"; res.how = win.how; res.best = win; }
        }
        res.moves.forEach(function (mv) { delete mv._k; });
        res.moves.sort(function (a, b) { return a.words[0] < b.words[0] ? -1 : a.words[0] > b.words[0] ? 1 : 0; });
        return res;
      });
    });
  }

  function clear() { memo.clear(); }
  function groupOf(word) { return ownerOf[word]; }
  function syllableOf(start, history) { return M.syllables[position(start, history).cur]; }

  return {
    init: init, analyze: analyze, clear: clear, position: position, normalize: normalize, key48: key48, coreSize: coreSize,
    decode: decode, lookup: lookup, groupOf: groupOf, syllableOf: syllableOf, dueum: dueum
  };
})();
if (typeof module !== "undefined" && module.exports) module.exports = RouteSite;
else if (typeof globalThis !== "undefined") globalThis.RouteSite = RouteSite;
