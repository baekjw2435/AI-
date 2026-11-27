// cert2site: winning-move records of one route-proof-v4 certificate, keyed the way the route site looks them up.
//
// usage: cert2site MODEL.txt CERT.v4.gz ROOT.txt OUT.bin
//   MODEL.txt  site_model.py's numeric model (site numbering) + the map from certificate (ModelV3) groups to site groups
//   ROOT.txt   "cur count0 count1 ..." of the certificate's root position, site numbering (site_model.SiteMap.root)
//   OUT.bin    records {u32 a, u32 b, u64 s, u16 g, u16 p}: a, b = the site engine's forward/backward FNV-1a of
//              [cur & 255, cur >> 8, canonical counts...], s = FNV-1a 64 of the same bytes (collision check),
//              g = the certificate's winning group (site numbering), p = canonical core size
// Prints {"cert_nodes", "visited", "records", "one_move", "static", "root_result"} as JSON.
//
// The walk is the verifier's: start from the root's canonical state, follow every move of the certificate, and
// compute each child's canonical state (pairs cancelled, self-loops mod 2, unreachable removed, static labels,
// undecided core) with the site engine's rules, which on the 817-word list are ModelV3's. A W node gets a record unless
// the engine decides it by itself: a static state, or a winning move into a static loss (the engine's "한 수").
// The certificate was verified before (verify_v4); this tool only reads it.
#include <zlib.h>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
using namespace std;

static int V, G;
static vector<int> esrc, edst, full, gmap;
static vector<pair<int, int>> pairsv;
static vector<int> loopsv;
static vector<vector<int>> outg;

static void die(const char* m) { fprintf(stderr, "cert2site: %s\n", m); exit(1); }

static void read_model(const char* path) {
  FILE* f = fopen(path, "r");
  if (!f) die("cannot open model");
  if (fscanf(f, "%d %d", &V, &G) != 2) die("model header");
  esrc.resize(G); edst.resize(G); full.resize(G); gmap.resize(G); outg.assign(V, {});
  for (int g = 0; g < G; g++) if (fscanf(f, "%d %d", &esrc[g], &edst[g]) != 2) die("edges");
  for (int g = 0; g < G; g++) if (fscanf(f, "%d", &full[g]) != 1) die("full");
  int np; if (fscanf(f, "%d", &np) != 1) die("pairs");
  pairsv.resize(np);
  for (auto& p : pairsv) if (fscanf(f, "%d %d", &p.first, &p.second) != 2) die("pair");
  int nl; if (fscanf(f, "%d", &nl) != 1) die("loops");
  loopsv.resize(nl);
  for (auto& l : loopsv) if (fscanf(f, "%d", &l) != 1) die("loop");
  for (int g = 0; g < G; g++) if (fscanf(f, "%d", &gmap[g]) != 1) die("group map");
  fclose(f);
  for (int g = 0; g < G; g++) outg[esrc[g]].push_back(g);   // same order as model.json's outgoing (by group number)
}

struct Norm { vector<uint8_t> core; int st; };

// site-engine.js normalize(), line for line
static Norm normalize(int cur, const vector<uint8_t>& counts) {
  vector<uint8_t> r(counts);
  for (auto& p : pairsv) { int t = min(r[p.first], r[p.second]); r[p.first] -= t; r[p.second] -= t; }
  for (int l : loopsv) r[l] %= 2;
  vector<uint8_t> reach(V, 0); vector<int> q{cur}; reach[cur] = 1;
  for (size_t i = 0; i < q.size(); i++) for (int g : outg[q[i]]) if (r[g]) { int t = edst[g]; if (!reach[t]) { reach[t] = 1; q.push_back(t); } }
  for (int s = 0; s < V; s++) if (!reach[s]) for (int g : outg[s]) r[g] = 0;
  // staticLabels(paired)
  vector<int8_t> lab(V, -1); vector<vector<int>> succ(V); vector<uint8_t> loop(V, 0);
  for (int g = 0; g < G; g++) if (r[g]) { if (esrc[g] == edst[g]) loop[esrc[g]] = 1; else succ[esrc[g]].push_back(edst[g]); }
  vector<int> pend(V); for (int s = 0; s < V; s++) pend[s] = s;
  while (!pend.empty()) {
    vector<int> rem; bool changed = false;
    for (int src : pend) {
      bool allWin = true, hasLose = false;
      for (int t : succ[src]) { int l = lab[t]; if (l == 0) { hasLose = true; break; } if (l != 1) allWin = false; }
      if (hasLose) { lab[src] = 1; changed = true; }
      else if (allWin) { lab[src] = loop[src]; changed = true; }
      else rem.push_back(src);
    }
    if (!changed) break;
    pend.swap(rem);
  }
  Norm n;
  if (lab[cur] != -1) { n.core = r; n.st = lab[cur]; return n; }
  vector<uint8_t> seen(V, 0); vector<int> q2{cur}; seen[cur] = 1;
  for (size_t i = 0; i < q2.size(); i++) for (int g : outg[q2[i]]) if (r[g]) { int t = edst[g]; if (lab[t] == -1 && !seen[t]) { seen[t] = 1; q2.push_back(t); } }
  n.core.assign(G, 0);
  for (int s = 0; s < V; s++) if (seen[s]) for (int g : outg[s]) if (r[g] && lab[edst[g]] == -1) n.core[g] = r[g];
  n.st = -1;
  return n;
}

struct Rec { uint32_t a, b; uint64_t s; uint16_t g, p; } __attribute__((packed));

