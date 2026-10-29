// solver_v3: df-pn (1+epsilon, optional weak-PN) with a compact 128-bit Zobrist
// transposition table, for the grouped word-chain game. Reads the same numeric
// input as solver_v2 and emits the same route-proof-v2 JSONL certificate, which
// verify_v2.py checks independently (so hash collisions or TT races can only
// produce a REJECTED certificate, never an accepted wrong one).
//
// Main differences from solver_v2:
//  * TT entry = 32 bytes (two 64-bit hash words, pn, dn, work, best); bucketed,
//    smallest-work replacement; never aborts when full (GC by replacement).
//  * children are not stored; a node's children are generated only when it is
//    entered, and are looked up by hash; static children are resolved at
//    generation time (static-L child => immediate win).
//  * incremental canonicalization: a child differs from its (canonical) parent
//    by one consumed word; the reachability / retrograde cascade is computed
//    with 160-bit bitsets and the Zobrist hash is updated incrementally.
//  * df-pn with the 1+epsilon trick and mobility initialisation (pn=1, dn=moves).
//  * optional shared-TT multi-threading (lockless XOR-checked entries).
//  * certificates are rebuilt by replaying moves from the root with an exact,
//    non-incremental reference canonicalization (cross-checked against the
//    incremental one at every emitted edge); TT-evicted nodes are re-solved.
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <fstream>
#include <iostream>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>
#include <sys/mman.h>
#include <zlib.h>
using namespace std;
typedef uint64_t u64;
typedef uint32_t u32;
typedef uint16_t u16;
typedef uint8_t u8;

static constexpr u32 INF = 0xFFFFFFFFu;
static constexpr u32 BIG = 0xFFFFFF00u;  // saturation value for unproven numbers
static inline u32 sat_add(u32 a, u32 b) {
  if (a == INF || b == INF) return INF;
  u64 s = (u64)a + b;
  return s > BIG ? BIG : (u32)s;
}

// ---------------------------------------------------------------- bitsets
constexpr int MAXW = 4;  // up to 256 vertices
struct Bits {
  u64 w[MAXW];
  void clear() { for (int i = 0; i < MAXW; i++) w[i] = 0; }
  bool test(int i) const { return (w[i >> 6] >> (i & 63)) & 1; }
  void set(int i) { w[i >> 6] |= 1ull << (i & 63); }
  void reset(int i) { w[i >> 6] &= ~(1ull << (i & 63)); }
  bool any() const { return (w[0] | w[1] | w[2] | w[3]) != 0; }
  int count() const {
    return __builtin_popcountll(w[0]) + __builtin_popcountll(w[1]) + __builtin_popcountll(w[2]) +
           __builtin_popcountll(w[3]);
  }
  bool operator==(const Bits& o) const {
    return w[0] == o.w[0] && w[1] == o.w[1] && w[2] == o.w[2] && w[3] == o.w[3];
  }
  bool operator!=(const Bits& o) const { return !(*this == o); }
  void operator|=(const Bits& o) { for (int i = 0; i < MAXW; i++) w[i] |= o.w[i]; }
  void operator&=(const Bits& o) { for (int i = 0; i < MAXW; i++) w[i] &= o.w[i]; }
  void andnot(const Bits& o) { for (int i = 0; i < MAXW; i++) w[i] &= ~o.w[i]; }
  Bits operator&(const Bits& o) const { Bits r; for (int i = 0; i < MAXW; i++) r.w[i] = w[i] & o.w[i]; return r; }
  template <class F> void each(F f) const {
    for (int k = 0; k < MAXW; k++)
      for (u64 x = w[k]; x; x &= x - 1) f(k * 64 + __builtin_ctzll(x));
  }
};

// ---------------------------------------------------------------- model
static int N = 0, G = 0, ROOTV = 0;
static vector<int> src_, dst_, rev_;
static vector<vector<int>> outg, incg;
static vector<u64> Z0, Z1;  // Z[g*256+c], Z[.][0]=0
static vector<u64> V0, V1;  // current-vertex keys
static vector<u8> rawcnt;

static u64 splitmix(u64& x) {
  u64 z = (x += 0x9E3779B97F4A7C15ull);
  z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ull;
  z = (z ^ (z >> 27)) * 0x94D049BB133111EBull;
  return z ^ (z >> 31);
}

static void read_input(const string& path) {
  ifstream f(path);
  if (!(f >> N >> G >> ROOTV) || N <= 0 || N > 64 * MAXW || G < 0 || G > 65535 || ROOTV < 0 || ROOTV >= N)
    throw runtime_error("invalid graph header");
  src_.resize(G); dst_.resize(G); rev_.assign(G, -1); rawcnt.assign(G, 0);
  outg.assign(N, {}); incg.assign(N, {});
  unordered_map<u64, int> pm;
  for (int i = 0; i < G; i++) {
    int c;
    if (!(f >> src_[i] >> dst_[i] >> c) || src_[i] < 0 || src_[i] >= N || dst_[i] < 0 || dst_[i] >= N || c < 0 || c > 255)
      throw runtime_error("invalid graph edge");
    if (!pm.emplace((u64)src_[i] * N + dst_[i], i).second) throw runtime_error("duplicate grouped endpoint");
    rawcnt[i] = (u8)c;
    outg[src_[i]].push_back(i);
    incg[dst_[i]].push_back(i);
  }
  string extra;
  if (f >> extra) throw runtime_error("extra graph input");
  for (int i = 0; i < G; i++) {
    auto it = pm.find((u64)dst_[i] * N + src_[i]);
    if (it != pm.end()) rev_[i] = it->second;
  }
  u64 seed = 0x5eed817ull;
  Z0.assign((size_t)G * 256, 0); Z1.assign((size_t)G * 256, 0);
  for (int g = 0; g < G; g++)
    for (int c = 1; c < 256; c++) { Z0[g * 256 + c] = splitmix(seed); Z1[g * 256 + c] = splitmix(seed); }
  V0.resize(N); V1.resize(N);
  for (int v = 0; v < N; v++) { V0[v] = splitmix(seed); V1[v] = splitmix(seed); }
}

static inline void full_hash(int cur, const u8* k, u64& h0, u64& h1) {
  h0 = V0[cur]; h1 = V1[cur];
  for (int g = 0; g < G; g++)
    if (k[g]) { h0 ^= Z0[g * 256 + k[g]]; h1 ^= Z1[g * 256 + k[g]]; }
}

