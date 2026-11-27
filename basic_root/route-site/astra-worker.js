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
// 표 파일은 데이터만 담은 WebAssembly 모듈(.wasm)의 사용자 정의 구역으로 올라가 있습니다(아티팩트가 일반 이진 파일을
// 받지 않음). 그 구역의 바이트를 꺼냅니다.
function unwasm(buf) {
  var u = new Uint8Array(buf), p = 9;
  if (u.length < 10 || u[0] !== 0 || u[1] !== 0x61 || u[2] !== 0x73 || u[3] !== 0x6d || u[8] !== 0) throw new Error("표 파일 형식이 맞지 않아요.");
  function leb() { var r = 0, s = 1, b; do { b = u[p++]; r += (b & 0x7f) * s; s *= 128; } while (b & 0x80); return r; }
  var size = leb(), end = p + size, nameLen = leb();
  p += nameLen;
  if (end !== u.length) throw new Error("표 파일 크기가 맞지 않아요.");
  return buf.slice(p, end);
}
function unbase64(text) {
  var s = atob(text.replace(/\s+/g, "")), u = new Uint8Array(s.length);
  for (var i = 0; i < s.length; i++) u[i] = s.charCodeAt(i);
  return u.buffer;
}
function init() {
  return Promise.all([get("model.json", "json"), get("astra/game-data.json", "json"), get("astra/proof-817.wasm"), get("astra/engine.wasm")]).then(function (r) {
    var model = r[0];
    RouteSite.init(model, { format: "route-site-1", dictionary_sha256: model.dictionary_sha256, books: [] }, null);
    return AstraRoute.init(r[1], unwasm(r[2]), new Uint8Array(r[3]), model);
  });
}
onmessage = function (ev) {
  var m = ev.data;
  if (!ready) ready = init().catch(function (e) { ready = null; throw e; });
  ready.then(function () { return AstraRoute.analyze(m.entry, m.history, m.budget); }).then(
    function (res) { postMessage({ id: m.id, res: res }); },
    function (err) { postMessage({ id: m.id, error: String((err && err.message) || err) }); });
};
