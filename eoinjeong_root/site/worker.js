/* 어인정 수순 지도: 계산 작업자(Web Worker). eoin_solver.wasm(solver/eoin_solver.c)으로 수를 하나씩 계산합니다.
 * 받는 메시지
 *   {type:"init", model}                        model = data.json의 model(ModelV3: 꼭짓점 수, 묶음 [출발, 도착, 단어 수])
 *   {type:"moves", id, start, history, groups}  start = 받은 음절의 꼭짓점, history = 쓴 단어들의 묶음 번호,
 *                                               groups = 값을 알고 싶은 묶음(그 수를 둔 뒤 상대 차례의 값)
 * 보내는 메시지
 *   {type:"ready"} | {type:"move", id, group, value(1 = 그때 둘 차례인 쪽 승, 0 = 패)} | {type:"done", id} | {type:"error", message}
 * 새 "moves"가 오면 하던 계산을 멈추고 새 것을 합니다. 치환표는 계속 남아 다음 계산을 빠르게 합니다. */
"use strict";
var api = null, model = null, current = 0, STEP = 30000;

function fail(e) { self.postMessage({ type: "error", message: String(e && e.message || e) }); }

function init(m) {
  model = m;
  return fetch("eoin_solver.wasm").then(function (r) {
    if (!r.ok) throw new Error("eoin_solver.wasm을 불러오지 못했어요 (" + r.status + ").");
    return r.arrayBuffer();
  }).then(function (buf) { return WebAssembly.instantiate(buf, {}); }).then(function (res) {
    api = res.instance.exports;
    m.groups.forEach(function (g, i) { api.set_group(i, g[0], g[1], g[2]); });
    var rc = api.init(m.vertices, m.groups.length);
    if (rc !== 0) throw new Error("계산기 준비 실패 (" + rc + ")");
    self.postMessage({ type: "ready" });
  });
}

function run(msg) {
  var id = msg.id, cnt = model.groups.map(function (g) { return g[2]; }), cur = msg.start;
  msg.history.forEach(function (g) { cnt[g]--; cur = model.groups[g][1]; });
  var list = msg.groups.slice(), k = 0;
  function load() {
    for (var g = 0; g < cnt.length; g++) api.set_count(g, cnt[g]);
    api.set_cur(cur);
  }
  function step() {
    if (id !== current) return;
    load();
    var t0 = Date.now();
    while (k < list.length && Date.now() - t0 < 60) {
      var v = api.child_value(list[k], STEP);
      if (v === -1) continue;
      self.postMessage({ type: "move", id: id, group: list[k], value: v });
      k++;
    }
    if (k < list.length) setTimeout(step, 0);
    else self.postMessage({ type: "done", id: id });
  }
  step();
}

self.onmessage = function (ev) {
  var m = ev.data;
  try {
    if (m.type === "init") init(m.model).catch(fail);
    else if (m.type === "moves") { current = m.id; if (api) run(m); }
  } catch (e) { fail(e); }
};
