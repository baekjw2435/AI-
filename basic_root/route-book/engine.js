// RouteBook: 기초사전 루트 817단어 필승 수순 엔진 (route-book-1).
//
// 검증된 증명 13개(역 4개, 격 9개)에서 뽑은 승리수를 한 표로 합쳐 씁니다. 표는 국면 열쇠로 찾고,
// 열쇠의 첫 바이트로 256조각(tables/bXX.bin)으로 나뉘어 있습니다. 한 수를 고를 때 조각 하나만 필요합니다.
//
// 국면 열쇠: verify_v2.py와 같은 정준화(왕복 쌍 제거, 자기 연결 짝수 제거, 도달 불가 제거, 정적 역산,
// 미확정 핵심 추출)를 한 뒤, [현재 음절 번호 하위 바이트, 상위 바이트, 묶음별 남은 개수...]에 대한
// FNV-1a 32비트를 앞에서(기저 2166136261)와 뒤에서(기저 0x9747b28c) 각각 계산한 두 값.
var RouteBook = (function () {
  var M, vertexCount, groupCount, ownerOf, vertexOf, buckets, catalog, lostRoots;

  function init(model, cat) {
    if (!model || model.format !== "route-book-1") throw new Error("model.json 형식이 맞지 않아요.");
    M = model;
    vertexCount = M.syllables.length;
    groupCount = M.edges.length;
    ownerOf = Object.create(null);
    vertexOf = Object.create(null);
    M.words.forEach(function (list, g) { list.forEach(function (w) { ownerOf[w] = g; }); });
    M.syllables.forEach(function (s, v) { vertexOf[s] = v; });
    buckets = new Array(M.buckets);
    catalog = cat || null;
    // 증명의 루트 중 둘 차례인 쪽이 지는 국면(예: 격 → 격식). 되받기가 안전한지 판단할 때 씁니다.
    lostRoots = (M.roots || []).filter(function (r) { return r.result_for_player_to_move === "L"; });
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

  function bucketFile(id) { return "tables/b" + (id < 16 ? "0" : "") + id.toString(16) + ".bin"; }

  function addBucket(id, buffer) {
    if (!(id >= 0 && id < M.buckets && id === Math.floor(id))) throw new Error("승리수 표 조각 번호가 맞지 않아요: " + id);
    if (ArrayBuffer.isView(buffer)) buffer = buffer.buffer.slice(buffer.byteOffset, buffer.byteOffset + buffer.byteLength);
    if (!(buffer instanceof ArrayBuffer) || buffer.byteLength < 8) throw new Error("승리수 표 형식이 맞지 않아요.");
    var head = new DataView(buffer, 0, 8);
    if (String.fromCharCode(head.getUint8(0), head.getUint8(1), head.getUint8(2), head.getUint8(3)) !== "YSK1") throw new Error("승리수 표 형식이 맞지 않아요.");
    var n = head.getUint32(4, true);
    if (buffer.byteLength !== 8 + 10 * n) throw new Error("승리수 표 조각 " + id + "의 크기가 맞지 않아요.");
    var T = { n: n, keys: new Uint32Array(buffer.slice(8, 8 + 8 * n)), groups: new Uint16Array(buffer.slice(8 + 8 * n, 8 + 10 * n)) };
    if (n && ((T.keys[0] >>> 24) !== id || (T.keys[2 * (n - 1)] >>> 24) !== id)) throw new Error("승리수 표 조각 " + id + "이 아닌 파일이에요.");
    buckets[id] = T;
  }

  function hasBucket(id) { return !!buckets[id]; }

  // start: 시작 음절(예: "격"). history: 그 음절부터 실제로 낸 단어들. initialUsed: 그 전에 이미 쓴 단어들(선택).
  function position(start, history, initialUsed) {
    if (!M) throw new Error("먼저 RouteBook.init(model, catalog)를 불러 주세요.");
    var cur = vertexOf[dueum(start)], counts = M.full.slice(), used = Object.create(null), i, w, g;
    if (cur === undefined) throw new Error("사전에 없는 음절이에요: " + start);
    if (!Array.isArray(history)) throw new Error("history는 단어 배열이어야 해요.");
    initialUsed = initialUsed || [];
    if (!Array.isArray(initialUsed)) throw new Error("initialUsed는 단어 배열이어야 해요.");
    for (i = 0; i < initialUsed.length; i++) {
      w = initialUsed[i]; g = ownerOf[w];
      if (g === undefined || used[w]) throw new Error("쓸 수 없는 단어예요: " + w);
      counts[g]--; used[w] = true;
    }
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
    var reach = new Uint8Array(vertexCount), queue = [cur];
    reach[cur] = 1;
    for (var q = 0; q < queue.length; q++) {
      var out = M.outgoing[queue[q]];
      for (i = 0; i < out.length; i++) {
        var g = out[i];
        if (r[g]) { var t2 = M.edges[g][1]; if (!reach[t2]) { reach[t2] = 1; queue.push(t2); } }
      }
    }
    for (var s = 0; s < vertexCount; s++) if (!reach[s]) { var o = M.outgoing[s]; for (i = 0; i < o.length; i++) r[o[i]] = 0; }
    return r;
  }

  function staticLabels(paired) {
    var labels = new Int8Array(vertexCount).fill(-1), succ = [], loop = new Uint8Array(vertexCount), s, g;
    for (s = 0; s < vertexCount; s++) succ.push([]);
    for (g = 0; g < groupCount; g++) if (paired[g]) {
      var e = M.edges[g];
      if (e[0] === e[1]) loop[e[0]] = 1; else succ[e[0]].push(e[1]);
    }
    var pending = [];
    for (s = 0; s < vertexCount; s++) pending.push(s);
    while (pending.length) {
      var remaining = [], changed = false;
      for (var i = 0; i < pending.length; i++) {
        var src = pending[i], allWin = true, hasLose = false, list = succ[src];
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
      pending = remaining;
    }
    return labels;
  }

  // st: -1 미확정, 0 둘 차례인 쪽이 정적으로 짐, 1 정적으로 이김
  function normalize(cur, counts) {
    var paired = reduce(cur, counts), labels = staticLabels(paired);
    if (labels[cur] !== -1) return { core: paired, st: labels[cur], paired: paired, labels: labels };
    var seen = new Uint8Array(vertexCount), queue = [cur], i, g;
    seen[cur] = 1;
    for (var q = 0; q < queue.length; q++) {
      var out = M.outgoing[queue[q]];
      for (i = 0; i < out.length; i++) {
        g = out[i];
        if (paired[g]) { var t = M.edges[g][1]; if (labels[t] === -1 && !seen[t]) { seen[t] = 1; queue.push(t); } }
      }
    }
    var core = new Array(groupCount).fill(0);
    for (var s = 0; s < vertexCount; s++) if (seen[s]) {
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

  function keyOf(cur, core) { return [fnv(cur, core, false, 2166136261), fnv(cur, core, true, 0x9747b28c)]; }

  function find(T, a, b) {
    var lo = 0, hi = T.n;
    while (lo < hi) {
      var mid = (lo + hi) >>> 1, x = T.keys[2 * mid], y = T.keys[2 * mid + 1];
      if (x < a || (x === a && y < b)) lo = mid + 1; else hi = mid;
    }
    return lo < T.n && T.keys[2 * lo] === a && T.keys[2 * lo + 1] === b ? T.groups[lo] : -1;
  }

  function freeWord(g, used) {
    var list = M.words[g];
    for (var i = 0; i < list.length; i++) if (!used[list[i]]) return list[i];
    return null;
  }

  function move(g, w, how, used) {
    return { word: w, group: g, how: how, alts: M.words[g].filter(function (x) { return !used[x] && x !== w; }) };
  }

  // 지금 둘 차례인 쪽의 필승 수. 반환: { word, group, how: "증명"|"정적"|"되받기", alts } 또는 null(표에 없음).
  // 필요한 표 조각이 아직 없으면 err.needBucket(조각 번호)를 단 오류를 던집니다. ourMoveAsync를 쓰면 알아서 불러옵니다.
  function ourMove(start, history, initialUsed) {
    var p = position(start, history, initialUsed), n = normalize(p.cur, p.counts), out = M.outgoing[p.cur], g, w, i;
    if (n.st === 1) {
      for (i = 0; i < out.length; i++) {
        g = out[i];
        if (n.paired[g] && M.edges[g][1] !== p.cur && n.labels[M.edges[g][1]] === 0 && (w = freeWord(g, p.used))) return move(g, w, "정적", p.used);
      }
      for (i = 0; i < out.length; i++) {
        g = out[i];
        if (n.paired[g] && M.edges[g][1] === p.cur && (w = freeWord(g, p.used))) return move(g, w, "정적", p.used);
      }
      return null;
    }
    if (n.st === 0) return null;
    // 상대를 계산 없이 지는 자리로 보내는 수(표에서 뺀 경우)
    for (i = 0; i < out.length; i++) {
      g = out[i];
      if (!n.core[g]) continue;
      var c = p.counts.slice(); c[g]--;
      if (normalize(M.edges[g][1], c).st === 0 && (w = freeWord(g, p.used))) return move(g, w, "증명", p.used);
    }
    var k = keyOf(p.cur, n.core), b = k[0] >>> 24;
    if (!buckets[b]) { var e = new Error("승리수 표 조각 " + bucketFile(b) + "이 필요해요."); e.needBucket = b; throw e; }
    g = find(buckets[b], k[0], k[1]);
    if (g >= 0 && M.edges[g][0] === p.cur && (w = freeWord(g, p.used))) return move(g, w, "증명", p.used);
    // 상대가 왕복 쌍의 한쪽을 냈으면 짝으로 되받아 그 수 직전 국면으로 돌아간다.
    // 그 직전 국면이 상대에게 증명된 패배일 때만 이기는 수이므로, 그것을 확인한 경우에만 둔다.
    if (history.length) {
      var r = M.rev[ownerOf[history[history.length - 1]]];
      if (r >= 0 && M.edges[r][0] === p.cur && (w = freeWord(r, p.used)) && lostFor(start, history.slice(0, -1), initialUsed)) return move(r, w, "되받기", p.used);
    }
    return null;
  }

  // h 국면에서 둘 차례인 쪽이 진다는 것이 증명돼 있는가
  function lostFor(start, h, initialUsed) {
    var p = position(start, h, initialUsed);
    if (normalize(p.cur, p.counts).st === 0) return true;
    // 둘 차례인 쪽이 지는 증명 루트(같은 묶음의 단어로 같은 국면에 온 경우 포함)
    if (!(initialUsed && initialUsed.length)) {
      for (var i = 0; i < lostRoots.length; i++) {
        var R = lostRoots[i];
        if (dueum(R.start) === dueum(start) && R.history.length === h.length &&
            R.history.every(function (w, k) { return ownerOf[w] === ownerOf[h[k]]; })) return true;
      }
    }
    // 바로 앞 수가 그 국면에서 증명된 승리수였다(그 수를 둔 쪽이 이긴다 = 지금 둘 차례인 쪽이 진다)
    if (h.length) {
      var prev = ourMove(start, h.slice(0, -1), initialUsed);
      if (prev && prev.group === ownerOf[h[h.length - 1]]) return true;
    }
    return false;
  }

  // loadBucket(id) -> Promise<ArrayBuffer>. 예: function (id) { return fetch(RouteBook.bucketFile(id)).then(r => r.arrayBuffer()); }
  // 필요한 조각을 모두 불러올 때까지 되풀이합니다(되받기 확인에 조각이 더 필요할 수 있음). 오류는 항상 거부된 Promise로 돌려줍니다.
  function ourMoveAsync(start, history, initialUsed, loadBucket) {
    function attempt() {
      try { return Promise.resolve(ourMove(start, history, initialUsed)); }
      catch (e) {
        if (e.needBucket === undefined) return Promise.reject(e);
        return Promise.resolve().then(function () { return loadBucket(e.needBucket); }).then(function (buf) {
          addBucket(e.needBucket, buf);
          return attempt();
        });
      }
    }
    return Promise.resolve().then(attempt);
  }

  function legalWords(start, history, initialUsed) {
    var p = position(start, history, initialUsed), list = [], out = M.outgoing[p.cur];
    for (var i = 0; i < out.length; i++) M.words[out[i]].forEach(function (w) { if (!p.used[w]) list.push(w); });
    return list.sort();
  }

  function syllableOf(start, history, initialUsed) { return M.syllables[position(start, history, initialUsed).cur]; }
  function groupOf(word) { return ownerOf[word]; }
  function firstMoves(start) { return catalog && catalog.starts[start] ? catalog.starts[start].first_moves : null; }

  return {
    init: init, addBucket: addBucket, hasBucket: hasBucket, bucketFile: bucketFile, ourMove: ourMove, ourMoveAsync: ourMoveAsync,
    legalWords: legalWords, syllableOf: syllableOf, groupOf: groupOf, firstMoves: firstMoves,
    position: position, normalize: normalize, keyOf: keyOf, dueum: dueum
  };
})();
if (typeof module !== "undefined" && module.exports) module.exports = RouteBook;
else if (typeof globalThis !== "undefined") globalThis.RouteBook = RouteBook;