// Reference (non-incremental) canonicalization with exactly the v2 semantics:
// pair/loop cancellation (optional), reachability pruning, least-fixed-point
// static labels, unknown-core pruning. Returns -1 (core) or 0/1 (static L/W).
static int ref_canon(int cur, vector<u8>& k, bool pairs) {
  if (pairs)
    for (int e = 0; e < G; e++) {
      if (src_[e] == dst_[e]) k[e] %= 2;
      else if (rev_[e] > e) { int r = rev_[e]; u8 d = min(k[e], k[r]); k[e] -= d; k[r] -= d; }
    }
  vector<u8> seen(N, 0);
  vector<int> q; q.reserve(N);
  seen[cur] = 1; q.push_back(cur);
  for (size_t i = 0; i < q.size(); i++)
    for (int e : outg[q[i]]) if (k[e] && !seen[dst_[e]]) { seen[dst_[e]] = 1; q.push_back(dst_[e]); }
  for (int e = 0; e < G; e++) if (!seen[src_[e]]) k[e] = 0;
  vector<int> status(N, -1), left(N, 0);
  vector<u8> loop(N, 0);
  q.clear();
  for (int u = 0; u < N; u++) {
    for (int e : outg[u]) if (k[e]) { if (dst_[e] == u) loop[u] = 1; else left[u]++; }
    if (!left[u]) { status[u] = loop[u]; q.push_back(u); }
  }
  for (size_t i = 0; i < q.size(); i++) {
    int t = q[i];
    for (int e : incg[t]) {
      int u = src_[e];
      if (!k[e] || u == t || status[u] != -1) continue;
      if (status[t] == 0) { status[u] = 1; q.push_back(u); }
      else if (--left[u] == 0) { status[u] = loop[u]; q.push_back(u); }
    }
  }
  if (status[cur] != -1) return status[cur];
  fill(seen.begin(), seen.end(), 0); q.clear(); q.push_back(cur); seen[cur] = 1;
  for (size_t i = 0; i < q.size(); i++)
    for (int e : outg[q[i]]) if (k[e] && status[dst_[e]] == -1 && !seen[dst_[e]]) { seen[dst_[e]] = 1; q.push_back(dst_[e]); }
  for (int e = 0; e < G; e++) if (!seen[src_[e]] || status[dst_[e]] != -1) k[e] = 0;
  return -1;
}

// ---------------------------------------------------------------- state
struct State {
  int cur = 0;
  Bits core, loop;
  vector<Bits> succ;  // nonloop successors with positive count, valid for core vertices
  vector<u8> cnt;
  u64 h0 = 0, h1 = 0;
  void init() { succ.resize(N); cnt.assign(G, 0); }
};

// Build a search state from canonical NON-static counts.
static void build_state(int cur, const vector<u8>& k, State& S) {
  S.init();
  S.cur = cur; S.cnt = k; S.core.clear(); S.loop.clear();
  S.core.set(cur);
  for (int u = 0; u < N; u++) S.succ[u].clear();
  for (int g = 0; g < G; g++) if (k[g]) {
    S.core.set(src_[g]); S.core.set(dst_[g]);
    if (src_[g] == dst_[g]) S.loop.set(src_[g]); else S.succ[src_[g]].set(dst_[g]);
  }
  full_hash(cur, k.data(), S.h0, S.h1);
}

struct CI {  // child info
  u64 h0, h1;
  Bits core;
  u32 pn, dn, work;
  u16 g;
  int8_t stat;
  u8 nm;
  bool known;
};

struct Scratch {
  vector<int8_t> label;
  vector<int> rem;
  vector<int> q;
  void init() { label.assign(N, -1); rem.assign(N, 0); q.reserve(N); }
};

// Incremental canonical child of a canonical non-static parent P via group e.
static void gen_child(const State& P, int e, CI& ci, Scratch& sc) {
  const int v = P.cur, w = dst_[e];
  const int c = P.cnt[e];
  ci.g = (u16)e;
  ci.known = false;
  ci.work = 0;
  if (v == w) {  // self-loop (count is 1 in a canonical state): nothing else changes
    ci.core = P.core; ci.stat = -1;
    ci.h0 = P.h0 ^ Z0[e * 256 + c] ^ Z0[e * 256 + c - 1];
    ci.h1 = P.h1 ^ Z1[e * 256 + c] ^ Z1[e * 256 + c - 1];
    ci.nm = (u8)min(255, P.succ[v].count() + (c - 1 > 0 ? 1 : 0));
    return;
  }
  Bits sv = P.succ[v];
  if (c == 1) sv.reset(w);
  // Reachability from w in the child graph. If v is reachable, every parent-core
  // vertex is reachable (paths through e can be cut at their last use of e).
  Bits vis; vis.clear(); vis.set(w);
  Bits fr = vis;
  bool full = false;
  while (fr.any()) {
    Bits nx; nx.clear();
    fr.each([&](int u) { nx |= (u == v ? sv : P.succ[u]); });
    nx.andnot(vis);
    if (nx.test(v)) { full = true; break; }
    vis |= nx;
    fr = nx;
  }
  Bits ncore;
  bool seed = full && !sv.any();
  if (!full) {
    ncore = vis;  // v unreachable: no vertex can become classified
  } else if (!seed) {
    ncore = P.core;
  } else {
    // Only v can seed the retrograde cascade: every other core vertex keeps a
    // nonloop successor. R = parent core.
    Bits L; L.clear();
    Bits remInit; remInit.clear();
    sc.q.clear();
    auto lab = [&](int u, int8_t val) { sc.label[u] = val; L.set(u); sc.q.push_back(u); };
    lab(v, P.loop.test(v) ? 1 : 0);
    for (size_t qi = 0; qi < sc.q.size(); qi++) {
      int t = sc.q[qi];
      int8_t lt = sc.label[t];
      for (int g : incg[t]) {
        int u = src_[g];
        if (u == t || !P.core.test(u) || L.test(u)) continue;
        const Bits& su = (u == v) ? sv : P.succ[u];
        if (!su.test(t)) continue;
        if (lt == 0) lab(u, 1);
        else {
          if (!remInit.test(u)) { sc.rem[u] = su.count(); remInit.set(u); }
          if (--sc.rem[u] == 0) lab(u, P.loop.test(u) ? 1 : 0);
        }
      }
    }
    if (L.test(w)) { ci.stat = sc.label[w]; ci.nm = 0; ci.h0 = ci.h1 = 0; ci.core.clear(); return; }
    // core = unknown vertices reachable from w through unknown vertices
    ncore.clear(); ncore.set(w);
    Bits f2 = ncore;
    while (f2.any()) {
      Bits nx; nx.clear();
      f2.each([&](int u) { nx |= (u == v ? sv : P.succ[u]); });
      nx.andnot(L); nx.andnot(ncore);
      ncore |= nx; f2 = nx;
    }
  }
  ci.stat = -1;
  ci.core = ncore;
  u64 h0 = P.h0 ^ V0[v] ^ V0[w] ^ Z0[e * 256 + c] ^ Z0[e * 256 + c - 1];
  u64 h1 = P.h1 ^ V1[v] ^ V1[w] ^ Z1[e * 256 + c] ^ Z1[e * 256 + c - 1];
  if (ncore != P.core) {
    Bits X = P.core; X.andnot(ncore);
    X.each([&](int u) {
      for (int g : outg[u]) {
        int cc = (g == e) ? c - 1 : P.cnt[g];
        if (cc) { h0 ^= Z0[g * 256 + cc]; h1 ^= Z1[g * 256 + cc]; }
      }
      for (int g : incg[u]) {
        int s = src_[g];
        if (s == u || !ncore.test(s)) continue;
        int cc = (g == e) ? c - 1 : P.cnt[g];
        if (cc) { h0 ^= Z0[g * 256 + cc]; h1 ^= Z1[g * 256 + cc]; }
      }
    });
  }
  ci.h0 = h0; ci.h1 = h1;
  ci.nm = (u8)min(255, (P.succ[w] & ncore).count() + (P.loop.test(w) ? 1 : 0));
}

