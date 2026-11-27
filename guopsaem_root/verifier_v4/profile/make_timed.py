#!/usr/bin/env python3
"""Make verify_v4_timed.cpp, a PROFILING copy of ../verify_v4.cpp with time counters around its parts.

usage: make_timed.py            (run in this folder; writes verify_v4_timed.cpp)
       g++ -O2 -std=c++17 -o verify_v4_timed verify_v4_timed.cpp -lz
       verify_v4_timed <same arguments as verify_v4> 2> profile.json

The copy runs the same checks (the checking lines are untouched) and prints the normal result; one more JSON
line on stderr says how many seconds each part took. It is for measuring only: certificates are accepted with
verify_v4, never with this copy. Every edit below must find its place exactly once, so the script fails if
verify_v4.cpp changes in a part it touches.
Environment knobs of the copy, to try other settings of the state store without touching the verifier:
  VPROF_LEVEL (zlib level, default 6), VPROF_MEMLEVEL (default 4), VPROF_STRATEGY (0 default, 1 filtered,
  2 huffman only, 3 RLE = default, 4 fixed). The settings before 2026-11-12 were 6 / 9 / 0.
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
src = (HERE.parent / 'verify_v4.cpp').read_text(encoding='utf-8')
s = src


def rep(a, b):
    global s
    assert s.count(a) == 1, (a[:70], s.count(a))
    s = s.replace(a, b)


rep("""// verify_v4.cpp - independent route-proof-v4 checker (C++17, zlib).
""", """// verify_v4_timed.cpp - PROFILING COPY of verify_v4.cpp. NOT a verifier to accept certificates with.
// It is verify_v4.cpp with time counters around its parts; the checks are the same lines. The counters are
// printed as one JSON line on stderr after the normal output. Made by profile/make_timed.py from verify_v4.cpp.
//
// verify_v4.cpp - independent route-proof-v4 checker (C++17, zlib).
""")
rep("""#include <zlib.h>
""", """#include <zlib.h>
#include <x86intrin.h>
""")
rep("""struct VErr : runtime_error {""", """// ---- profiling counters (ticks of the time stamp counter)
enum { P_SETUP, P_PARSE, P_TAKE, P_NORM_NODE, P_NORM_CHILD, P_RECORD, P_SAME, P_REDUCE, P_LABELS, P_CORE,
       P_PACK_RESET, P_PACK_DEFLATE, P_UNPACK, P_SHA, P_N };
static unsigned long long prof[P_N], prof_calls[P_N], prof_packed_bytes;
static const char* prof_name[P_N] = {"setup_model_position", "read_and_parse_certificate", "take_state", "normalize_node",
                                     "normalize_child", "record_state", "compare_state", "in_normalize_reduce", "in_normalize_labels",
                                     "in_normalize_core", "in_pack_reset_dictionary", "in_pack_deflate", "in_unpack_inflate", "sha256"};
struct Tm {
  int k; unsigned long long t0;
  explicit Tm(int kk) : k(kk), t0(__rdtsc()) {}
  ~Tm() { prof[k] += __rdtsc() - t0; prof_calls[k]++; }
};
static int prof_env(const char* name, int dflt) { const char* v = getenv(name); return v && *v ? atoi(v) : dflt; }

struct VErr : runtime_error {""")
rep("""  void update(const void* data, size_t n) {
    const u8* p = (const u8*)data;""", """  void update(const void* data, size_t n) {
    Tm tm_(P_SHA);
    const u8* p = (const u8*)data;""")
rep("""  int normalize(int cur, const u8* in, u8* out) {
    reduce(cur, in, out);
    static_labels(out);
    if (labels[cur] != -1) return labels[cur];
    fill(seen.begin(), seen.end(), 0);""", """  int normalize(int cur, const u8* in, u8* out) {
    { Tm tm_(P_REDUCE); reduce(cur, in, out); }
    { Tm tm_(P_LABELS); static_labels(out); }
    if (labels[cur] != -1) return labels[cur];
    Tm tm_(P_CORE);
    fill(seen.begin(), seen.end(), 0);""")
rep("""    if (deflateInit2(&ds, 6, Z_DEFLATED, -15, 4, Z_RLE) != Z_OK || inflateInit2(&is, -15) != Z_OK)""",
    """    if (deflateInit2(&ds, prof_env("VPROF_LEVEL", 6), Z_DEFLATED, -15, prof_env("VPROF_MEMLEVEL", 4), prof_env("VPROF_STRATEGY", Z_RLE)) != Z_OK || inflateInit2(&is, -15) != Z_OK)""")
rep("""  string pack(const u8* c, size_t G) {
    if (deflateReset(&ds) != Z_OK || deflateSetDictionary(&ds, dict.data(), (uInt)dict.size()) != Z_OK) throw VErr("zlib failure");
    zbuf.resize(deflateBound(&ds, G) + 64);""", """  string pack(const u8* c, size_t G) {
    { Tm tm_(P_PACK_RESET);
    if (deflateReset(&ds) != Z_OK || deflateSetDictionary(&ds, dict.data(), (uInt)dict.size()) != Z_OK) throw VErr("zlib failure");
    }
    Tm tm_(P_PACK_DEFLATE);
    zbuf.resize(deflateBound(&ds, G) + 64);""")
rep("""    if (deflate(&ds, Z_FINISH) != Z_STREAM_END) throw VErr("zlib compress failure");
    return string((const char*)zbuf.data(), zbuf.size() - ds.avail_out);""", """    if (deflate(&ds, Z_FINISH) != Z_STREAM_END) throw VErr("zlib compress failure");
    prof_packed_bytes += zbuf.size() - ds.avail_out;
    return string((const char*)zbuf.data(), zbuf.size() - ds.avail_out);""")
rep("""  void unpack(const u8* z, size_t zl, vector<u8>& out, size_t G) {
    out.resize(G);""", """  void unpack(const u8* z, size_t zl, vector<u8>& out, size_t G) {
    Tm tm_(P_UNPACK);
    out.resize(G);""")
rep("""  try {
    string dict_bytes = read_file(dict_path), pos_bytes = read_file(pos_path);""", """  const unsigned long long tsc0 = __rdtsc();
  try {
    unsigned long long tsc_setup = __rdtsc();
    string dict_bytes = read_file(dict_path), pos_bytes = read_file(pos_path);""")
rep("""    // ---- read certificate
    ProofReader rd(proof_path);""", """    prof[P_SETUP] += __rdtsc() - tsc_setup; prof_calls[P_SETUP]++;
    // ---- read certificate
    unsigned long long tsc_parse = __rdtsc();
    ProofReader rd(proof_path);""")
rep("""    string proof_hex = rd.finish_hex();
""", """    string proof_hex = rd.finish_hex();
    prof[P_PARSE] += __rdtsc() - tsc_parse; prof_calls[P_PARSE]++;
""")
rep("""      int v = (int)st.take(id, S, G);
      int stat = M.normalize(v, S.data(), canon.data());""", """      int v; { Tm tm_(P_TAKE); v = (int)st.take(id, S, G); }
      int stat; { Tm tm_(P_NORM_NODE); stat = M.normalize(v, S.data(), canon.data()); }""")
rep("""        int t = M.gtgt[g];
        M.normalize(t, tmp.data(), child.data());
        if (reached[c]) {
          require(st.same(c, (u32)t, child.data(), G, cmp),
                  "node " + to_string(id) + ": incorrect child state (node " + to_string(c) + " reached with a different state)");
        } else {
          reached[c] = 1;
          reached_count++;
          st.record(c, (u32)t, child.data(), G);
          stack.push_back(c);
        }""", """        int t = M.gtgt[g];
        { Tm tm_(P_NORM_CHILD); M.normalize(t, tmp.data(), child.data()); }
        if (reached[c]) {
          Tm tm_(P_SAME);
          require(st.same(c, (u32)t, child.data(), G, cmp),
                  "node " + to_string(id) + ": incorrect child state (node " + to_string(c) + " reached with a different state)");
        } else {
          Tm tm_(P_RECORD);
          reached[c] = 1;
          reached_count++;
          st.record(c, (u32)t, child.data(), G);
          stack.push_back(c);
        }""")
rep("""    fputs(o.c_str(), stdout);
    return 0;""", """    fputs(o.c_str(), stdout);
    {
      const double ticks_per_s = (double)(__rdtsc() - tsc0) / el;
      string p = "{\\"profile_total_seconds\\": " + to_string(el) + ", \\"nodes\\": " + to_string(reached_count) +
                 ", \\"packed_state_bytes\\": " + to_string(prof_packed_bytes);
      for (int i = 0; i < P_N; i++)
        p += string(", \\"") + prof_name[i] + "\\": [" + to_string(prof[i] / ticks_per_s) + ", " + to_string(prof_calls[i]) + "]";
      fprintf(stderr, "%s}\\n", p.c_str());
    }
    return 0;""")
(HERE / 'verify_v4_timed.cpp').write_text(s, encoding='utf-8')
print('verify_v4_timed.cpp:', len(s.splitlines()), 'lines; verify_v4.cpp:', len(src.splitlines()), 'lines')