static Rec make_rec(int cur, const vector<uint8_t>& core, int g) {
  uint32_t a = 2166136261u, b = 0x9747b28cu; uint64_t s = 1469598103934665603ull;
  vector<uint8_t> bytes; bytes.reserve(G + 2);
  bytes.push_back(cur & 255); bytes.push_back(cur >> 8);
  bytes.insert(bytes.end(), core.begin(), core.end());
  for (uint8_t x : bytes) { a ^= x; a *= 16777619u; s ^= x; s *= 1099511628211ull; }
  for (size_t i = bytes.size(); i-- > 0;) { b ^= bytes[i]; b *= 16777619u; }
  unsigned p = 0; for (uint8_t x : core) p += x;
  if (p > 65535) die("core size");
  Rec r{a, b, s, (uint16_t)g, (uint16_t)p};
  return r;
}

int main(int argc, char** argv) {
  if (argc != 5) die("usage: cert2site MODEL.txt CERT.v4.gz ROOT.txt OUT.bin");
  read_model(argv[1]);
  // certificate
  gzFile z = gzopen(argv[2], "rb");
  if (!z) die("cannot open certificate");
  gzbuffer(z, 1 << 20);
  vector<char> buf(1 << 22);
  if (!gzgets(z, buf.data(), buf.size())) die("empty certificate");
  string head(buf.data());
  auto num_after = [&](const string& h, const char* k) { size_t p = h.find(k); if (p == string::npos) die("header key"); return atol(h.c_str() + p + strlen(k)); };
  if (head.find("\"route-proof-v4\"") == string::npos) die("not a route-proof-v4 certificate");
  if (num_after(head, "\"groups\":") != G || num_after(head, "\"vertices\":") != V) die("certificate does not match the model");
  long root = num_after(head, "\"root\":");
  vector<uint8_t> isW; vector<uint32_t> off{0}; vector<uint16_t> mg; vector<uint32_t> mc;
  while (gzgets(z, buf.data(), buf.size())) {
    const char* l = buf.data();
    if (!*l || *l == '\n') continue;
    const char* pid = strstr(l, "\"id\":"); const char* pr = strstr(l, "\"r\":\""); const char* pm = strstr(l, "\"m\":[");
    if (!pid || !pr || !pm) die("node line");
    if ((long)atol(pid + 5) != (long)isW.size()) die("node ids out of order");
    isW.push_back(pr[5] == 'W');
    const char* p = pm + 5;
    while (true) {
      while (*p == ' ') p++;
      if (*p == ']') break;
      if (*p == ',') { p++; continue; }
      if (*p != '[') die("move syntax");
      char* e; long g = strtol(p + 1, &e, 10); if (*e != ',') die("move syntax");
      long c = strtol(e + 1, &e, 10); if (*e != ']') die("move syntax");
      if (g < 0 || g >= G || c < 0 || c >= (long)isW.size() - 1) die("move out of range");
      mg.push_back((uint16_t)gmap[g]); mc.push_back((uint32_t)c);
      p = e + 1;
    }
    off.push_back((uint32_t)mg.size());
  }
  gzclose(z);
  long n = isW.size();
  if (root != n - 1) die("root is not the last node");
  // root position
  FILE* rf = fopen(argv[3], "r"); if (!rf) die("cannot open root");
  int cur0; if (fscanf(rf, "%d", &cur0) != 1) die("root");
  vector<uint8_t> c0(G);
  for (int g = 0; g < G; g++) { int x; if (fscanf(rf, "%d", &x) != 1) die("root counts"); c0[g] = (uint8_t)x; }
  fclose(rf);
  FILE* out = fopen(argv[4], "wb"); if (!out) die("cannot write output");
  Norm r0 = normalize(cur0, c0);
  long visited = 0, records = 0, one_move = 0, statics = 0;
  vector<uint8_t> seen(n, 0);
  struct Frame { uint32_t id; int cur; vector<uint8_t> core; };
  vector<Frame> st;
  if (r0.st != -1) die("the root is static; nothing to record");
  st.push_back({(uint32_t)root, cur0, r0.core}); seen[root] = 1;
  while (!st.empty()) {
    Frame f = std::move(st.back()); st.pop_back();
    visited++;
    uint32_t a = off[f.id], b = off[f.id + 1];
    if (a == b) { statics++; continue; }                     // a node without moves must be a static state
    if (isW[f.id] && b - a != 1) die("a W node with more than one move");
    for (uint32_t k = a; k < b; k++) {
      int g = mg[k];
      if (esrc[g] != f.cur || !f.core[g]) die("illegal move in the certificate");
      vector<uint8_t> c(f.core); c[g]--;
      Norm cn = normalize(edst[g], c);
      if (isW[f.id]) {
        if (cn.st == 0) one_move++;                          // the engine finds a move into a static loss itself
        else { Rec r = make_rec(f.cur, f.core, g); fwrite(&r, sizeof r, 1, out); records++; }
      }
      uint32_t ch = mc[k];
      if (cn.st == -1 && !seen[ch]) { seen[ch] = 1; st.push_back({ch, edst[g], std::move(cn.core)}); }
      else if (cn.st != -1 && off[ch] != off[ch + 1]) die("a static child with moves");
    }
  }
  fclose(out);
  printf("{\"cert_nodes\": %ld, \"visited\": %ld, \"records\": %ld, \"one_move\": %ld, \"static\": %ld, \"root_result\": \"%c\"}\n",
         n, visited, records, one_move, statics, isW[root] ? 'W' : 'L');
  return 0;
}