static void materialize(const State& P, const CI& ci, State& S) {
  const int e = ci.g, v = P.cur, w = dst_[e];
  S.cur = w;
  memcpy(S.cnt.data(), P.cnt.data(), G);
  S.cnt[e]--;
  S.core = ci.core;
  Bits X = P.core; X.andnot(ci.core);
  X.each([&](int u) {
    for (int g : outg[u]) S.cnt[g] = 0;
    for (int g : incg[u]) S.cnt[g] = 0;
  });
  S.loop = P.loop & ci.core;
  ci.core.each([&](int u) { S.succ[u] = P.succ[u] & ci.core; });
  if (v == w) S.loop.reset(v);
  else if (S.cnt[e] == 0 && ci.core.test(v)) S.succ[v].reset(w);
  S.h0 = ci.h0; S.h1 = ci.h1;
}

// ---------------------------------------------------------------- TT
// Entry words: a = k0 ^ c ^ d, b = k1, c = pn | dn<<32, d = work | best<<32 | 1<<63.
struct Entry { atomic<u64> a, b, c, d; };
struct TT {
  Entry* tab = nullptr;
  u64 nb = 0, mask = 0;  // buckets of 4
  size_t bytes = 0;
  atomic<u64> stores{0}, replacements{0};
  void alloc(size_t mb, u64 force_buckets = 0) {
    u64 want = force_buckets ? force_buckets : ((u64)mb << 20) / (4 * sizeof(Entry));
    nb = 1; while (nb * 2 <= want) nb *= 2;
    mask = nb - 1;
    bytes = nb * 4 * sizeof(Entry);
    void* p = mmap(nullptr, bytes, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS | MAP_POPULATE, -1, 0);  // first-touch faults cost ~3 s/GB here
    if (p == MAP_FAILED) throw runtime_error("TT allocation failed");
    tab = (Entry*)p;
  }
  inline Entry* bucket(u64 k1) const { return tab + ((k1 >> 7) & mask) * 4; }
  inline void prefetch(u64 k1) const { __builtin_prefetch(bucket(k1)); }
  bool probe(u64 k0, u64 k1, u32& pn, u32& dn, u32& work, int& best) const {
    Entry* b = bucket(k1);
    for (int i = 0; i < 4; i++) {
      u64 B = b[i].b.load(memory_order_relaxed);
      if (B != k1) continue;
      u64 A = b[i].a.load(memory_order_relaxed), C = b[i].c.load(memory_order_relaxed), D = b[i].d.load(memory_order_relaxed);
      if ((A ^ C ^ D) != k0 || !(D >> 63)) continue;
      pn = (u32)C; dn = (u32)(C >> 32); work = (u32)D; best = (int)((D >> 32) & 0xFFFF);
      if (best == 0xFFFF) best = -1;
      return true;
    }
    return false;
  }
  void store(u64 k0, u64 k1, u32 pn, u32 dn, u32 work, int best) {
    Entry* b = bucket(k1);
    u64 C = (u64)pn | ((u64)dn << 32);
    u64 D = (u64)max<u32>(work, 1) | ((u64)(best < 0 ? 0xFFFF : best) << 32) | (1ull << 63);
    int victim = -1; u64 vw = ~0ull;
    for (int i = 0; i < 4; i++) {
      u64 B = b[i].b.load(memory_order_relaxed);
      u64 A = b[i].a.load(memory_order_relaxed), Cc = b[i].c.load(memory_order_relaxed), Dd = b[i].d.load(memory_order_relaxed);
      bool valid = (Dd >> 63) != 0;
      if (valid && B == k1 && (A ^ Cc ^ Dd) == k0) {
        u32 op = (u32)Cc, od = (u32)(Cc >> 32);
        if ((op == 0 || od == 0) && pn != 0 && dn != 0) return;  // proven results are final
        victim = i; vw = 0; break;
      }
      u64 pri;
      if (!valid) pri = 0;
      else {
        pri = (u32)Dd;
        u32 p = (u32)Cc, d = (u32)(Cc >> 32);
        if (p == 0 || d == 0) pri = pri * 2 + 1;  // proven entries weigh double
        pri += 1;
      }
      if (pri < vw) { vw = pri; victim = i; }
    }
    if (vw > 1) replacements.fetch_add(1, memory_order_relaxed);
    b[victim].b.store(k1, memory_order_relaxed);
    b[victim].c.store(C, memory_order_relaxed);
    b[victim].d.store(D, memory_order_relaxed);
    b[victim].a.store(k0 ^ C ^ D, memory_order_relaxed);
    stores.fetch_add(1, memory_order_relaxed);
  }
  u64 used() const {
    u64 n = 0;
    for (u64 i = 0; i < nb * 4; i++) if (tab[i].d.load(memory_order_relaxed) >> 63) n++;
    return n;
  }
  u64 proven() const {
    u64 n = 0;
    for (u64 i = 0; i < nb * 4; i++) {
      u64 D = tab[i].d.load(memory_order_relaxed);
      if (!(D >> 63)) continue;
      u64 C = tab[i].c.load(memory_order_relaxed);
      if ((u32)C == 0 || (u32)(C >> 32) == 0) n++;
    }
    return n;
  }
};

// ---------------------------------------------------------------- options/global
struct Opt {
  double seconds = 30, emit_seconds = 1e9;
  u64 max_mid = ~0ull;
  size_t tt_mb = 1024;
  double eps = 0.25;
  int init = 1;
  int wpn = 0;
  int threads = 1;
  bool selfcheck = false;
  string proof;
  int vloss = 1;
  u64 tt_buckets = 0;
  int init_div = 16;
  double progress = 0;  // seconds between stderr progress lines (0 = off)
  string tt_load, tt_save;
  double checkpoint = 0;  // seconds between TT checkpoints to tt_save (0 = only at the end)
} opt;
static TT tt;

