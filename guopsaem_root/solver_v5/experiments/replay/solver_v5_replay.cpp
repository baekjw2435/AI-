// solver_v5_replay (experiment, 2026-11-12): solver_v5 plus STRATEGY REPLAY before the search.
//   --replay FILE          a route-proof-v4 certificate of a RELATED position of the same dictionary (for example
//                          the handed-over syllable with no word used, when this input is the same position with
//                          one word missing). Before the search, the old certificate is walked from its root next
//                          to the real new position: the same group moves are played in both. The old file only
//                          says which move to try; every value is decided on the NEW state:
//                            - children, pair/loop cancellation, static labels and legality come from the new counts
//                              (gen_child / apply_child, the solver's own canonicalization);
//                            - a new state is recorded as W only if one of ITS children is proven L, and as L only
//                              if EVERY legal move of the new state has a child proven W;
//                            - results are stored in the table under the new state's 128-bit key; a state reached
//                              again is looked up by that key, never by the old node number.
//                          Where the old line cannot be followed (the old winning move is gone or now loses, the
//                          new state has a move the old node did not list, the old node was a static leaf but the
//                          new state is not) the state is "stuck".
//   --replay-stuck-nodes N each stuck state gets one df-pn search of at most about N nodes (default 200000;
//                          0 = none). What stays unknown is left to the normal search that follows, inside the
//                          same --seconds budget (replay time counts), and if that does not finish the result is
//                          "unknown" as always.
//   The certificate is then written by the unchanged emitter (replay with the reference canonicalization) and
//   must pass the unchanged verifier: replay results are table hints like any other table content.
//   Output adds replay_* fields. Without --replay the program behaves as solver_v5.
//
// solver_v5 (with the proven-state cache): solver_v5 plus a proven-state cache shared across jobs of the same dictionary.
//   --proven-save FILE   at the end, write every proven TT entry (pn == 0 or dn == 0) to FILE; the header
//                        binds the file to the game graph (graph_fingerprint) but NOT to the root.
//   --proven-load FILE   (repeatable) before the search, insert the entries of FILE into the TT as proven
//                        hints with work = PROVEN_BASE + original work, so the replacement policy keeps them.
//   --proven-min-work W  save only entries whose (original) work is >= W (default 1 = all).
//   --proven-load-min-work W  load only entries whose recorded work is >= W (default 1 = all).
//   --proven-save-loaded 0|1  also save entries that came from --proven-load (default 0: only new proofs).
//   --proven-load-max N  load at most the N records with the most work from EACH --proven-load file
//                        (default 0 = all), so one shared cache cannot take more than N table slots.
//   --proven-load-fraction F  the same cap as a fraction of the table's ACTUAL slots (tt_capacity: the bucket
//                        count is rounded down to a power of two, so --tt-mb 3072 gives 2 GB); with both
//                        options the smaller cap applies (2026-11-07).
//   --tt-save-loaded 0|1 also write entries that came from --proven-load into --tt-save files (default 0:
//                        they live in the cache file; before 2026-11-06 they were written and, ranked by
//                        PROVEN_BASE + work, filled the --tt-save-max budget ahead of the job's own entries).
//   A job's own work is capped at PROVEN_BASE - 1 when stored, so work >= PROVEN_BASE always means a cache
//   record. (Before 2026-11-06 a node searched for more than 2^30 nodes in total, e.g. a resumed root, could
//   cross that line and be taken for one.)
//   --tt-load repairs such records in files written before that (2026-11-07): an OPEN record with work >=
//   PROVEN_BASE is the job's own (cache records are always proven), so its work is capped to PROVEN_BASE - 1;
//   a PROVEN one is looked up among the records the --proven-load files will actually insert this run (same
//   cap as proven_load): found there, it is left to the cache load; otherwise (not in a cache file, or beyond
//   the cap) it is kept as the job's own record with work min(work - PROVEN_BASE, PROVEN_BASE - 1). Counts are
//   reported as tt_load_open_capped, tt_load_proven_in_cache and tt_load_proven_kept.
// Proven values are properties of the canonical state (vertex + canonical counts); the Zobrist keys depend
// only on the game graph. Loaded entries are hints: certificates are still produced by replay with the
// reference canonicalization and checked by the verifier. Without these options the behaviour is solver_v5's.
//
// solver_v5: solver_v4 with the same search and fewer CPU cycles per node: the search state is
// changed in place and restored from an undo log instead of being copied at every depth, rows of
// State::succ are masked lazily, and the breadth-first searches read the rows directly.
// Same input, output and certificates as solver_v4 (single-thread runs are bit-identical).
//
// solver_v4: solver_v3 generalized to the one-way standard initial-sound rule of the
// 구없샘 study. Input: "N G ROOT", then per group "k s1..sk t count" (a group with
// k > 1 sources is one word usable from several vertices, e.g. after 낙 and after 락).
// Emits route-proof-v3, checked independently by guopsaem_root/verifier_v3/verify_v3.py.
// Up to 512 vertices. Everything below the model section is solver_v3 unchanged.
//
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
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <fstream>
#include <map>
#include <iostream>
#include <mutex>
#include <numeric>
#include <stdexcept>
#include <string>
#include <thread>
#include <unordered_map>
#include <unordered_set>
#include <vector>
#include <sys/mman.h>
#include <unistd.h>
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
constexpr int MAXW = 8;  // up to 512 vertices
struct Bits {
  u64 w[MAXW];
  void clear() { for (int i = 0; i < MAXW; i++) w[i] = 0; }
  bool test(int i) const { return (w[i >> 6] >> (i & 63)) & 1; }
  void set(int i) { w[i >> 6] |= 1ull << (i & 63); }
  void reset(int i) { w[i >> 6] &= ~(1ull << (i & 63)); }
  void assign(int i, bool b) { if (b) set(i); else reset(i); }
  bool any() const { u64 x = 0; for (int i = 0; i < MAXW; i++) x |= w[i]; return x != 0; }
  int count() const { int c = 0; for (int i = 0; i < MAXW; i++) c += __builtin_popcountll(w[i]); return c; }
  bool operator==(const Bits& o) const { for (int i = 0; i < MAXW; i++) if (w[i] != o.w[i]) return false; return true; }
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
// A group may be usable from several vertices ("shared": one word that can follow
// both 낙 and 락, say). srcs_[g] lists them; dst_[g] is the single target.
static int N = 0, G = 0, ROOTV = 0;
constexpr int MAXSRC = 4;
static vector<vector<int>> srcs_, avail, incg, preds, sloopg;
static vector<vector<vector<int>>> sib_;  // sib_[e][i]: other groups usable at srcs_[e][i] with target dst_[e]
static vector<int> dst_, rev_;            // rev_ only between single-source groups
static vector<u8> single_;
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
  srcs_.assign(G, {}); dst_.assign(G, 0); rev_.assign(G, -1); single_.assign(G, 0); rawcnt.assign(G, 0);
  avail.assign(N, {}); incg.assign(N, {}); preds.assign(N, {}); sloopg.assign(N, {}); sib_.assign(G, {});
  map<pair<vector<int>, int>, int> seen;
  map<pair<int, int>, int> single_at;
  for (int i = 0; i < G; i++) {
    int k, c;
    if (!(f >> k) || k < 1 || k > MAXSRC) throw runtime_error("invalid group source count");
    for (int j = 0; j < k; j++) {
      int s;
      if (!(f >> s) || s < 0 || s >= N || (j && s <= srcs_[i].back())) throw runtime_error("invalid group source");
      srcs_[i].push_back(s);
    }
    if (!(f >> dst_[i] >> c) || dst_[i] < 0 || dst_[i] >= N || c < 0 || c > 255) throw runtime_error("invalid graph edge");
    if (!seen.emplace(make_pair(srcs_[i], dst_[i]), i).second) throw runtime_error("duplicate grouped endpoint");
    rawcnt[i] = (u8)c;
    single_[i] = k == 1;
    if (k == 1) single_at[{srcs_[i][0], dst_[i]}] = i;
    for (int s : srcs_[i]) avail[s].push_back(i);
    incg[dst_[i]].push_back(i);
  }
  string extra;
  if (f >> extra) throw runtime_error("extra graph input");
  for (int i = 0; i < G; i++) {
    if (single_[i] && srcs_[i][0] != dst_[i]) {
      auto it = single_at.find({dst_[i], srcs_[i][0]});
      if (it != single_at.end()) rev_[i] = it->second;
    }
    for (int s : srcs_[i]) {
      if (s == dst_[i]) { if (!single_[i]) sloopg[s].push_back(i); }
      else if (find(preds[dst_[i]].begin(), preds[dst_[i]].end(), s) == preds[dst_[i]].end()) preds[dst_[i]].push_back(s);
      vector<int> other;
      for (int g : avail[s]) if (g != i && dst_[g] == dst_[i]) other.push_back(g);
      sib_[i].push_back(other);
    }
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

// Reference (non-incremental) canonicalization with exactly the verify_v3 semantics:
// pair/loop cancellation between single-source groups (optional), pruning of groups
// with no reachable source, least-fixed-point static labels (a shared loop blocks the
// loop rule), unknown-core pruning. Returns -1 (core) or 0/1 (static L/W).
static int ref_canon(int cur, vector<u8>& k, bool pairs) {
  if (pairs)
    for (int e = 0; e < G; e++) {
      if (!single_[e]) continue;
      if (srcs_[e][0] == dst_[e]) k[e] %= 2;
      else if (rev_[e] > e) { int r = rev_[e]; u8 d = min(k[e], k[r]); k[e] -= d; k[r] -= d; }
    }
  vector<u8> seen(N, 0);
  vector<int> q; q.reserve(N);
  seen[cur] = 1; q.push_back(cur);
  for (size_t i = 0; i < q.size(); i++)
    for (int e : avail[q[i]]) if (k[e] && !seen[dst_[e]]) { seen[dst_[e]] = 1; q.push_back(dst_[e]); }
  for (int e = 0; e < G; e++) {
    if (!k[e]) continue;
    bool any = false;
    for (int s : srcs_[e]) if (seen[s]) any = true;
    if (!any) k[e] = 0;
  }
  vector<Bits> sb(N);
  for (auto& b : sb) b.clear();
  vector<u8> loop(N, 0), sloop(N, 0);
  for (int e = 0; e < G; e++) if (k[e])
    for (int s : srcs_[e]) {
      if (s == dst_[e]) (single_[e] ? loop : sloop)[s] = 1;
      else sb[s].set(dst_[e]);
    }
  vector<int> status(N, -1), left(N, 0);
  q.clear();
  for (int u = 0; u < N; u++) {
    left[u] = sb[u].count();
    if (!left[u] && !sloop[u]) { status[u] = loop[u]; q.push_back(u); }
  }
  for (size_t i = 0; i < q.size(); i++) {
    int t = q[i];
    for (int u : preds[t]) {
      if (status[u] != -1 || !sb[u].test(t)) continue;
      if (status[t] == 0) { status[u] = 1; q.push_back(u); }
      else if (--left[u] == 0 && !sloop[u]) { status[u] = loop[u]; q.push_back(u); }
    }
  }
  if (status[cur] != -1) return status[cur];
  fill(seen.begin(), seen.end(), 0); q.clear(); q.push_back(cur); seen[cur] = 1;
  for (size_t i = 0; i < q.size(); i++)
    for (int e : avail[q[i]]) if (k[e] && status[dst_[e]] == -1 && !seen[dst_[e]]) { seen[dst_[e]] = 1; q.push_back(dst_[e]); }
  for (int e = 0; e < G; e++) {
    if (!k[e]) continue;
    bool any = false;
    for (int s : srcs_[e]) if (seen[s]) any = true;
    if (!any || status[dst_[e]] != -1) k[e] = 0;
  }
  return -1;
}

// ---------------------------------------------------------------- state
struct State {
  int cur = 0;
  Bits core, loop, sloop;  // loop: single-source loop; sloop: shared group leading back
  vector<Bits> succ;  // for core u: (succ[u] & core) = nonloop successors with positive count (rows may keep stale bits)
  vector<u8> cnt;
  u64 h0 = 0, h1 = 0;
  void init() { succ.resize(N); cnt.assign(G, 0); }
};

// Build a search state from canonical NON-static counts.
static void build_state(int cur, const vector<u8>& k, State& S) {
  S.init();
  S.cur = cur; S.cnt = k; S.core.clear(); S.loop.clear(); S.sloop.clear();
  for (int u = 0; u < N; u++) S.succ[u].clear();
  vector<int> q{cur};
  S.core.set(cur);
  for (size_t i = 0; i < q.size(); i++)
    for (int e : avail[q[i]]) if (k[e] && !S.core.test(dst_[e])) { S.core.set(dst_[e]); q.push_back(dst_[e]); }
  S.core.each([&](int u) {
    for (int e : avail[u]) if (k[e]) {
      if (dst_[e] == u) (single_[e] ? S.loop : S.sloop).set(u);
      else S.succ[u].set(dst_[e]);
    }
  });
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

// Structural change at the core sources of e when its last word is used.
// Rows of State::succ are kept UNMASKED (see State): only bits of core vertices are meaningful.
struct Mod { int u; Bits su; bool lp, sl; };
static inline int child_mods(const State& P, int e, int c, Mod* mods) {
  if (c != 1) return 0;
  int n = 0;
  const int w = dst_[e];
  for (size_t i = 0; i < srcs_[e].size(); i++) {
    const int u = srcs_[e][i];
    if (!P.core.test(u)) continue;
    Mod& m = mods[n++];
    m.u = u; m.su = P.succ[u]; m.lp = P.loop.test(u); m.sl = P.sloop.test(u);
    if (u == w) {
      if (single_[e]) m.lp = false;
      else { bool other = false; for (int g : sloopg[u]) if (g != e && P.cnt[g]) other = true; m.sl = other; }
    } else {
      bool other = false;
      for (int g : sib_[e][i]) if (P.cnt[g]) other = true;
      if (!other) m.su.reset(w);
    }
  }
  return n;
}

// Incremental canonical child of a canonical non-static parent P via group e.
// Same results as solver_v4's gen_child; rows are masked with P.core where v4 relied on masked rows,
// and the two breadth-first searches read P.succ directly: a modified row differs from P.succ[u]
// only by the bit of w, and w is in the visited set from the start, so that bit is discarded anyway.
static void gen_child(const State& P, int e, CI& ci, Scratch& sc) {
  const int v = P.cur, w = dst_[e];
  const int c = P.cnt[e];
  ci.g = (u16)e;
  ci.known = false;
  ci.work = 0;
  if (single_[e] && v == w) {  // single-source loop (count 1 in a canonical state): nothing else changes
    ci.core = P.core; ci.stat = -1;
    ci.h0 = P.h0 ^ Z0[e * 256 + c] ^ Z0[e * 256 + c - 1];
    ci.h1 = P.h1 ^ Z1[e * 256 + c] ^ Z1[e * 256 + c - 1];
    ci.nm = (u8)min(255, (P.succ[v] & P.core).count() + (c - 1 > 0 ? 1 : 0) + (P.sloop.test(v) ? 1 : 0));
    return;
  }
  Mod mods[MAXSRC];
  const int nmods = child_mods(P, e, c, mods);
  auto succOf = [&](int u) -> const Bits& { for (int i = 0; i < nmods; i++) if (mods[i].u == u) return mods[i].su; return P.succ[u]; };
  auto loopOf = [&](int u) -> bool { for (int i = 0; i < nmods; i++) if (mods[i].u == u) return mods[i].lp; return P.loop.test(u); };
  auto sloopOf = [&](int u) -> bool { for (int i = 0; i < nmods; i++) if (mods[i].u == u) return mods[i].sl; return P.sloop.test(u); };
  // Reachability from w in the child graph. If v is reachable, every parent-core
  // vertex is reachable (paths through e can be cut at their last use of e).
  Bits vis; vis.clear(); vis.set(w);
  bool full = v == w;
  if (!full) {
    Bits fr = vis;
    while (fr.any()) {
      Bits nx; nx.clear();
      fr.each([&](int u) { nx |= P.succ[u]; });
      nx &= P.core;
      nx.andnot(vis);
      if (nx.test(v)) { full = true; break; }
      vis |= nx;
      fr = nx;
    }
  }
  const Bits& R = full ? P.core : vis;
  // Only a changed source of e can seed the retrograde cascade: every other core
  // vertex keeps a nonloop successor or a shared loop.
  bool seed = false;
  for (int i = 0; i < nmods; i++)
    if (R.test(mods[i].u) && !(mods[i].su & P.core).any() && !mods[i].sl) seed = true;
  Bits ncore;
  if (!seed) {
    ncore = R;
  } else {
    Bits L; L.clear();
    Bits remInit; remInit.clear();
    sc.q.clear();
    auto lab = [&](int u, int8_t val) { sc.label[u] = val; L.set(u); sc.q.push_back(u); };
    for (int i = 0; i < nmods; i++)
      if (R.test(mods[i].u) && !(mods[i].su & P.core).any() && !mods[i].sl) lab(mods[i].u, mods[i].lp ? 1 : 0);
    for (size_t qi = 0; qi < sc.q.size(); qi++) {
      int t = sc.q[qi];
      int8_t lt = sc.label[t];
      for (int u : preds[t]) {
        if (!R.test(u) || L.test(u)) continue;
        const Bits& su = succOf(u);
        if (!su.test(t)) continue;
        if (lt == 0) lab(u, 1);
        else {
          if (!remInit.test(u)) { sc.rem[u] = (su & P.core).count(); remInit.set(u); }
          if (--sc.rem[u] == 0 && !sloopOf(u)) lab(u, loopOf(u) ? 1 : 0);
        }
      }
    }
    if (L.test(w)) { ci.stat = sc.label[w]; ci.nm = 0; ci.h0 = ci.h1 = 0; ci.core.clear(); return; }
    // core = unknown vertices reachable from w through unknown vertices
    ncore.clear(); ncore.set(w);
    Bits f2 = ncore;
    while (f2.any()) {
      Bits nx; nx.clear();
      f2.each([&](int u) { nx |= P.succ[u]; });
      nx &= P.core;
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
      for (int g : incg[u]) {
        int cc = (g == e) ? c - 1 : P.cnt[g];
        if (cc) { h0 ^= Z0[g * 256 + cc]; h1 ^= Z1[g * 256 + cc]; }
      }
      for (int g : avail[u]) {
        if (!ncore.test(dst_[g])) continue;  // target left the core (done above) or was never in it
        if (single_[g]) {
          // its only source u leaves the core: dropped, counted here once
        } else {
          bool keep = false; int first = -1;
          for (int s : srcs_[g]) { if (ncore.test(s)) keep = true; if (first < 0 && X.test(s)) first = s; }
          if (keep || first != u) continue;
        }
        int cc = (g == e) ? c - 1 : P.cnt[g];
        if (cc) { h0 ^= Z0[g * 256 + cc]; h1 ^= Z1[g * 256 + cc]; }
      }
    });
  }
  ci.h0 = h0; ci.h1 = h1;
  ci.nm = (u8)min(255, (succOf(w) & ncore).count() + (loopOf(w) ? 1 : 0) + (sloopOf(w) ? 1 : 0));
}

// In-place descent: S becomes the canonical child described by ci; U records what to restore.
struct Undo {
  int cur = 0;
  Bits core;
  u64 h0 = 0, h1 = 0;
  int nmods = 0;
  int mu[MAXSRC];
  Bits msucc[MAXSRC];
  bool mlp[MAXSRC], msl[MAXSRC];
  vector<pair<int, u8>> cnt;  // (group, previous count), in the order of change
};

static void apply_child(State& S, const CI& ci, Undo& U) {
  const int e = ci.g, w = dst_[e];
  Mod mods[MAXSRC];
  const int nmods = child_mods(S, e, S.cnt[e], mods);  // from the parent, before any change
  U.cur = S.cur; U.core = S.core; U.h0 = S.h0; U.h1 = S.h1;
  U.cnt.clear();
  U.cnt.push_back({e, S.cnt[e]});
  S.cnt[e]--;
  Bits X = S.core; X.andnot(ci.core);
  X.each([&](int u) {
    for (int g : incg[u]) if (S.cnt[g]) { U.cnt.push_back({g, S.cnt[g]}); S.cnt[g] = 0; }
    for (int g : avail[u]) {
      if (!S.cnt[g]) continue;
      bool keep = false;
      if (!single_[g]) for (int s : srcs_[g]) if (ci.core.test(s)) { keep = true; break; }
      if (!keep) { U.cnt.push_back({g, S.cnt[g]}); S.cnt[g] = 0; }
    }
  });
  U.nmods = nmods;
  for (int i = 0; i < nmods; i++) {
    const int u = mods[i].u;
    U.mu[i] = u; U.msucc[i] = S.succ[u]; U.mlp[i] = S.loop.test(u); U.msl[i] = S.sloop.test(u);
    S.succ[u] = mods[i].su; S.loop.assign(u, mods[i].lp); S.sloop.assign(u, mods[i].sl);
  }
  S.core = ci.core; S.cur = w; S.h0 = ci.h0; S.h1 = ci.h1;
}

static void revert_child(State& S, const Undo& U) {
  for (int i = U.nmods - 1; i >= 0; i--) {
    const int u = U.mu[i];
    S.succ[u] = U.msucc[i]; S.loop.assign(u, U.mlp[i]); S.sloop.assign(u, U.msl[i]);
  }
  for (auto it = U.cnt.rbegin(); it != U.cnt.rend(); ++it) S.cnt[it->first] = it->second;
  S.core = U.core; S.cur = U.cur; S.h0 = U.h0; S.h1 = U.h1;
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
  int proof_format = 3;  // 3: route-proof-v3 (vertex + counts per node), 4: route-proof-v4 (moves only)
  int vloss = 1;
  u64 tt_buckets = 0;
  int init_div = 16;
  double progress = 0;  // seconds between stderr progress lines (0 = off)
  string tt_load, tt_save;
  u64 tt_save_max = 0;  // 0: save every entry; N: save only the N entries with the most work (smaller kept state)
  double checkpoint = 0;  // seconds between TT checkpoints to tt_save (0 = only at the end)
  vector<string> proven_load;
  string proven_save;
  u32 proven_min_work = 1, proven_load_min_work = 1;
  bool proven_save_loaded = false;
  u64 proven_load_max = 0;     // 0: load every record; N: load only the N records with the most work
  double proven_load_fraction = 0;  // > 0: cap = this fraction of the actual table slots (combined with the above)
  bool tt_save_loaded = false;  // also write records that came from --proven-load into --tt-save files
  string replay;                // old v4 certificate to replay before the search
  u64 replay_stuck_nodes = 200000;  // df-pn node budget per stuck state (0: no local search)
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
  for (int g = 0; g < G; g++) { add((u64)srcs_[g].size()); for (int s : srcs_[g]) add((u64)s); add((u64)dst_[g] | (1ull << 40)); }
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
static constexpr u32 PROVEN_BASE = 0x40000000u;  // loaded entries: work = PROVEN_BASE + min(work, PROVEN_BASE - 1)
static u64 tt_save(const string& path, const State& root) {
  const string tmp = path + ".tmp";
  FILE* f = fopen(tmp.c_str(), "wb");
  if (!f) throw runtime_error("cannot create TT file");
  TTHeader h; fill_header(h, root);
  h.created = (u64)time(nullptr);
  bool ok = fwrite(&h, sizeof h, 1, f) == 1;
  u64 ck = 0x5eedc0de, n = 0;
  // --tt-save-max N: keep the N entries with the most work (the costliest results to recompute).
  // Threshold from a histogram of floor(log2(work)); entries in the threshold bucket are taken in
  // table order until N is reached. Loaded values are only hints, so a smaller state is still exact.
  int cut_bucket = -1; u64 cut_room = ~0ull;
  if (opt.tt_save_max) {
    u64 hist[33] = {0};
    for (u64 i = 0; i < tt.nb * 4; i++) {
      u64 D = tt.tab[i].d.load(memory_order_relaxed);
      if (!(D >> 63)) continue;
      u32 w = (u32)D;
      if (!opt.tt_save_loaded && w >= PROVEN_BASE) continue;  // not saved (see below), so not counted
      hist[w ? 32 - __builtin_clz(w) : 0]++;
    }
    u64 acc = 0;
    for (int b = 32; b >= 0; b--) {
      if (acc + hist[b] >= opt.tt_save_max) { cut_bucket = b; cut_room = opt.tt_save_max - acc; break; }
      acc += hist[b];
    }
  }
  vector<u64> buf; buf.reserve(4 * 8192);
  for (u64 i = 0; ok && i < tt.nb * 4; i++) {
    Entry& e = tt.tab[i];
    u64 D = e.d.load(memory_order_relaxed);
    if (!(D >> 63)) continue;
    if (!opt.tt_save_loaded && (u32)D >= PROVEN_BASE) continue;  // shared-cache record: lives in the cache file
    if (cut_bucket >= 0) {
      u32 w = (u32)D;
      int b = w ? 32 - __builtin_clz(w) : 0;
      if (b < cut_bucket) continue;
      if (b == cut_bucket) { if (!cut_room) continue; cut_room--; }
    }
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
  if (ok) ok = fflush(f) == 0 && fsync(fileno(f)) == 0;  // on disk before the rename (2026-11-12)
  if (fclose(f) != 0) ok = false;
  if (!ok) { remove(tmp.c_str()); throw runtime_error("TT file write failure"); }
  if (rename(tmp.c_str(), path.c_str())) { remove(tmp.c_str()); throw runtime_error("TT file rename failure"); }
  return n;
}
static u64 tt_fix_open_capped = 0, tt_fix_proven_in_cache = 0, tt_fix_proven_kept = 0;
static void mark_in_cache(const vector<array<u64, 4>>& amb, vector<char>& in_cache);
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
  vector<array<u64, 4>> amb;  // proven records with work >= PROVEN_BASE: cache or own? decided below
  for (u64 done = 0; done < h.count;) {
    size_t k = (size_t)min<u64>(h.count - done, 8192);
    if (fread(buf.data(), 32, k, f) != k) fail("truncated");
    for (size_t r = 0; r < k; r++) {
      const u64* rec = &buf[4 * r];
      for (int j = 0; j < 4; j++) ck_add(ck, rec[j]);
      int best = (int)((rec[3] >> 32) & 0xFFFF);
      u32 pn = (u32)rec[2], dn = (u32)(rec[2] >> 32), w = (u32)rec[3];
      if (w >= PROVEN_BASE) {
        if (pn != 0 && dn != 0) { w = PROVEN_BASE - 1; tt_fix_open_capped++; }  // open: the job's own top node
        else { amb.push_back({rec[0], rec[1], rec[2], rec[3]}); continue; }
      }
      tt.store(rec[0], rec[1], pn, dn, w, best == 0xFFFF ? -1 : best);
    }
    done += k;
  }
  u64 tail[2]; char end[8];
  if (fread(tail, 8, 2, f) != 2 || fread(end, 8, 1, f) != 1 || memcmp(end, TT_END, 8)) fail("truncated");
  if (tail[0] != h.count || tail[1] != ck) fail("checksum mismatch");
  if (fgetc(f) != EOF) fail("trailing data");
  fclose(f);
  if (!amb.empty()) {
    vector<char> in_cache(amb.size(), 0);
    if (!opt.proven_load.empty()) mark_in_cache(amb, in_cache);
    for (size_t i = 0; i < amb.size(); i++) {
      if (in_cache[i]) { tt_fix_proven_in_cache++; continue; }  // a cache record: the cache load decides
      const u64* rec = amb[i].data();
      int best = (int)((rec[3] >> 32) & 0xFFFF);
      u32 w = (u32)rec[3];
      w = min<u32>(w - PROVEN_BASE, PROVEN_BASE - 1);
      tt.store(rec[0], rec[1], (u32)rec[2], (u32)(rec[2] >> 32), max<u32>(w, 1), best == 0xFFFF ? -1 : best);
      tt_fix_proven_kept++;
    }
  }
  tt.stores = 0; tt.replacements = 0;
  return h.count;
}

// ---------------------------------------------------------------- proven-state cache (--proven-save / --proven-load)
// File: PCHeader, then count records of 24 bytes {k0, k1, work (u32), best (u16), result (u8: 1 = W for the
// player to move, 0 = L), 0 (u8)}, then {count, checksum} and an end marker. Bound to the game graph only.
static const char PC_MAGIC[8] = {'Y', 'S', 'P', 'C', '1', 0, 0, 0};
static const char PC_END[8] = {'Y', 'S', 'P', 'C', 'E', 'N', 'D', 0};
struct PCHeader {
  char magic[8];
  u64 graph0, graph1;
  u32 min_work, reserved;
  u64 count, created;
};
struct PCRec { u64 k0, k1; u32 work; u16 best; u8 win, pad; };
static_assert(sizeof(PCRec) == 24, "PCRec layout");
// Which records proven_load() inserts from one cache file: those with work >= --proven-load-min-work and, with
// --proven-load-max N, at most the N with the most work (a threshold on floor(log2(work)); records in the
// threshold bucket are taken in file order). proven_load() and mark_in_cache() both use this, so they agree
// record by record (2026-11-07).
struct PCSelect {
  int cut_bucket = -1;
  u64 cut_room = ~0ull;
  bool init(const string& path) {  // false: the file cannot be read (proven_load then reports the error)
    cut_bucket = -1; cut_room = ~0ull;
    if (!opt.proven_load_max) return true;
    FILE* g = fopen(path.c_str(), "rb");
    if (!g) return false;
    PCHeader hh;
    if (fread(&hh, sizeof hh, 1, g) != 1) { fclose(g); return false; }
    u64 hist[33] = {0};
    vector<PCRec> b2(8192);
    for (u64 done = 0; done < hh.count;) {
      size_t k = (size_t)min<u64>(hh.count - done, 8192);
      if (fread(b2.data(), sizeof(PCRec), k, g) != k) { fclose(g); return false; }
      for (size_t r = 0; r < k; r++) if (b2[r].work >= opt.proven_load_min_work) { u32 w = b2[r].work; hist[w ? 32 - __builtin_clz(w) : 0]++; }
      done += k;
    }
    fclose(g);
    u64 acc = 0;
    for (int b = 32; b >= 0; b--) {
      if (acc + hist[b] >= opt.proven_load_max) { cut_bucket = b; cut_room = opt.proven_load_max - acc; break; }
      acc += hist[b];
    }
    return true;
  }
  bool take(const PCRec& x) {  // call once per record, in file order
    if (x.work < opt.proven_load_min_work) return false;
    if (cut_bucket >= 0) {
      int b = x.work ? 32 - __builtin_clz(x.work) : 0;
      if (b < cut_bucket) return false;
      if (b == cut_bucket) { if (!cut_room) return false; cut_room--; }
    }
    return true;
  }
};
// tt_load helper: which of the ambiguous records (proven, work >= PROVEN_BASE) proven_load() will ACTUALLY insert
// this run (same file, same k0 and k1, and selected by the same cap). A record that is in a cache file but
// beyond the cap is not marked, so tt_load keeps it as the job's own instead of losing it for this run.
// Only the header is checked here; proven_load checks each file fully afterwards.
static void mark_in_cache(const vector<array<u64, 4>>& amb, vector<char>& in_cache) {
  vector<u32> idx(amb.size());
  for (size_t i = 0; i < idx.size(); i++) idx[i] = (u32)i;
  // amb holds saved records {k0, k1, C, D} (tt_save writes k0 = A ^ C ^ D and k1 = B)
  auto k0of = [&](u32 i) { return amb[i][0]; };
  sort(idx.begin(), idx.end(), [&](u32 a, u32 b) { return amb[a][1] != amb[b][1] ? amb[a][1] < amb[b][1] : k0of(a) < k0of(b); });
  PCHeader want; memset(&want, 0, sizeof want);
  graph_fingerprint(want.graph0, want.graph1);
  for (auto& pth : opt.proven_load) {
    FILE* g = fopen(pth.c_str(), "rb");
    if (!g) continue;
    PCHeader hh;
    if (fread(&hh, sizeof hh, 1, g) != 1 || memcmp(hh.magic, PC_MAGIC, 8) || hh.graph0 != want.graph0 || hh.graph1 != want.graph1) { fclose(g); continue; }
    PCSelect sel;
    if (!sel.init(pth)) { fclose(g); continue; }
    vector<PCRec> b2(8192);
    bool bad = false;
    for (u64 done = 0; done < hh.count && !bad;) {
      size_t k = (size_t)min<u64>(hh.count - done, 8192);
      if (fread(b2.data(), sizeof(PCRec), k, g) != k) break;
      for (size_t r = 0; r < k; r++) {
        const PCRec& x = b2[r];
        if (x.win > 1 || x.pad) { bad = true; break; }  // proven_load refuses the file later
        if (!sel.take(x)) continue;                     // not inserted this run: not "in the cache"
        auto it = lower_bound(idx.begin(), idx.end(), x, [&](u32 a, const PCRec& y) {
          return amb[a][1] != y.k1 ? amb[a][1] < y.k1 : k0of(a) < y.k0; });
        for (; it != idx.end() && amb[*it][1] == x.k1 && k0of(*it) == x.k0; ++it) in_cache[*it] = 1;
      }
      done += k;
    }
    fclose(g);
  }
}
static u64 proven_save(const string& path, u64& skipped_small, u64& skipped_loaded) {
  const string tmp = path + ".tmp";
  FILE* f = fopen(tmp.c_str(), "wb");
  if (!f) throw runtime_error("cannot create proven file");
  PCHeader h; memset(&h, 0, sizeof h);
  memcpy(h.magic, PC_MAGIC, 8);
  graph_fingerprint(h.graph0, h.graph1);
  h.min_work = opt.proven_min_work;
  h.created = (u64)time(nullptr);
  bool ok = fwrite(&h, sizeof h, 1, f) == 1;
  u64 ck = 0x5eedcac4e, n = 0;
  skipped_small = skipped_loaded = 0;
  vector<PCRec> buf; buf.reserve(8192);
  auto flush = [&]() { if (ok && !buf.empty()) ok = fwrite(buf.data(), sizeof(PCRec), buf.size(), f) == buf.size(); buf.clear(); };
  for (u64 i = 0; ok && i < tt.nb * 4; i++) {
    Entry& e = tt.tab[i];
    u64 D = e.d.load(memory_order_relaxed);
    if (!(D >> 63)) continue;
    u64 B = e.b.load(memory_order_relaxed), A = e.a.load(memory_order_relaxed), C = e.c.load(memory_order_relaxed);
    u32 pn = (u32)C, dn = (u32)(C >> 32);
    if (pn != 0 && dn != 0) continue;
    u32 work = (u32)D;
    if (work >= PROVEN_BASE) {
      if (!opt.proven_save_loaded) { skipped_loaded++; continue; }
      work -= PROVEN_BASE;
    }
    if (work < opt.proven_min_work) { skipped_small++; continue; }
    PCRec r; memset(&r, 0, sizeof r);
    r.k0 = A ^ C ^ D; r.k1 = B; r.work = work; r.best = (u16)((D >> 32) & 0xFFFF); r.win = pn == 0 ? 1 : 0;
    ck_add(ck, r.k0); ck_add(ck, r.k1); ck_add(ck, (u64)r.work | ((u64)r.best << 32) | ((u64)r.win << 48));
    buf.push_back(r); n++;
    if (buf.size() == buf.capacity()) flush();
  }
  flush();
  u64 tail[2] = {n, ck};
  if (ok) ok = fwrite(tail, 8, 2, f) == 2 && fwrite(PC_END, 8, 1, f) == 1;
  if (ok) { h.count = n; ok = fseek(f, 0, SEEK_SET) == 0 && fwrite(&h, sizeof h, 1, f) == 1; }
  if (fclose(f) != 0) ok = false;
  if (!ok) { remove(tmp.c_str()); throw runtime_error("proven file write failure"); }
  if (rename(tmp.c_str(), path.c_str())) { remove(tmp.c_str()); throw runtime_error("proven file rename failure"); }
  return n;
}
static u64 proven_load(const string& path, u64& inserted) {
  // With --proven-load-max N, a first pass over the file finds the work threshold so that at most N records
  // (those with the most work) are inserted; the shared cache then takes at most N table slots (PCSelect).
  PCSelect sel;
  if (!sel.init(path)) throw runtime_error("proven file refused (" + path + "): cannot be read or truncated");
  FILE* f = fopen(path.c_str(), "rb");
  if (!f) throw runtime_error("cannot open proven file " + path);
  PCHeader h, want; memset(&want, 0, sizeof want);
  graph_fingerprint(want.graph0, want.graph1);
  auto fail = [&](const string& why) { fclose(f); throw runtime_error("proven file refused (" + path + "): " + why); };
  if (fread(&h, sizeof h, 1, f) != 1 || memcmp(h.magic, PC_MAGIC, 8)) fail("not a proven-cache file");
  if (h.graph0 != want.graph0 || h.graph1 != want.graph1) fail("different game graph (groups, endpoints or hash keys)");
  u64 ck = 0x5eedcac4e;
  vector<PCRec> buf(8192);
  for (u64 done = 0; done < h.count;) {
    size_t k = (size_t)min<u64>(h.count - done, 8192);
    if (fread(buf.data(), sizeof(PCRec), k, f) != k) fail("truncated");
    for (size_t r = 0; r < k; r++) {
      const PCRec& x = buf[r];
      if (x.win > 1 || x.pad) fail("bad record");
      ck_add(ck, x.k0); ck_add(ck, x.k1); ck_add(ck, (u64)x.work | ((u64)x.best << 32) | ((u64)x.win << 48));
      if (!sel.take(x)) continue;
      inserted++;
      u32 w = PROVEN_BASE + min<u32>(x.work, PROVEN_BASE - 1);
      int best = x.best == 0xFFFF ? -1 : (int)x.best;
      if (x.win) tt.store(x.k0, x.k1, 0, INF, w, best);
      else tt.store(x.k0, x.k1, INF, 0, w, best);
    }
    done += k;
  }
  u64 tail[2]; char end[8];
  if (fread(tail, 8, 2, f) != 2 || fread(end, 8, 1, f) != 1 || memcmp(end, PC_END, 8)) fail("truncated");
  if (tail[0] != h.count || tail[1] != ck) fail("checksum mismatch");
  if (fgetc(f) != EOF) fail("trailing data");
  fclose(f);
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
  State S;            // the current search state, changed in place
  vector<Undo> undo;  // undo[d]: how to return from depth d+1 to depth d
  vector<vector<CI>> fr;
  Scratch sc;
  u64 mid_calls = 0, gens = 0;
  u64 rng = 0;
  void init(int maxdepth, int tid) {
    id = tid;
    S.init();
    undo.resize(maxdepth + 2);
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
    if (T.core != S.core || T.loop != (S.loop & S.core) || T.sloop != (S.sloop & S.core) || T.h0 != S.h0 || T.h1 != S.h1) throw runtime_error("selfcheck: materialize mismatch");
    S.core.each([&](int u) { if (T.succ[u] != (S.succ[u] & S.core)) throw runtime_error("selfcheck: succ mismatch"); });
    vector<u8> k = S.cnt;
    if (ref_canon(S.cur, k, false) != -1 || k != S.cnt) throw runtime_error("selfcheck: state not canonical");
  }

  // Returns node pn/dn; accumulates work.
  void mid(int d, u32 pth, u32 dth, u32& rpn, u32& rdn, u64& rwork) {
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
    for (int g : avail[S.cur]) {
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
      apply_child(S, c, undo[d]);
      if (opt.selfcheck) selfcheck_state(S);
      u32 cp, cd; u64 cw;
      mid(d + 1, cpth, cdth, cp, cd, cw);
      revert_child(S, undo[d]);
      c.pn = cp; c.dn = cd; c.known = true; c.work = (u32)min<u64>(cw, 0xFFFFFFFFull);
      work += cw;
    }
    if (multi) mybusy->fetch_sub(1, memory_order_relaxed);
    // own work stays below PROVEN_BASE, so it is never mistaken for a shared-cache record (2026-11-06)
    tt.store(S.h0, S.h1, pn, dn, (u32)min<u64>(work + prevwork, (u64)PROVEN_BASE - 1), bestg);
    rpn = pn; rdn = dn; rwork = work;
  }
};

// ---------------------------------------------------------------- strategy replay (--replay)
// The old certificate: results and moves only (v4 has no states). Lines are the solver's compact form.
struct OldProof {
  vector<u8> win;   // 1 = W for the player to move
  vector<u64> off;  // moves of node i: mv[2*off[i] .. 2*off[i+1])
  vector<u32> mv;   // group, child id
  void load(const string& path) {
    gzFile f = gzopen(path.c_str(), "rb");  // reads gzip and plain files
    if (!f) throw runtime_error("cannot open replay certificate " + path);
    string pending;
    vector<char> buf(1 << 20);
    bool header = true;
    off.assign(1, 0);
    auto line = [&](const char* p, const char* e) {
      if (e > p && e[-1] == '\r') e--;
      string ln(p, e);
      if (header) {
        if (ln.find("\"format\":\"route-proof-v4\"") == string::npos) throw runtime_error("replay certificate is not route-proof-v4");
        if (ln.find("\"groups\":" + to_string(G) + ",") == string::npos || ln.find("\"vertices\":" + to_string(N) + ",") == string::npos)
          throw runtime_error("replay certificate belongs to another dictionary (groups/vertices differ)");
        header = false;
        return;
      }
      const string want = "{\"id\":" + to_string(win.size()) + ",\"r\":\"";
      if (ln.compare(0, want.size(), want) != 0 || ln.size() < want.size() + 8) throw runtime_error("replay certificate: unexpected node line");
      char r = ln[want.size()];
      if (r != 'W' && r != 'L') throw runtime_error("replay certificate: unexpected result");
      size_t m = ln.find("\"m\":[", want.size());
      if (m == string::npos || ln.find("\"k\"") != string::npos) throw runtime_error("replay certificate: unsupported node line");
      u64 x = 0; bool in = false; size_t cnt = 0;
      for (size_t i = m + 5; i < ln.size(); i++) {
        char c = ln[i];
        if (c >= '0' && c <= '9') { x = x * 10 + (u64)(c - '0'); in = true; }
        else if (in) { mv.push_back((u32)x); cnt++; x = 0; in = false; }
      }
      if (cnt & 1) throw runtime_error("replay certificate: odd move list");
      for (size_t i = mv.size() - cnt; i < mv.size(); i += 2)
        if (mv[i] >= (u32)G || mv[i + 1] >= win.size()) throw runtime_error("replay certificate: move out of range");
      win.push_back(r == 'W');
      off.push_back(mv.size() / 2);
    };
    for (;;) {
      int n = gzread(f, buf.data(), (unsigned)buf.size());
      if (n < 0) { gzclose(f); throw runtime_error("replay certificate: read error"); }
      if (n == 0) break;
      pending.append(buf.data(), (size_t)n);
      size_t start = 0, nl;
      while ((nl = pending.find('\n', start)) != string::npos) { line(pending.data() + start, pending.data() + nl); start = nl + 1; }
      pending.erase(0, start);
    }
    gzclose(f);
    if (!pending.empty()) line(pending.data(), pending.data() + pending.size());
    if (win.empty()) throw runtime_error("replay certificate has no nodes");
  }
};

struct KeyHash128 { size_t operator()(const pair<u64, u64>& k) const { return (size_t)(k.first ^ (k.second * 0x9E3779B97F4A7C15ull)); } };

struct Replayer {
  Searcher* S = nullptr;
  const OldProof* op = nullptr;
  vector<vector<CI>> rfr;                                // children per depth (the searcher's own lists are used by mid)
  unordered_set<pair<u64, u64>, KeyHash128> seen;        // new states handled without a proof, by their own key
  u64 nodes = 0, proven = 0, memo_proven = 0, memo_unknown = 0;
  u64 stuck_old_leaf = 0, stuck_witness_gone = 0, stuck_witness_static = 0, stuck_witness_refuted = 0, stuck_new_move = 0;
  u64 unknown_below = 0, flips = 0, local_calls = 0, local_solved = 0, local_mid = 0;
  bool expired = false;

  bool out_of_time() {
    if (!expired && (nodes & 255) == 0 &&
        chrono::duration<double>(chrono::steady_clock::now() - t_start).count() >= opt.seconds) expired = true;
    return expired;
  }
  // One budgeted df-pn search of the state the searcher is in (depth d). 1 / 0 = proven, -1 = not solved.
  int local(int d) {
    if (!opt.replay_stuck_nodes || expired) return -1;
    local_calls++;
    const u64 keep_max = opt.max_mid, before = S->mid_calls;
    opt.max_mid = min(keep_max, g_mid.load() + max<u64>(opt.replay_stuck_nodes, 1024));
    stop_flag = false;
    u32 rp = 1, rd = 1; u64 rw = 0;
    S->mid(d, INF, INF, rp, rd, rw);
    local_mid += S->mid_calls - before;
    opt.max_mid = keep_max;
    if (stop_flag.load()) {
      lock_guard<mutex> l(reason_mu);
      if (stop_reason == "node_limit" && g_mid.load() < keep_max) { stop_reason = "none"; stop_flag = false; }  // only the local budget
      else expired = true;                                                                                      // the run's own limit
    }
    if (rp == 0) { local_solved++; return 1; }
    if (rd == 0) { local_solved++; return 0; }
    return -1;
  }
  // Value of the canonical non-static state the searcher is in, guided by old node `oid`.
  int run(int d, u32 oid, u64& work) {
    State& st = S->S;
    work = 1;
    { u32 p, q, w; int b;
      if (tt.probe(st.h0, st.h1, p, q, w, b) && (p == 0 || q == 0)) { memo_proven++; return p == 0 ? 1 : 0; } }
    if (!seen.insert({st.h0, st.h1}).second) { memo_unknown++; return -1; }
    nodes++;
    if (out_of_time()) return -1;
    vector<CI>& ch = rfr[d];
    ch.clear();
    for (int g : avail[st.cur]) {
      if (!st.cnt[g]) continue;
      ch.emplace_back();
      gen_child(st, g, ch.back(), S->sc);
      if (opt.selfcheck) S->selfcheck_child(st, ch.back());
      if (ch.back().stat == 0) {  // a move to a statically lost state: W, whatever the old node says
        tt.store(st.h0, st.h1, 0, INF, 1, g);
        proven++;
        return 1;
      }
    }
    if (ch.empty()) throw runtime_error("replay: non-static state without moves");
    const u64 lo = op->off[oid], hi = op->off[oid + 1];
    auto descend = [&](size_t i, long long cid, u64& cw) -> int {  // value of child i for ITS mover
      const CI ci = ch[i];
      apply_child(st, ci, S->undo[d]);
      if (opt.selfcheck) S->selfcheck_state(st);
      int r;
      if (cid >= 0) r = run(d + 1, (u32)cid, cw);
      else {  // no old node for this move: table first, then a local search
        u32 p, q, w; int b;
        cw = 1;
        if (tt.probe(st.h0, st.h1, p, q, w, b) && (p == 0 || q == 0)) r = p == 0 ? 1 : 0;
        else r = local(d + 1);
      }
      revert_child(st, S->undo[d]);
      return r;
    };
    if (lo == hi) { stuck_old_leaf++; return local(d); }  // the old state was static, this one is not
    if (op->win[oid]) {
      const int g0 = (int)op->mv[2 * lo];
      size_t wi = ch.size();
      for (size_t i = 0; i < ch.size(); i++) if (ch[i].g == g0) wi = i;
      if (wi == ch.size()) { stuck_witness_gone++; return local(d); }
      if (ch[wi].stat == 1) { stuck_witness_static++; return local(d); }
      u64 cw = 0;
      int r = descend(wi, (long long)op->mv[2 * lo + 1], cw);
      work += cw;
      if (r == 0) {
        tt.store(st.h0, st.h1, 0, INF, (u32)min<u64>(work, (u64)PROVEN_BASE - 1), g0);
        proven++;
        return 1;
      }
      if (r == 1) { stuck_witness_refuted++; return local(d); }
      unknown_below++;  // the stuck state is deeper and had its own search; the normal search goes on from the table
      return -1;
    }
    // old node L: EVERY legal move of the NEW state must lead to a state proven W
    bool all = true;
    u64 k = lo;
    for (size_t i = 0; i < ch.size(); i++) {
      if (ch[i].stat == 1) continue;
      const int g = ch[i].g;
      while (k < hi && (int)op->mv[2 * k] < g) k++;  // both lists are in ascending group order
      long long cid = -1;
      if (k < hi && (int)op->mv[2 * k] == g) cid = (long long)op->mv[2 * k + 1];
      else for (u64 j = lo; j < hi; j++) if ((int)op->mv[2 * j] == g) { cid = (long long)op->mv[2 * j + 1]; break; }  // unsorted file
      if (cid < 0) stuck_new_move++;
      u64 cw = 0;
      int r = descend(i, cid, cw);
      work += cw;
      if (r == 0) {  // this move wins in the new position: the node is W now
        tt.store(st.h0, st.h1, 0, INF, (u32)min<u64>(work, (u64)PROVEN_BASE - 1), g);
        proven++; flips++;
        return 1;
      }
      if (r != 1) all = false;
    }
    if (all) {
      tt.store(st.h0, st.h1, INF, 0, (u32)min<u64>(work, (u64)PROVEN_BASE - 1), -1);
      proven++;
      return 0;
    }
    unknown_below++;
    return -1;
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
    line += "{\"id\":"; line += to_string(count);
    if (opt.proof_format == 3) {
      line += ",\"v\":"; line += to_string(v); line += ",\"c\":\"";
      for (int g = 0; g < G; g++) { line += hx[k[g] >> 4]; line += hx[k[g] & 15]; }
      line += '"';
    }
    line += ",\"r\":\""; line += win ? 'W' : 'L'; line += "\",\"m\":[";
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
    S->S = es[d];  // whole state (solver_v4 copied every field but sloop)
    for (;;) {
      u32 rp, rd; u64 rw;
      if (emit_expired()) throw runtime_error("emission time limit while re-solving an evicted node");
      u64 before = S->mid_calls;
      stop_flag = false;
      S->mid(0, INF, INF, rp, rd, rw);
      resolve_mid += S->mid_calls - before;
      if (rp == 0 || rd == 0) {
        // the TT may have evicted the root right away; store again
        tt.store(es[d].h0, es[d].h1, rp, rd, (u32)min<u64>(rw, (u64)PROVEN_BASE - 1), -1);
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
    for (int g : avail[E.cur]) if (E.cnt[g]) { ch.emplace_back(); gen_child(E, g, ch.back(), S->sc); }
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
    if (argc < 2) throw runtime_error("usage: solver_v3 INPUT [--seconds S] [--nodes MAXMID] [--proof OUT[.gz]] [--proof-format v3|v4] [--tt-mb MB] [--threads T] [--eps E] [--init 0|1|2] [--wpn 0|1] [--selfcheck 0|1] [--emit-seconds S] [--tt-load FILE] [--tt-save FILE] [--tt-save-max N] [--checkpoint-seconds S] [--proven-load FILE]... [--proven-load-max N] [--proven-load-fraction F] [--proven-save FILE] [--tt-save-loaded 0|1] [--proven-min-work W] [--proven-save-loaded 0|1] [--replay OLD_V4_PROOF] [--replay-stuck-nodes N]");
    for (int i = 2; i < argc; i++) {
      string x = argv[i];
      if (i + 1 >= argc) throw runtime_error("missing option value");
      string v = argv[++i];
      if (x == "--seconds") opt.seconds = stod(v);
      else if (x == "--nodes") opt.max_mid = stoull(v);
      else if (x == "--proof") opt.proof = v;
      else if (x == "--proof-format") { if (v == "v3" || v == "3") opt.proof_format = 3; else if (v == "v4" || v == "4") opt.proof_format = 4; else throw runtime_error("--proof-format must be v3 or v4"); }
      else if (x == "--tt-mb") opt.tt_mb = stoull(v);
      else if (x == "--threads") opt.threads = stoi(v);
      else if (x == "--eps") opt.eps = stod(v);
      else if (x == "--init") opt.init = stoi(v);
      else if (x == "--wpn") opt.wpn = stoi(v);
      else if (x == "--selfcheck") opt.selfcheck = stoi(v) != 0;
      else if (x == "--emit-seconds") opt.emit_seconds = stod(v);
      else if (x == "--vloss") opt.vloss = stoi(v);
      else if (x == "--tt-buckets") opt.tt_buckets = stoull(v);
      else if (x == "--tt-save-max") opt.tt_save_max = stoull(v);
      else if (x == "--progress") opt.progress = stod(v);
      else if (x == "--init-div") opt.init_div = max(1, stoi(v));
      else if (x == "--tt-load") opt.tt_load = v;
      else if (x == "--tt-save") opt.tt_save = v;
      else if (x == "--checkpoint-seconds") opt.checkpoint = stod(v);
      else if (x == "--proven-load") opt.proven_load.push_back(v);
      else if (x == "--proven-save") opt.proven_save = v;
      else if (x == "--proven-min-work") opt.proven_min_work = (u32)max(1ull, min(stoull(v), (unsigned long long)PROVEN_BASE - 1));
      else if (x == "--proven-load-min-work") opt.proven_load_min_work = (u32)max(1ull, min(stoull(v), (unsigned long long)PROVEN_BASE - 1));
      else if (x == "--proven-save-loaded") opt.proven_save_loaded = stoi(v) != 0;
      else if (x == "--proven-load-max") opt.proven_load_max = stoull(v);
      else if (x == "--proven-load-fraction") opt.proven_load_fraction = stod(v);
      else if (x == "--tt-save-loaded") opt.tt_save_loaded = stoi(v) != 0;
      else if (x == "--replay") opt.replay = v;
      else if (x == "--replay-stuck-nodes") opt.replay_stuck_nodes = stoull(v);
      else throw runtime_error("unknown option: " + x);
    }
    if (!isfinite(opt.seconds) || opt.seconds < 0 || opt.threads < 1 || opt.threads > 64 || opt.tt_mb < 1 || opt.eps < 0 ||
        !isfinite(opt.checkpoint) || opt.checkpoint < 0 || (opt.checkpoint > 0 && opt.tt_save.empty()))
      throw runtime_error("invalid option value");
    read_input(argv[1]);
    tt.alloc(opt.tt_mb, opt.tt_buckets);
    if (!(opt.proven_load_fraction >= 0 && opt.proven_load_fraction <= 1)) throw runtime_error("--proven-load-fraction must be in [0, 1]");
    if (opt.proven_load_fraction > 0) {
      u64 n = (u64)(opt.proven_load_fraction * (double)(tt.nb * 4));
      opt.proven_load_max = opt.proven_load_max ? min(opt.proven_load_max, max<u64>(n, 1)) : max<u64>(n, 1);
    }
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
    u64 pc_loaded = 0, pc_inserted = 0, pc_saved = 0, pc_skip_small = 0, pc_skip_loaded = 0, pc_used_after_load = 0;
    double pc_load_s = 0, pc_save_s = 0;
    string pc_save_error;
    if (!opt.proven_load.empty()) {
      auto t0 = chrono::steady_clock::now();
      for (auto& pth : opt.proven_load) pc_loaded += proven_load(pth, pc_inserted);
      pc_used_after_load = tt.used();
      tt.stores = 0; tt.replacements = 0;
      pc_load_s = chrono::duration<double>(chrono::steady_clock::now() - t0).count();
    }
    auto save_now = [&]() {
      auto t0 = chrono::steady_clock::now();
      try { tt_saved = tt_save(opt.tt_save, root); tt_saves++; } catch (const exception& e) { tt_save_error = e.what(); }
      tt_save_s += chrono::duration<double>(chrono::steady_clock::now() - t0).count();
    };
    OldProof oldproof;
    double replay_load_s = 0, replay_s = 0;
    int replay_root = -2;  // -2: no replay, -1: root not proven by replay, 0 / 1: proven L / W
    Replayer rp_;
    if (!opt.replay.empty()) {
      auto t0 = chrono::steady_clock::now();
      oldproof.load(opt.replay);
      replay_load_s = chrono::duration<double>(chrono::steady_clock::now() - t0).count();
    }
    if (opt.checkpoint > 0) next_ckpt = opt.checkpoint;
    t_start = chrono::steady_clock::now();
    vector<Searcher> ss(opt.threads);
    for (int i = 0; i < opt.threads; i++) ss[i].init(maxdepth, i);
    u32 rpn = rstat == -1 ? 1 : (rstat ? 0 : INF), rdn = rstat == -1 ? 1 : (rstat ? INF : 0);
    bool root_solved = false;
    if (!opt.replay.empty() && rstat == -1) {
      // replay phase (one thread; its time is part of --seconds). No checkpoints meanwhile: the table is saved
      // by the first checkpoint of the search, or at the end.
      const double keep_ckpt = next_ckpt;
      next_ckpt = 1e300;
      rp_.S = &ss[0]; rp_.op = &oldproof;
      rp_.rfr.resize(maxdepth + 2);
      ss[0].S = root;
      u64 w = 0;
      replay_root = rp_.run(0, (u32)oldproof.win.size() - 1, w);
      replay_s = chrono::duration<double>(chrono::steady_clock::now() - t_start).count();
      if (keep_ckpt < 1e299) next_ckpt = replay_s + opt.checkpoint;
      if (!rp_.expired) stop_flag = false;
    }
    if (rstat == -1) {
      auto run = [&](int i) {
        Searcher& s = ss[i];
        s.S = root;
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
    // The final state is saved whether or not the root is solved (2026-11-12, Fable review). A solved root used
    // to be left at its last checkpoint; if the certificate then could not be written or was not accepted, the
    // search since that checkpoint was gone. With the solved state on disk the next run has the result at once.
    // The runner deletes the file only after the certificate is accepted (solve_common.release_state).
    if (!opt.tt_save.empty() && rstat == -1) save_now();
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
      next_ckpt = 1e300;  // no checkpoints while the certificate is written: the timer used to interrupt every re-solve after 1,024 nodes
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
      string head = string("{\"format\":\"route-proof-v") + (opt.proof_format == 4 ? "4" : "3") + "\",\"groups\":" + to_string(G) + ",\"vertices\":" + to_string(N) + ",\"root\":" + to_string(rid) + "}\n";
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
    if (!opt.proven_save.empty()) {
      auto t0 = chrono::steady_clock::now();
      try { pc_saved = proven_save(opt.proven_save, pc_skip_small, pc_skip_loaded); } catch (const exception& e) { pc_save_error = e.what(); }
      pc_save_s = chrono::duration<double>(chrono::steady_clock::now() - t0).count();
    }
    u64 used = tt.used();
    if (!opt.proven_load.empty() || !opt.proven_save.empty())
      fprintf(stderr, "{\"proven_loaded\":%llu,\"proven_inserted\":%llu,\"proven_tt_used_after_load\":%llu,\"proven_load_seconds\":%s,\"proven_saved\":%llu,"
              "\"proven_skipped_small\":%llu,\"proven_skipped_loaded\":%llu,\"proven_save_seconds\":%s,\"proven_save_error\":\"%s\"}\n",
              (unsigned long long)pc_loaded, (unsigned long long)pc_inserted, (unsigned long long)pc_used_after_load, jnum(pc_load_s).c_str(), (unsigned long long)pc_saved,
              (unsigned long long)pc_skip_small, (unsigned long long)pc_skip_loaded, jnum(pc_save_s).c_str(), pc_save_error.c_str());
    printf("{\"result\":\"%s\",\"reason\":\"%s\",\"mid_calls\":%llu,\"child_gens\":%llu,\"tt_entries\":%llu,\"tt_capacity\":%llu,\"tt_mb\":%zu,"
           "\"tt_stores\":%llu,\"tt_replacements\":%llu,\"seconds\":%s,\"pn\":%u,\"dn\":%u,\"best_group\":%d,\"threads\":%d,"
           "\"eps\":%g,\"init\":%d,\"wpn\":%d,\"proof_nodes\":%llu,\"emit_resolves\":%llu,\"emit_resolve_mid\":%llu,"
           "\"emit_crosschecks\":%llu,\"emit_seconds\":%s,\"selfchecks\":%llu,\"proof_error\":\"%s\","
           "\"tt_loaded\":%llu,\"tt_load_seconds\":%s,\"tt_saves\":%llu,\"tt_saved\":%llu,\"tt_save_seconds\":%s,"
           "\"tt_save_error\":\"%s\",\"tt_load_open_capped\":%llu,\"tt_load_proven_in_cache\":%llu,\"tt_load_proven_kept\":%llu,"
           "\"proven_load_cap\":%llu,"
           "\"replay_root\":%d,\"replay_old_nodes\":%llu,\"replay_load_seconds\":%s,\"replay_seconds\":%s,\"replay_nodes\":%llu,"
           "\"replay_proven\":%llu,\"replay_memo_proven\":%llu,\"replay_memo_unknown\":%llu,\"replay_stuck_old_leaf\":%llu,"
           "\"replay_stuck_witness_gone\":%llu,\"replay_stuck_witness_static\":%llu,\"replay_stuck_witness_refuted\":%llu,"
           "\"replay_stuck_new_move\":%llu,\"replay_unknown_below\":%llu,\"replay_flips\":%llu,\"replay_local_calls\":%llu,"
           "\"replay_local_solved\":%llu,\"replay_local_mid\":%llu}\n",
           result.c_str(), stop_reason.c_str(), (unsigned long long)mid_total, (unsigned long long)gen_total,
           (unsigned long long)used, (unsigned long long)(tt.nb * 4), (size_t)(tt.bytes >> 20),
           (unsigned long long)tt.stores.load(), (unsigned long long)tt.replacements.load(), jnum(elapsed).c_str(), rpn, rdn, bestg,
           (int)ss.size(), opt.eps, opt.init, opt.wpn, (unsigned long long)proof_nodes, (unsigned long long)resolves,
           (unsigned long long)resolve_mid, (unsigned long long)crosschecks, jnum(emit_s).c_str(),
           (unsigned long long)g_selfchecks.load(), proof_error.c_str(), (unsigned long long)tt_loaded, jnum(tt_load_s).c_str(),
           (unsigned long long)tt_saves, (unsigned long long)tt_saved, jnum(tt_save_s).c_str(), tt_save_error.c_str(),
           (unsigned long long)tt_fix_open_capped, (unsigned long long)tt_fix_proven_in_cache, (unsigned long long)tt_fix_proven_kept,
           (unsigned long long)opt.proven_load_max,
           replay_root, (unsigned long long)oldproof.win.size(), jnum(replay_load_s).c_str(), jnum(replay_s).c_str(),
           (unsigned long long)rp_.nodes, (unsigned long long)rp_.proven, (unsigned long long)rp_.memo_proven,
           (unsigned long long)rp_.memo_unknown, (unsigned long long)rp_.stuck_old_leaf, (unsigned long long)rp_.stuck_witness_gone,
           (unsigned long long)rp_.stuck_witness_static, (unsigned long long)rp_.stuck_witness_refuted,
           (unsigned long long)rp_.stuck_new_move, (unsigned long long)rp_.unknown_below, (unsigned long long)rp_.flips,
           (unsigned long long)rp_.local_calls, (unsigned long long)rp_.local_solved, (unsigned long long)rp_.local_mid);
    return !proof_error.empty() ? 3 : !tt_save_error.empty() ? 4 : !pc_save_error.empty() ? 5 : 0;
  } catch (const exception& e) {
    fprintf(stderr, "solver error: %s\n", e.what());
    return 2;
  }
}
