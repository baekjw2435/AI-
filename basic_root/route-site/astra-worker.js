// 적 국면 계산을 화면과 따로 돌리는 Worker. 아스트라의 계산 엔진은 한 국면에 몇 초가 걸릴 수 있어서,
// 페이지가 멈추지 않도록 여기서 AstraRoute.analyze를 부릅니다. 메시지: { id, entry, history, budget } → { id, res | error }
importScripts("site-engine.js", "astra-adapter.js");
var ready = null;
function get(p, type) {
  return fetch(p).then(function (r) {
    if (!r.ok) throw new Error(p + "를 불러오지 못했어요 (" + r.status + ").");
    return type === "json" ? r.json() : type === "b64" ? r.text() : r.arrayBuffer();
  });
}
function unbase64(text) {
  var s = atob(text.replace(/\s+/g, "")), u = new Uint8Array(s.length);
  for (var i = 0; i < s.length; i++) u[i] = s.charCodeAt(i);
  return u.buffer;
}
function init() {
  return Promise.all([get("model.json", "json"), get("astra/game-data.json", "json"), get("astra/proof-817.txt", "b64"), get("astra/engine.wasm")]).then(function (r) {
    var model = r[0];
    RouteSite.init(model, { format: "route-site-1", dictionary_sha256: model.dictionary_sha256, books: [] }, null);
    return AstraRoute.init(r[1], unbase64(r[2]), new Uint8Array(r[3]), model);
  });
}
onmessage = function (ev) {
  var m = ev.data;
  if (!ready) ready = init().catch(function (e) { ready = null; throw e; });
  ready.then(function () { return AstraRoute.analyze(m.entry, m.history, m.budget); }).then(
    function (res) { postMessage({ id: m.id, res: res }); },
    function (err) { postMessage({ id: m.id, error: String((err && err.message) || err) }); });
};