// ---------------------------------------------------------------- TT persistence (--tt-save / --tt-load)
// The file is bound to the game graph (group numbering, endpoints, Zobrist keys), the canonical root
// and the options that give unproven pn/dn their meaning; a mismatch refuses the load. Records are the
// raw entries (k0, k1, pn|dn<<32, work|best<<32). Virtual-loss marks live in the busy table and are not
// saved. Loaded values are search hints like any TT content: the certificate is still emitted by
// replay and checked by verify_v2.py.
static const char TT_MAGIC[8] = {'Y', 'S', 'T', 'T', '1', 0, 0, 0};
static const char TT_END[8] = {'Y', 'S', 'T', 'T', 'E', 'N', 'D', 0};
struct TTHeader {
  char magic[8];
  u64 graph0, graph1, root0, root1;
  int32_t init, init_div, wpn, reserved;
  u64 count, created;
};
static void graph_fingerprint(u64& f0, u64& f1) {
  u64 s = 0x7474667031ull;
  f0 = 0; f1 = 0;
  auto add = [&](u64 x) { s ^= x; f0 ^= splitmix(s); f1 = (f1 ^ splitmix(s)) * 0x100000001b3ull; };
  add(1); add((u64)N); add((u64)G);
  for (int g = 0; g < G; g++) add(((u64)src_[g] << 32) | (u64)dst_[g]);
  if (G) { add(Z0[256 + 1]); add(Z1[256 + 1]); }
  add(V0[0]); add(V1[0]);
}
static inline void ck_add(u64& h, u64 w) { h = (h ^ w) * 0x100000001b3ull; h ^= h >> 31; }
static void fill_header(TTHeader& h, const State& root) {
  memset(&h, 0, sizeof h);
  memcpy(h.magic, TT_MAGIC, 8);
  graph_fingerprint(h.graph0, h.graph1);
  h.root0 = root.h0; h.root1 = root.h1;
  h.init = opt.init; h.init_div = opt.init_div; h.wpn = opt.wpn;
}
// Writes PATH.tmp, then renames it over PATH. Call only while no searcher thread runs. Returns entries saved.
static u64 tt_save(const string& path, const State& root) {
  const string tmp = path + ".tmp";
  FILE* f = fopen(tmp.c_str(), "wb");
  if (!f) throw runtime_error("cannot create TT file");
  TTHeader h; fill_header(h, root);
  h.created = (u64)time(nullptr);
  bool ok = fwrite(&h, sizeof h, 1, f) == 1;
  u64 ck = 0x5eedc0de, n = 0;
  vector<u64> buf; buf.reserve(4 * 8192);
  for (u64 i = 0; ok && i < tt.nb * 4; i++) {
    Entry& e = tt.tab[i];
    u64 D = e.d.load(memory_order_relaxed);
    if (!(D >> 63)) continue;
    u64 B = e.b.load(memory_order_relaxed), A = e.a.load(memory_order_relaxed), C = e.c.load(memory_order_relaxed);
    u64 rec[4] = {A ^ C ^ D, B, C, D & ~(1ull << 63)};
    for (u64 w : rec) { buf.push_back(w); ck_add(ck, w); }
    n++;
    if (buf.size() == buf.capacity()) { ok = fwrite(buf.data(), 8, buf.size(), f) == buf.size(); buf.clear(); }
  }
  if (ok && !buf.empty()) ok = fwrite(buf.data(), 8, buf.size(), f) == buf.size();
  u64 tail[2] = {n, ck};
  if (ok) ok = fwrite(tail, 8, 2, f) == 2 && fwrite(TT_END, 8, 1, f) == 1;
  // the header's count is patched in last, so a file cut short anywhere fails the load checks
  if (ok) { h.count = n; ok = fseek(f, 0, SEEK_SET) == 0 && fwrite(&h, sizeof h, 1, f) == 1; }
  if (fclose(f) != 0) ok = false;
  if (!ok) { remove(tmp.c_str()); throw runtime_error("TT file write failure"); }
  if (rename(tmp.c_str(), path.c_str())) { remove(tmp.c_str()); throw runtime_error("TT file rename failure"); }
  return n;
}
static u64 tt_load(const string& path, const State& root) {
  FILE* f = fopen(path.c_str(), "rb");
  if (!f) throw runtime_error("cannot open TT file " + path);
  TTHeader h, want; fill_header(want, root);
  auto fail = [&](const string& why) { fclose(f); throw runtime_error("TT file refused: " + why); };
  if (fread(&h, sizeof h, 1, f) != 1 || memcmp(h.magic, TT_MAGIC, 8)) fail("not a solver_v3 TT file");
  if (h.graph0 != want.graph0 || h.graph1 != want.graph1) fail("different game graph (groups, endpoints or hash keys)");
  if (h.root0 != want.root0 || h.root1 != want.root1) fail("different root position");
  if (h.init != want.init || h.init_div != want.init_div || h.wpn != want.wpn) fail("different --init/--init-div/--wpn");
  u64 ck = 0x5eedc0de;
  vector<u64> buf(4 * 8192);
  for (u64 done = 0; done < h.count;) {
    size_t k = (size_t)min<u64>(h.count - done, 8192);
    if (fread(buf.data(), 32, k, f) != k) fail("truncated");
    for (size_t r = 0; r < k; r++) {
      const u64* rec = &buf[4 * r];
      for (int j = 0; j < 4; j++) ck_add(ck, rec[j]);
      int best = (int)((rec[3] >> 32) & 0xFFFF);
      tt.store(rec[0], rec[1], (u32)rec[2], (u32)(rec[2] >> 32), (u32)rec[3], best == 0xFFFF ? -1 : best);
    }
    done += k;
  }
  u64 tail[2]; char end[8];
  if (fread(tail, 8, 2, f) != 2 || fread(end, 8, 1, f) != 1 || memcmp(end, TT_END, 8)) fail("truncated");
  if (tail[0] != h.count || tail[1] != ck) fail("checksum mismatch");
  if (fgetc(f) != EOF) fail("trailing data");
  fclose(f);
  tt.stores = 0; tt.replacements = 0;
  return h.count;
}

// ---------------------------------------------------------------- busy table (multi-thread virtual loss)
struct Busy {
  vector<atomic<u16>> t;
  u64 mask = 0;
  void init(int bits) { t = vector<atomic<u16>>(1ull << bits); mask = (1ull << bits) - 1; for (auto& x : t) x.store(0); }
  inline atomic<u16>& at(u64 k0) { return t[k0 & mask]; }
};

static atomic<u32> root_pn{1}, root_dn{1};
static double next_progress = 0;

static Busy busy;
static atomic<bool> stop_flag{false};
static atomic<bool> ckpt_flag{false};  // stop requested only to write a TT checkpoint
static double next_ckpt = 1e300;
static atomic<u64> g_mid{0}, g_gen{0}, g_selfchecks{0};
static chrono::steady_clock::time_point t_start;
static string stop_reason = "none";
static mutex reason_mu;
// proof-emission deadline (--emit-seconds); checked per emitted node and inside re-solves
static atomic<bool> emit_deadline_on{false};
static chrono::steady_clock::time_point emit_deadline;
static inline bool emit_expired() {
  return emit_deadline_on.load(memory_order_relaxed) && chrono::steady_clock::now() >= emit_deadline;
}

