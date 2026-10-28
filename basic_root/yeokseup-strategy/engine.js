// 역습 필승 엔진: verify_v2.py와 같은 정준화(왕복 쌍 제거, 자기 연결 짝수 제거,
// 도달 불가 제거, 정적 역산, 미확정 핵심 추출)를 하고, 증명에서 뽑은 승리수 표를 찾는다.
var YeokEngine = (function () {
  var M, keys, groups, N, vertexCount, groupCount, ownerOf;

  function init(model, buffer) {
    M = model;
    vertexCount = M.syllables.length;
    groupCount = M.edges.length;
    var head = new DataView(buffer, 0, 8);
    if (String.fromCharCode(head.getUint8(0), head.getUint8(1), head.getUint8(2), head.getUint8(3)) !== "YSK1") throw new Error("승리수 표 형식이 맞지 않아요.");
    N = head.getUint32(4, true);
    keys = new Uint32Array(buffer.slice(8, 8 + 8 * N));
    groups = new Uint16Array(buffer.slice(8 + 8 * N, 8 + 10 * N));
    ownerOf = {};
    M.words.forEach(function (list, g) { list.forEach(function (w) { ownerOf[w] = g; }); });
  }

  function position(history) {
    var cur = M.start, counts = M.full.slice(), used = {};
    for (var i = 0; i < history.length; i++) {
      var w = history[i], g = ownerOf[w];
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

  function lookup(cur, core) {
    var a = fnv(cur, core, false, 2166136261), b = fnv(cur, core, true, 0x9747b28c), lo = 0, hi = N;
    while (lo < hi) {
      var mid = (lo + hi) >>> 1, x = keys[2 * mid], y = keys[2 * mid + 1];
      if (x < a || (x === a && y < b)) lo = mid + 1; else hi = mid;
    }
    return lo < N && keys[2 * lo] === a && keys[2 * lo + 1] === b ? groups[lo] : -1;
  }

  function freeWord(g, used) {
    var list = M.words[g];
    for (var i = 0; i < list.length; i++) if (!used[list[i]]) return list[i];
    return null;
  }

  function alternatives(g, used, chosen) {
    return M.words[g].filter(function (w) { return !used[w] && w !== chosen; });
  }

  // 현재 차례(나)의 필승 수. how: "증명" | "정적" | "되받기"
  function ourMove(history) {
    var p = position(history), n = normalize(p.cur, p.counts), g, w, out = M.outgoing[p.cur], i;
    if (n.st === 1) {
      for (i = 0; i < out.length; i++) {
        g = out[i];
        if (n.paired[g] && M.edges[g][1] !== p.cur && n.labels[M.edges[g][1]] === 0 && (w = freeWord(g, p.used))) return { word: w, group: g, how: "정적", alts: alternatives(g, p.used, w) };
      }
      for (i = 0; i < out.length; i++) {
        g = out[i];
        if (n.paired[g] && M.edges[g][1] === p.cur && (w = freeWord(g, p.used))) return { word: w, group: g, how: "정적", alts: alternatives(g, p.used, w) };
      }
      return null;
    }
    if (n.st === 0) return null;
    g = lookup(p.cur, n.core);
    if (g >= 0 && M.edges[g][0] === p.cur && (w = freeWord(g, p.used))) return { word: w, group: g, how: "증명", alts: alternatives(g, p.used, w) };
    if (history.length) {
      var last = ownerOf[history[history.length - 1]], r = M.rev[last];
      if (r >= 0 && M.edges[r][0] === p.cur && (w = freeWord(r, p.used))) return { word: w, group: r, how: "되받기", alts: alternatives(r, p.used, w) };
    }
    return null;
  }

  function legalWords(history) {
    var p = position(history), list = [], out = M.outgoing[p.cur];
    for (var i = 0; i < out.length; i++) M.words[out[i]].forEach(function (w) { if (!p.used[w]) list.push(w); });
    return list.sort();
  }

  function syllableOf(history) { return M.syllables[position(history).cur]; }

  return { init: init, ourMove: ourMove, legalWords: legalWords, syllableOf: syllableOf, normalize: normalize, position: position, lookup: lookup, size: function () { return N; } };
})();
if (typeof module !== "undefined") module.exports = YeokEngine;