static inline void init_numbers(int nm, int corev, u32& pn, u32& dn) {
  switch (opt.init) {
    case 0: pn = 1; dn = 1; break;
    case 2: pn = 2; dn = (u32)max(1, 2 * nm); break;
    case 3: { u32 sc = 1 + (u32)corev / (u32)opt.init_div; pn = sc; dn = (u32)max(1, nm) * sc; break; }
    case 4: { u32 sc = (u32)corev / (u32)opt.init_div; pn = 1 + sc; dn = (u32)max(1, nm) + sc; break; }
    default: pn = 1; dn = (u32)max(1, nm); break;
  }
}

struct Searcher {
  int id = 0;
  vector<State> st;
  vector<vector<CI>> fr;
  Scratch sc;
  u64 mid_calls = 0, gens = 0;
  u64 rng = 0;
  void init(int maxdepth, int tid) {
    id = tid;
    st.resize(maxdepth + 2);
    for (auto& s : st) s.init();
    fr.resize(maxdepth + 2);
    sc.init();
    rng = 0x1234567ull * (tid + 1);
  }

  void selfcheck_child(const State& P, const CI& ci) {
    vector<u8> k = P.cnt;
    k[ci.g]--;
    int s = ref_canon(dst_[ci.g], k, false);
    if (s != ci.stat) throw runtime_error("selfcheck: static label mismatch");
    if (s == -1) {
      u64 h0, h1; full_hash(dst_[ci.g], k.data(), h0, h1);
      if (h0 != ci.h0 || h1 != ci.h1) throw runtime_error("selfcheck: hash mismatch");
      State T; build_state(dst_[ci.g], k, T);
      if (T.core != ci.core) throw runtime_error("selfcheck: core mismatch");
    }
    g_selfchecks.fetch_add(1, memory_order_relaxed);
  }
  void selfcheck_state(const State& S) {
    State T; build_state(S.cur, S.cnt, T);
    if (T.core != S.core || T.loop != S.loop || T.h0 != S.h0 || T.h1 != S.h1) throw runtime_error("selfcheck: materialize mismatch");
    S.core.each([&](int u) { if (T.succ[u] != S.succ[u]) throw runtime_error("selfcheck: succ mismatch"); });
    vector<u8> k = S.cnt;
    if (ref_canon(S.cur, k, false) != -1 || k != S.cnt) throw runtime_error("selfcheck: state not canonical");
  }

  // Returns node pn/dn; accumulates work.
  void mid(int d, u32 pth, u32 dth, u32& rpn, u32& rdn, u64& rwork) {
    State& S = st[d];
    vector<CI>& ch = fr[d];
    ch.clear();
    mid_calls++;
    if ((mid_calls & 1023) == 0) {
      g_mid.fetch_add(1024, memory_order_relaxed);
      double el = chrono::duration<double>(chrono::steady_clock::now() - t_start).count();
      if (opt.progress > 0 && id == 0 && el >= next_progress) {
        next_progress = el + opt.progress;
        fprintf(stderr, "{\"t\":%.1f,\"mid\":%llu,\"root_pn\":%u,\"root_dn\":%u,\"tt_stores\":%llu,\"tt_repl\":%llu}\n", el,
                (unsigned long long)g_mid.load(), root_pn.load(), root_dn.load(), (unsigned long long)tt.stores.load(),
                (unsigned long long)tt.replacements.load());
      }
      if (el >= opt.seconds) { lock_guard<mutex> l(reason_mu); if (!stop_flag) stop_reason = "time_limit"; stop_flag = true; }
      if (el >= next_ckpt) { lock_guard<mutex> l(reason_mu); if (!stop_flag) { ckpt_flag = true; stop_flag = true; } }
      if (g_mid.load(memory_order_relaxed) >= opt.max_mid) { lock_guard<mutex> l(reason_mu); if (!stop_flag) stop_reason = "node_limit"; stop_flag = true; }
      if (emit_expired()) { lock_guard<mutex> l(reason_mu); if (!stop_flag) stop_reason = "emit_time_limit"; stop_flag = true; }
    }
    u64 work = 1, prevwork = 0;
    { u32 p, q, wk; int b; if (tt.probe(S.h0, S.h1, p, q, wk, b)) prevwork = wk; }
    for (int g : outg[S.cur]) {
      if (!S.cnt[g]) continue;
      ch.emplace_back();
      CI& ci = ch.back();
      gen_child(S, g, ci, sc);
      gens++;
      if (opt.selfcheck) selfcheck_child(S, ci);
      if (ci.stat == 0) {  // static L child: immediate win
        tt.store(S.h0, S.h1, 0, INF, 1, g);
        rpn = 0; rdn = INF; rwork = 1;
        return;
      }
      if (ci.stat == 1) { ci.pn = 0; ci.dn = INF; ci.known = true; }
      else tt.prefetch(ci.h1);
    }
    if (ch.empty()) throw runtime_error("non-static state without moves");
    const bool multi = opt.threads > 1;
    atomic<u16>* mybusy = nullptr;
    if (multi) { mybusy = &busy.at(S.h0); mybusy->fetch_add(1, memory_order_relaxed); }
    u32 pn = 0, dn = 0;
    int bestg = -1;
    for (;;) {
      u32 sumpn = 0, maxpn = 0, mindn = INF;
      int unsolved = 0, mi = -1;
      for (size_t i = 0; i < ch.size(); i++) {
        CI& c = ch[i];
        if (c.stat != 1) {
          u32 p, q, wk; int b;
          if (tt.probe(c.h0, c.h1, p, q, wk, b)) { c.pn = p; c.dn = q; c.work = wk; c.known = true; }
          else if (!c.known) { init_numbers(c.nm, c.core.count(), c.pn, c.dn); }
        }
        if (c.dn < mindn) { mindn = c.dn; mi = (int)i; }
        sumpn = sat_add(sumpn, c.pn);
        if (c.pn != 0) { unsolved++; maxpn = max(maxpn, c.pn); }
      }
      pn = mindn;
      if (opt.wpn) dn = unsolved == 0 ? 0 : (maxpn == INF ? INF : sat_add(maxpn, (u32)(unsolved - 1)));
      else dn = sumpn;
      if (pn == 0) { dn = INF; bestg = ch[mi].g; break; }
      if (dn == 0) { pn = INF; bestg = -1; break; }
      bestg = ch[mi].g;
      if (d == 0) { root_pn.store(pn, memory_order_relaxed); root_dn.store(dn, memory_order_relaxed); }
      if (pn >= pth || dn >= dth || stop_flag.load(memory_order_relaxed)) break;
      int bi = mi;
      if (multi) {  // virtual loss: steer away from children other threads are searching
        u32 bestsel = INF;
        for (size_t i = 0; i < ch.size(); i++) {
          CI& c = ch[i];
          if (c.dn >= pth || c.pn == 0) continue;
          u32 sel = c.dn;
          u16 bz = busy.at(c.h0).load(memory_order_relaxed);
          if (bz) sel = sat_add(sel, (u32)bz * (u32)opt.vloss * (c.dn / 2 + 1));
          if (sel < bestsel) { bestsel = sel; bi = (int)i; }
        }
      }
      CI& c = ch[bi];
      u32 second = INF;  // smallest dn among the other children
      for (size_t i = 0; i < ch.size(); i++) if ((int)i != bi && ch[i].dn < second) second = ch[i].dn;
      u32 cpth;
      if (dth >= INF) cpth = INF;
      else if (opt.wpn) cpth = dth - (u32)(unsolved - 1);
      else cpth = dth - (dn - c.pn);
      u32 cdth;
      if (second >= BIG) cdth = pth;
      else {
        u64 a = (u64)second + 1;
        u64 b = (u64)ceil((double)second * (1.0 + opt.eps));
        cdth = (u32)min<u64>(pth, max(a, b));
      }
      if (cdth <= c.dn) cdth = c.dn + 1;  // can only happen under virtual-loss reordering
      if (cdth > pth) cdth = pth;
      materialize(S, c, st[d + 1]);
      if (opt.selfcheck) selfcheck_state(st[d + 1]);
      u32 cp, cd; u64 cw;
      mid(d + 1, cpth, cdth, cp, cd, cw);
      c.pn = cp; c.dn = cd; c.known = true; c.work = (u32)min<u64>(cw, 0xFFFFFFFFull);
      work += cw;
    }
    if (multi) mybusy->fetch_sub(1, memory_order_relaxed);
    tt.store(S.h0, S.h1, pn, dn, (u32)min<u64>(work + prevwork, 0xFFFFFFF0ull), bestg);
    rpn = pn; rdn = dn; rwork = work;
  }
};

// ---------------------------------------------------------------- proof emission
struct Emitter {
  gzFile gz = nullptr;
  FILE* fp = nullptr;
  string body;
  unordered_map<u64, vector<pair<u64, u32>>> ids;  // h0 -> (h1, id)
  u32 count = 0;
  u64 resolves = 0, resolve_mid = 0, crosschecks = 0;
  Searcher* S = nullptr;
  vector<State> es;
  chrono::steady_clock::time_point t0;
  void write(const string& s) {
    if (gz) { if (gzwrite(gz, s.data(), (unsigned)s.size()) != (int)s.size()) throw runtime_error("proof write failure"); }
    else if (fwrite(s.data(), 1, s.size(), fp) != s.size()) throw runtime_error("proof write failure");
  }
  bool find(u64 h0, u64 h1, u32& id) {
    auto it = ids.find(h0);
    if (it == ids.end()) return false;
    for (auto& p : it->second) if (p.first == h1) { id = p.second; return true; }
    return false;
  }
  u32 put(int v, const vector<u8>& k, bool win, const vector<pair<int, u32>>& moves, u64 h0, u64 h1) {
    static const char* hx = "0123456789abcdef";
    string line;
    line.reserve(64 + 2 * G + 16 * moves.size());
    line += "{\"id\":"; line += to_string(count); line += ",\"v\":"; line += to_string(v); line += ",\"c\":\"";
    for (int g = 0; g < G; g++) { line += hx[k[g] >> 4]; line += hx[k[g] & 15]; }
    line += "\",\"r\":\""; line += win ? 'W' : 'L'; line += "\",\"m\":[";
    for (size_t i = 0; i < moves.size(); i++) {
      if (i) line += ',';
      line += '['; line += to_string(moves[i].first); line += ','; line += to_string(moves[i].second); line += ']';
    }
    line += "]}\n";
    write(line);
    ids[h0].push_back({h1, count});
    return count++;
  }
  // make sure state es[d] (canonical non-static) is proven in the TT; returns win?
  bool ensure(int d) {
    u32 p, q, w; int b;
    if (tt.probe(es[d].h0, es[d].h1, p, q, w, b) && (p == 0 || q == 0)) return p == 0;
    resolves++;
    State& R = S->st[0];
    R.cur = es[d].cur; R.core = es[d].core; R.loop = es[d].loop; R.succ = es[d].succ; R.cnt = es[d].cnt; R.h0 = es[d].h0; R.h1 = es[d].h1;
    for (;;) {
      u32 rp, rd; u64 rw;
      if (emit_expired()) throw runtime_error("emission time limit while re-solving an evicted node");
      u64 before = S->mid_calls;
      stop_flag = false;
      S->mid(0, INF, INF, rp, rd, rw);
      resolve_mid += S->mid_calls - before;
      if (rp == 0 || rd == 0) {
        // the TT may have evicted the root right away; store again
        tt.store(es[d].h0, es[d].h1, rp, rd, (u32)min<u64>(rw, 0xFFFFFFF0ull), -1);
        return rp == 0;
      }
      if (emit_expired()) throw runtime_error("emission time limit while re-solving an evicted node");
    }
  }
  // es[d] holds a canonical state with known static flag `stat`. Returns id; sets win.
  u32 emit(int d, int stat, bool& win) {
    if (emit_expired()) throw runtime_error("emission time limit");
    State& E = es[d];
    u32 id;
    if (find(E.h0, E.h1, id)) {
      // result is recomputable but we must report it: store with id
      win = res[id];
      return id;
    }
    if (stat != -1) {
      win = stat == 1;
      id = put(E.cur, E.cnt, win, {}, E.h0, E.h1);
      res.push_back(win);
      return id;
    }
    bool claim = ensure(d);
    // enumerate children
    vector<CI> ch;
    for (int g : outg[E.cur]) if (E.cnt[g]) { ch.emplace_back(); gen_child(E, g, ch.back(), S->sc); }
    vector<pair<int, u32>> moves;
    auto child = [&](const CI& ci, bool& cwin) -> u32 {
      // exact reference child, cross-checked against the incremental child
      vector<u8> k = E.cnt;
      k[ci.g]--;
      int w = dst_[ci.g];
      int s = ref_canon(w, k, false);
      if (s != ci.stat) throw runtime_error("emission: static mismatch between incremental and reference canonicalization");
      State& C = es[d + 1];
      if (s == -1) {
        build_state(w, k, C);
        if (C.h0 != ci.h0 || C.h1 != ci.h1 || C.core != ci.core) throw runtime_error("emission: hash/core mismatch");
      } else {
        C.init(); C.cur = w; C.cnt = k; full_hash(w, k.data(), C.h0, C.h1);
      }
      crosschecks++;
      return emit(d + 1, s, cwin);
    };
    if (claim) {
      // candidate order: static L, TT best, TT-proven L (least work first), rest
      u32 p, q, wk; int best = -1;
      tt.probe(E.h0, E.h1, p, q, wk, best);
      vector<pair<u64, int>> order;
      for (size_t i = 0; i < ch.size(); i++) {
        CI& c = ch[i];
        u64 key;
        if (c.stat == 0) key = 0;
        else if (c.stat == 1) continue;
        else {
          u32 cp, cd, cw; int cb;
          bool f = tt.probe(c.h0, c.h1, cp, cd, cw, cb);
          if (f && cd == 0) key = 2 + cw;
          else if (c.g == best) key = 1;
          else if (f && cp == 0) continue;  // proven W for the opponent: useless
          else key = (1ull << 40) + (f ? cd : 1);
        }
        order.push_back({key, (int)i});
      }
      sort(order.begin(), order.end());
      bool found = false;
      for (auto& o : order) {
        bool cw;
        u32 cid = child(ch[o.second], cw);
        if (!cw) { moves.push_back({ch[o.second].g, cid}); found = true; break; }
      }
      if (!found) throw runtime_error("emission: no losing child for a node proven W (hash collision?)");
    } else {
      for (auto& c : ch) {
        bool cw;
        u32 cid = child(c, cw);
        if (!cw) throw runtime_error("emission: a child of an L node is L (hash collision?)");
        moves.push_back({c.g, cid});
      }
    }
    win = claim;
    id = put(E.cur, E.cnt, win, moves, E.h0, E.h1);
    res.push_back(win);
    return id;
  }
  vector<bool> res;
};

static string jnum(double x) { char b[64]; snprintf(b, sizeof b, "%.6f", x); return b; }

int main(int argc, char** argv) {
  try {
    if (argc < 2) throw runtime_error("usage: solver_v3 INPUT [--seconds S] [--nodes MAXMID] [--proof OUT[.gz]] [--tt-mb MB] [--threads T] [--eps E] [--init 0|1|2] [--wpn 0|1] [--selfcheck 0|1] [--emit-seconds S] [--tt-load FILE] [--tt-save FILE] [--checkpoint-seconds S]");
    for (int i = 2; i < argc; i++) {
      string x = argv[i];
      if (i + 1 >= argc) throw runtime_error("missing option value");
      string v = argv[++i];
      if (x == "--seconds") opt.seconds = stod(v);
      else if (x == "--nodes") opt.max_mid = stoull(v);
      else if (x == "--proof") opt.proof = v;
      else if (x == "--tt-mb") opt.tt_mb = stoull(v);
      else if (x == "--threads") opt.threads = stoi(v);
      else if (x == "--eps") opt.eps = stod(v);
      else if (x == "--init") opt.init = stoi(v);
      else if (x == "--wpn") opt.wpn = stoi(v);
      else if (x == "--selfcheck") opt.selfcheck = stoi(v) != 0;
      else if (x == "--emit-seconds") opt.emit_seconds = stod(v);
      else if (x == "--vloss") opt.vloss = stoi(v);
      else if (x == "--tt-buckets") opt.tt_buckets = stoull(v);
      else if (x == "--progress") opt.progress = stod(v);
      else if (x == "--init-div") opt.init_div = max(1, stoi(v));
      else if (x == "--tt-load") opt.tt_load = v;
      else if (x == "--tt-save") opt.tt_save = v;
      else if (x == "--checkpoint-seconds") opt.checkpoint = stod(v);
      else throw runtime_error("unknown option: " + x);
    }
    if (!isfinite(opt.seconds) || opt.seconds < 0 || opt.threads < 1 || opt.threads > 64 || opt.tt_mb < 1 || opt.eps < 0 ||
        !isfinite(opt.checkpoint) || opt.checkpoint < 0 || (opt.checkpoint > 0 && opt.tt_save.empty()))
      throw runtime_error("invalid option value");
    read_input(argv[1]);
    tt.alloc(opt.tt_mb, opt.tt_buckets);
    if (opt.threads > 1) busy.init(20);
    int totalwords = 0;
    for (int g = 0; g < G; g++) totalwords += rawcnt[g];
    vector<u8> rk = rawcnt;
    int rstat = ref_canon(ROOTV, rk, true);
    State root;
    if (rstat == -1) build_state(ROOTV, rk, root);
    else { root.init(); root.cur = ROOTV; root.cnt = rk; full_hash(ROOTV, rk.data(), root.h0, root.h1); }
    int maxdepth = totalwords + 2;
    u64 tt_loaded = 0, tt_saves = 0, tt_saved = 0;
    double tt_load_s = 0, tt_save_s = 0;
    string tt_save_error;
    if (!opt.tt_load.empty()) {
      auto t0 = chrono::steady_clock::now();
      tt_loaded = tt_load(opt.tt_load, root);
      tt_load_s = chrono::duration<double>(chrono::steady_clock::now() - t0).count();
    }
    auto save_now = [&]() {
      auto t0 = chrono::steady_clock::now();
      try { tt_saved = tt_save(opt.tt_save, root); tt_saves++; } catch (const exception& e) { tt_save_error = e.what(); }
      tt_save_s += chrono::duration<double>(chrono::steady_clock::now() - t0).count();
    };
    if (opt.checkpoint > 0) next_ckpt = opt.checkpoint;
    t_start = chrono::steady_clock::now();
    vector<Searcher> ss(opt.threads);
    for (int i = 0; i < opt.threads; i++) ss[i].init(maxdepth, i);
    u32 rpn = rstat == -1 ? 1 : (rstat ? 0 : INF), rdn = rstat == -1 ? 1 : (rstat ? INF : 0);
    bool root_solved = false;
    if (rstat == -1) {
      auto run = [&](int i) {
        Searcher& s = ss[i];
        s.st[0] = root;
        u32 p = 1, q = 1; u64 w;
        while (!stop_flag.load()) {
          s.mid(0, INF, INF, p, q, w);
          if (p == 0 || q == 0) {
            lock_guard<mutex> l(reason_mu);
            if (!root_solved) { root_solved = true; rpn = p; rdn = q; }
            stop_flag = true;
            break;
          }
        }
        if (i == 0) { lock_guard<mutex> l(reason_mu); if (!root_solved) { rpn = p; rdn = q; } }
      };
      for (;;) {
        if (opt.threads == 1) run(0);
        else {
          vector<thread> th;
          for (int i = 0; i < opt.threads; i++) th.emplace_back(run, i);
          for (auto& t : th) t.join();
        }
        if (!ckpt_flag || root_solved) break;
        // every searcher has unwound and stored its values: the table is consistent; save it and go on
        save_now();
        ckpt_flag = false;
        next_ckpt = chrono::duration<double>(chrono::steady_clock::now() - t_start).count() + opt.checkpoint;
        stop_flag = false;
      }
      ckpt_flag = false;
    }
    double elapsed = chrono::duration<double>(chrono::steady_clock::now() - t_start).count();
    string result = rpn == 0 ? "win" : rdn == 0 ? "loss" : "unknown";
    // a solved root needs no resume; only an unfinished search is saved at the end
    if (!opt.tt_save.empty() && result == "unknown") save_now();
    if (result != "unknown") stop_reason = "none";
    u64 mid_total = 0, gen_total = 0;
    for (auto& s : ss) { mid_total += s.mid_calls; gen_total += s.gens; }
    int bestg = -1;
    { u32 p, q, w; int b; if (rstat == -1 && tt.probe(root.h0, root.h1, p, q, w, b)) bestg = b; }
    // emission
    u64 proof_nodes = 0, resolves = 0, resolve_mid = 0, crosschecks = 0;
    double emit_s = 0;
    string vstatus = "none";
    string proof_error;
    if (result != "unknown" && !opt.proof.empty()) {
      auto t0 = chrono::steady_clock::now();
      emit_deadline = t0 + chrono::duration_cast<chrono::steady_clock::duration>(chrono::duration<double>(min(opt.emit_seconds, 1e9)));
      emit_deadline_on = true;
      const string tmp = opt.proof + ".body.tmp", out = opt.proof + ".tmp";
      Emitter em;
      try {
      stop_flag = false;
      opt.seconds = 1e18; opt.max_mid = ~0ull;
      em.S = &ss[0];
      em.t0 = t0;
      em.es.resize(maxdepth + 2);
      for (auto& s : em.es) s.init();
      bool gzip = opt.proof.size() > 3 && opt.proof.substr(opt.proof.size() - 3) == ".gz";
      if (gzip) { em.gz = gzopen(tmp.c_str(), "wb6"); if (!em.gz) throw runtime_error("cannot create proof body"); }
      else { em.fp = fopen(tmp.c_str(), "wb"); if (!em.fp) throw runtime_error("cannot create proof body"); }
      opt.threads = 1;
      em.es[0] = root;
      bool win;
      u32 rid = em.emit(0, rstat, win);
      if (win != (result == "win")) throw runtime_error("emission result differs from search result");
      if (gzip) { gzclose(em.gz); em.gz = nullptr; } else { fclose(em.fp); em.fp = nullptr; }
      string head = "{\"format\":\"route-proof-v2\",\"groups\":" + to_string(G) + ",\"vertices\":" + to_string(N) + ",\"root\":" + to_string(rid) + "}\n";
      if (gzip) {
        // concatenated gzip members are a valid gzip stream
        gzFile h = gzopen(out.c_str(), "wb6");
        gzwrite(h, head.data(), (unsigned)head.size());
        gzclose(h);
        FILE* o = fopen(out.c_str(), "ab"); FILE* in = fopen(tmp.c_str(), "rb");
        char buf[1 << 16]; size_t n;
        while ((n = fread(buf, 1, sizeof buf, in)) > 0) {
          if (fwrite(buf, 1, n, o) != n || emit_expired()) {
            fclose(in); fclose(o);
            throw runtime_error(emit_expired() ? "emission time limit while finalizing the proof file" : "proof finalize failure");
          }
        }
        fclose(in); if (fclose(o)) throw runtime_error("proof finalize failure");
      } else {
        FILE* o = fopen(out.c_str(), "wb"); FILE* in = fopen(tmp.c_str(), "rb");
        fwrite(head.data(), 1, head.size(), o);
        char buf[1 << 16]; size_t n;
        while ((n = fread(buf, 1, sizeof buf, in)) > 0) {
          if (fwrite(buf, 1, n, o) != n || emit_expired()) {
            fclose(in); fclose(o);
            throw runtime_error(emit_expired() ? "emission time limit while finalizing the proof file" : "proof finalize failure");
          }
        }
        fclose(in); if (fclose(o)) throw runtime_error("proof finalize failure");
      }
      if (emit_expired()) throw runtime_error("emission time limit while finalizing the proof file");
      remove(tmp.c_str());
      if (rename(out.c_str(), opt.proof.c_str())) throw runtime_error("proof rename failure");
      proof_nodes = em.count; resolves = em.resolves; resolve_mid = em.resolve_mid; crosschecks = em.crosschecks;
      emit_s = chrono::duration<double>(chrono::steady_clock::now() - t0).count();
      } catch (const exception& e) {
        if (em.gz) { gzclose(em.gz); em.gz = nullptr; }
        if (em.fp) { fclose(em.fp); em.fp = nullptr; }
        remove(tmp.c_str()); remove(out.c_str());
        proof_error = e.what();
        proof_nodes = 0;
        emit_s = chrono::duration<double>(chrono::steady_clock::now() - t0).count();
      }
      emit_deadline_on = false;
    }
    u64 used = tt.used();
    printf("{\"result\":\"%s\",\"reason\":\"%s\",\"mid_calls\":%llu,\"child_gens\":%llu,\"tt_entries\":%llu,\"tt_capacity\":%llu,\"tt_mb\":%zu,"
           "\"tt_stores\":%llu,\"tt_replacements\":%llu,\"seconds\":%s,\"pn\":%u,\"dn\":%u,\"best_group\":%d,\"threads\":%d,"
           "\"eps\":%g,\"init\":%d,\"wpn\":%d,\"proof_nodes\":%llu,\"emit_resolves\":%llu,\"emit_resolve_mid\":%llu,"
           "\"emit_crosschecks\":%llu,\"emit_seconds\":%s,\"selfchecks\":%llu,\"proof_error\":\"%s\","
           "\"tt_loaded\":%llu,\"tt_load_seconds\":%s,\"tt_saves\":%llu,\"tt_saved\":%llu,\"tt_save_seconds\":%s,"
           "\"tt_save_error\":\"%s\"}\n",
           result.c_str(), stop_reason.c_str(), (unsigned long long)mid_total, (unsigned long long)gen_total,
           (unsigned long long)used, (unsigned long long)(tt.nb * 4), (size_t)(tt.bytes >> 20),
           (unsigned long long)tt.stores.load(), (unsigned long long)tt.replacements.load(), jnum(elapsed).c_str(), rpn, rdn, bestg,
           (int)ss.size(), opt.eps, opt.init, opt.wpn, (unsigned long long)proof_nodes, (unsigned long long)resolves,
           (unsigned long long)resolve_mid, (unsigned long long)crosschecks, jnum(emit_s).c_str(),
           (unsigned long long)g_selfchecks.load(), proof_error.c_str(), (unsigned long long)tt_loaded, jnum(tt_load_s).c_str(),
           (unsigned long long)tt_saves, (unsigned long long)tt_saved, jnum(tt_save_s).c_str(), tt_save_error.c_str());
    return !proof_error.empty() ? 3 : !tt_save_error.empty() ? 4 : 0;
  } catch (const exception& e) {
    fprintf(stderr, "solver error: %s\n", e.what());
    return 2;
  }
}
