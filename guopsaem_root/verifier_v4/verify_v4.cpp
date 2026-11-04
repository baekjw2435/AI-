// verify_v4.cpp - independent route-proof-v4 checker (C++17, zlib).
//
// Written from the specification (guopsaem_root/verifier_v3/verify_v3.py, README_KO.md and
// verifier_v4/FORMAT.md). It shares no code with the solver: its own UTF-8 / Hangul handling,
// dictionary parsing, position replay, JSON parser, SHA-256, model and canonical form.
//
// Build: g++ -O2 -std=c++17 -o verify_v4 verify_v4.cpp -lz
// Usage: verify_v4 --dictionary D --expected-word-count N --position P.json --proof PROOF[.gz]
//                  [--input IN.txt] [--digest-only]
// Prints one JSON object (same fields as verify_v4.py); exit 0 iff verified.
#include <zlib.h>

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

using namespace std;
typedef uint8_t u8;
typedef uint32_t u32;
typedef uint64_t u64;
typedef int64_t i64;

struct VErr : runtime_error {
  explicit VErr(const string& s) : runtime_error(s) {}
};
static void require(bool c, const string& m) {
  if (!c) throw VErr(m);
}

// ------------------------------------------------------------------ SHA-256 (FIPS 180-4)
struct Sha256 {
  u32 h[8];
  u8 buf[64];
  u64 len = 0;
  size_t fill = 0;
  Sha256() {
    static const u32 iv[8] = {0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19};
    memcpy(h, iv, sizeof h);
  }
  static u32 rotr(u32 x, int n) { return (x >> n) | (x << (32 - n)); }
  void block(const u8* p) {
    static const u32 K[64] = {
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be,
        0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa,
        0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85,
        0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3,
        0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f,
        0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2};
    u32 w[64];
    for (int i = 0; i < 16; i++) w[i] = (u32)p[4 * i] << 24 | (u32)p[4 * i + 1] << 16 | (u32)p[4 * i + 2] << 8 | p[4 * i + 3];
    for (int i = 16; i < 64; i++) {
      u32 s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >> 3);
      u32 s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >> 10);
      w[i] = w[i - 16] + s0 + w[i - 7] + s1;
    }
    u32 a = h[0], b = h[1], c = h[2], d = h[3], e = h[4], f = h[5], g = h[6], hh = h[7];
    for (int i = 0; i < 64; i++) {
      u32 t1 = hh + (rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)) + ((e & f) ^ (~e & g)) + K[i] + w[i];
      u32 t2 = (rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)) + ((a & b) ^ (a & c) ^ (b & c));
      hh = g; g = f; f = e; e = d + t1; d = c; c = b; b = a; a = t1 + t2;
    }
    h[0] += a; h[1] += b; h[2] += c; h[3] += d; h[4] += e; h[5] += f; h[6] += g; h[7] += hh;
  }
  void update(const void* data, size_t n) {
    const u8* p = (const u8*)data;
    len += n;
    while (n) {
      size_t k = min(n, 64 - fill);
      memcpy(buf + fill, p, k);
      fill += k; p += k; n -= k;
      if (fill == 64) { block(buf); fill = 0; }
    }
  }
  void digest(u8 out[32]) {
    u64 bits = len * 8;
    u8 pad = 0x80;
    update(&pad, 1);
    u8 z = 0;
    while (fill != 56) update(&z, 1);
    u8 lb[8];
    for (int i = 0; i < 8; i++) lb[i] = (u8)(bits >> (56 - 8 * i));
    update(lb, 8);
    for (int i = 0; i < 8; i++) for (int j = 0; j < 4; j++) out[4 * i + j] = (u8)(h[i] >> (24 - 8 * j));
  }
  string hex() {
    u8 d[32];
    digest(d);
    static const char* x = "0123456789abcdef";
    string s;
    for (u8 c : d) { s += x[c >> 4]; s += x[c & 15]; }
    return s;
  }
};
static string sha_hex(const string& s) { Sha256 h; h.update(s.data(), s.size()); return h.hex(); }

// ------------------------------------------------------------------ UTF-8
// Strict decoder (as Python's "utf-8" codec); allow_surrogates mimics "surrogatepass".
static bool utf8_decode(const string& s, vector<u32>& out, bool allow_surrogates) {
  out.clear();
  size_t i = 0, n = s.size();
  const u8* p = (const u8*)s.data();
  while (i < n) {
    u32 c = p[i];
    if (c < 0x80) { out.push_back(c); i++; continue; }
    int len; u32 mn;
    if (c >= 0xC2 && c <= 0xDF) { len = 2; c &= 0x1F; mn = 0x80; }
    else if (c >= 0xE0 && c <= 0xEF) { len = 3; c &= 0x0F; mn = 0x800; }
    else if (c >= 0xF0 && c <= 0xF4) { len = 4; c &= 0x07; mn = 0x10000; }
    else return false;
    if (i + len > n) return false;
    for (int k = 1; k < len; k++) {
      if ((p[i + k] & 0xC0) != 0x80) return false;
      c = (c << 6) | (p[i + k] & 0x3F);
    }
    if (c < mn || c > 0x10FFFF) return false;
    if (c >= 0xD800 && c <= 0xDFFF && !allow_surrogates) return false;
    out.push_back(c);
    i += len;
  }
  return true;
}
static void utf8_put(string& s, u32 c) {  // also encodes lone surrogates (WTF-8), injective
  if (c < 0x80) s += (char)c;
  else if (c < 0x800) { s += (char)(0xC0 | c >> 6); s += (char)(0x80 | (c & 63)); }
  else if (c < 0x10000) { s += (char)(0xE0 | c >> 12); s += (char)(0x80 | (c >> 6 & 63)); s += (char)(0x80 | (c & 63)); }
  else { s += (char)(0xF0 | c >> 18); s += (char)(0x80 | (c >> 12 & 63)); s += (char)(0x80 | (c >> 6 & 63)); s += (char)(0x80 | (c & 63)); }
}
static string utf8_of(u32 c) { string s; utf8_put(s, c); return s; }
// Python str.isspace() (the separators of str.split())
static bool py_space(u32 c) {
  return (c >= 9 && c <= 13) || (c >= 0x1C && c <= 0x20) || c == 0x85 || c == 0xA0 || c == 0x1680 || (c >= 0x2000 && c <= 0x200A) ||
         c == 0x2028 || c == 0x2029 || c == 0x202F || c == 0x205F || c == 0x3000;
}
static bool hangul(u32 c) { return c >= 0xAC00 && c <= 0xD7A3; }

// ------------------------------------------------------------------ JSON (Python json.loads semantics)
struct JV {
  enum T { NUL, BOOL, INT, FLT, STR, ARR, OBJ } t = NUL;
  bool b = false;
  i64 i = 0;
  bool big = false;  // integer outside int64 (still an integer)
  string s;          // UTF-8 (WTF-8 for lone surrogates)
  vector<JV> a;
  vector<pair<string, JV>> o;
  const JV* get(const string& k) const {
    for (auto& kv : o) if (kv.first == k) return &kv.second;
    return nullptr;
  }
  bool is_int() const { return t == INT; }
};
struct JParser {
  const char* p;
  const char* e;
  int depth = 0;
  JParser(const char* b, const char* end) : p(b), e(end) {}
  [[noreturn]] void fail(const string& m) { throw VErr(m); }
  void ws() { while (p < e && (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r')) p++; }
  bool lit(const char* w) {
    size_t n = strlen(w);
    if ((size_t)(e - p) >= n && memcmp(p, w, n) == 0) { p += n; return true; }
    return false;
  }
  u32 hex4() {
    if (e - p < 4) fail("bad \\u escape");
    u32 v = 0;
    for (int k = 0; k < 4; k++) {
      char c = *p++;
      v <<= 4;
      if (c >= '0' && c <= '9') v |= c - '0';
      else if (c >= 'a' && c <= 'f') v |= c - 'a' + 10;
      else if (c >= 'A' && c <= 'F') v |= c - 'A' + 10;
      else fail("bad \\u escape");
    }
    return v;
  }
  string str() {  // p at opening quote; input is already valid UTF-8
    p++;
    string out;
    for (;;) {
      if (p >= e) fail("unterminated string");
      unsigned char c = (unsigned char)*p;
      if (c == '"') { p++; return out; }
      if (c < 0x20) fail("invalid control character in string");
      if (c != '\\') { out += (char)c; p++; continue; }
      p++;
      if (p >= e) fail("unterminated string");
      char x = *p++;
      switch (x) {
        case '"': out += '"'; break;
        case '\\': out += '\\'; break;
        case '/': out += '/'; break;
        case 'b': out += '\b'; break;
        case 'f': out += '\f'; break;
        case 'n': out += '\n'; break;
        case 'r': out += '\r'; break;
        case 't': out += '\t'; break;
        case 'u': {
          u32 u = hex4();
          if (u >= 0xD800 && u <= 0xDBFF && e - p >= 6 && p[0] == '\\' && p[1] == 'u') {
            const char* save = p;
            p += 2;
            u32 lo = hex4();
            if (lo >= 0xDC00 && lo <= 0xDFFF) u = 0x10000 + ((u - 0xD800) << 10) + (lo - 0xDC00);
            else p = save;
          }
          utf8_put(out, u);
          break;
        }
        default: fail("invalid escape");
      }
    }
  }
  JV num() {
    const char* s = p;
    if (p < e && *p == '-') p++;
    if (p >= e) fail("bad number");
    if (*p == '0') p++;
    else if (*p >= '1' && *p <= '9') while (p < e && *p >= '0' && *p <= '9') p++;
    else fail("bad number");
    bool flt = false;
    if (p + 1 < e && *p == '.' && p[1] >= '0' && p[1] <= '9') { flt = true; p++; while (p < e && *p >= '0' && *p <= '9') p++; }
    if (p < e && (*p == 'e' || *p == 'E')) {
      const char* q = p + 1;
      if (q < e && (*q == '+' || *q == '-')) q++;
      if (q < e && *q >= '0' && *q <= '9') { flt = true; p = q; while (p < e && *p >= '0' && *p <= '9') p++; }
    }
    JV v;
    if (flt) { v.t = JV::FLT; return v; }
    v.t = JV::INT;
    bool neg = *s == '-';
    const char* d = s + (neg ? 1 : 0);
    if (p - d > 4300) fail("integer string too long");  // Python's int max_str_digits
    if (p - d > 18) { v.big = true; return v; }
    i64 x = 0;
    for (const char* q = d; q < p; q++) x = x * 10 + (*q - '0');
    v.i = neg ? -x : x;
    return v;
  }
  JV value() {
    ws();
    if (p >= e) fail("expecting value");
    char c = *p;
    JV v;
    if (c == '{') {
      if (++depth > 900) fail("nesting too deep");
      p++;
      v.t = JV::OBJ;
      ws();
      if (p < e && *p == '}') { p++; depth--; return v; }
      for (;;) {
        ws();
        if (p >= e || *p != '"') fail("expecting property name");
        string k = str();
        ws();
        if (p >= e || *p != ':') fail("expecting ':'");
        p++;
        JV x = value();
        for (auto& kv : v.o) if (kv.first == k) fail("duplicate JSON key: " + k);
        v.o.emplace_back(move(k), move(x));
        ws();
        if (p < e && *p == ',') { p++; continue; }
        if (p < e && *p == '}') { p++; break; }
        fail("expecting ',' or '}'");
      }
      depth--;
      return v;
    }
    if (c == '[') {
      if (++depth > 900) fail("nesting too deep");
      p++;
      v.t = JV::ARR;
      ws();
      if (p < e && *p == ']') { p++; depth--; return v; }
      for (;;) {
        v.a.push_back(value());
        ws();
        if (p < e && *p == ',') { p++; continue; }
        if (p < e && *p == ']') { p++; break; }
        fail("expecting ',' or ']'");
      }
      depth--;
      return v;
    }
    if (c == '"') { v.t = JV::STR; v.s = str(); return v; }
    if (lit("null")) return v;
    if (lit("true")) { v.t = JV::BOOL; v.b = true; return v; }
    if (lit("false")) { v.t = JV::BOOL; return v; }
    if (lit("NaN") || lit("Infinity") || lit("-Infinity")) { v.t = JV::FLT; return v; }
    if (c == '-' || (c >= '0' && c <= '9')) return num();
    fail("expecting value");
  }
  JV document() {
    JV v = value();
    ws();
    if (p != e) fail("extra data");
    return v;
  }
};
// a line of the certificate: must be valid UTF-8 (as Python decodes it), then JSON
static JV parse_line(const string& line, u64 line_number) {
  vector<u32> tmp;
  try {
    if (!utf8_decode(line, tmp, false)) throw VErr("not UTF-8");
    JParser jp(line.data(), line.data() + line.size());
    return jp.document();
  } catch (const VErr& ex) {
    throw VErr("invalid JSON on line " + to_string(line_number) + ": " + ex.what());
  }
}

// ------------------------------------------------------------------ the game model
static const char* RULE_NAME = "engine-standard-dueum (ㄹ:ㅑㅕㅖㅛㅠㅣ→ㅇ, ㅏㅐㅗㅚㅜㅡ→ㄴ; ㄴ:ㅕㅛㅠㅣ→ㅇ; one-way)";

// alternative first syllable after receiving c, or 0
static u32 conv(u32 c) {
  require(c >= 0xAC00 && c < 0xAC00 + 11172, "only precomposed Korean syllables are supported");
  u32 off = c - 0xAC00, initial = off / 588, rem = off % 588, vowel = rem / 28;
  if (initial == 5 && (vowel == 2 || vowel == 6 || vowel == 7 || vowel == 12 || vowel == 17 || vowel == 20)) return 0xAC00 + 11 * 588 + rem;
  if (initial == 5 && (vowel == 0 || vowel == 1 || vowel == 8 || vowel == 11 || vowel == 13 || vowel == 18)) return 0xAC00 + 2 * 588 + rem;
  if (initial == 2 && (vowel == 6 || vowel == 12 || vowel == 17 || vowel == 20)) return 0xAC00 + 11 * 588 + rem;
  return 0;
}

struct Model {
  vector<vector<u32>> words;           // code points
  vector<string> words_utf8;
  unordered_map<string, int> word_index;
  unordered_set<u32> starts;
  vector<vector<u32>> keys;            // vertex -> sorted first syllables
  map<vector<u32>, int> vertex;
  vector<string> names;
  int N = 0, G = 0;
  vector<vector<int>> gsrc;            // group -> sorted sources
  vector<int> gtgt;
  vector<u8> full;
  vector<u8> shared;
  vector<int> word_group;              // word index -> group
  vector<vector<int>> avail;           // vertex -> groups (ascending)
  vector<pair<int, int>> pairs;
  vector<int> loops;
  // scratch
  vector<u8> reach, seen, single_loop, shared_loop;
  vector<int> labels, queue_, nsucc, succ_off, succ, pred_off, pred, rem, mark, work;
  int stamp = 0;

  vector<u32> key(u32 s) const {
    vector<u32> k;
    u32 alt = conv(s);
    if (starts.count(s)) k.push_back(s);
    if (alt && alt != s && starts.count(alt)) k.push_back(alt);
    sort(k.begin(), k.end());
    return k;
  }
  int vertex_of(u32 s) const {
    auto k = key(s);
    auto it = vertex.find(k);
    require(it != vertex.end(), "syllable " + utf8_of(s) + " is outside the model");
    return it->second;
  }

  Model(const string& bytes, i64 expected) {
    string body = bytes;
    if (body.size() >= 3 && (u8)body[0] == 0xEF && (u8)body[1] == 0xBB && (u8)body[2] == 0xBF) body = body.substr(3);
    vector<u32> cps;
    require(utf8_decode(body, cps, false), "dictionary is not UTF-8");
    vector<u32> cur;
    for (size_t i = 0; i <= cps.size(); i++) {
      if (i == cps.size() || py_space(cps[i])) {
        if (!cur.empty()) { words.push_back(cur); cur.clear(); }
      } else cur.push_back(cps[i]);
    }
    require(!words.empty(), "empty dictionary");
    for (auto& w : words) {
      string s;
      for (u32 c : w) utf8_put(s, c);
      words_utf8.push_back(s);
    }
    for (size_t i = 0; i < words.size(); i++) require(word_index.emplace(words_utf8[i], (int)i).second, "duplicate dictionary word");
    if (expected) require((i64)words.size() == expected, "expected " + to_string(expected) + " words, got " + to_string(words.size()));
    for (auto& w : words) for (u32 c : w) require(hangul(c), "dictionary contains a non-Hangul token");
    for (auto& w : words) starts.insert(w[0]);
    set_keys();
  }
  void set_keys() {
    vector<u32> raw(starts.begin(), starts.end());
    for (auto& w : words) raw.push_back(w.back());
    sort(raw.begin(), raw.end());
    raw.erase(unique(raw.begin(), raw.end()), raw.end());
    vector<vector<u32>> ks;
    for (u32 x : raw) ks.push_back(key(x));
    sort(ks.begin(), ks.end());
    ks.erase(unique(ks.begin(), ks.end()), ks.end());
    keys = ks;
    N = (int)keys.size();
    for (int i = 0; i < N; i++) {
      vertex[keys[i]] = i;
      string nm;
      for (size_t j = 0; j < keys[i].size(); j++) { if (j) nm += "/"; utf8_put(nm, keys[i][j]); }
      names.push_back(keys[i].empty() ? "-" : nm);
    }
    map<u32, vector<int>> sources_of;
    for (u32 s : starts) {
      vector<int> v;
      for (int i = 0; i < N; i++) if (find(keys[i].begin(), keys[i].end(), s) != keys[i].end()) v.push_back(i);
      sources_of[s] = v;
    }
    map<pair<vector<int>, int>, int> population;
    vector<pair<vector<int>, int>> wkey;
    for (auto& w : words) {
      pair<vector<int>, int> k(sources_of[w[0]], vertex.at(key(w.back())));
      population[k]++;
      wkey.push_back(k);
    }
    require(population.size() <= 65535, "too many groups");
    int mx = 0;
    for (auto& kv : population) mx = max(mx, kv.second);
    require(mx <= 255, "group population above 255");
    map<pair<vector<int>, int>, int> gid;
    for (auto& kv : population) {  // std::map iterates in (sources, target) lexicographic order = Python sorted()
      gid[kv.first] = G++;
      gsrc.push_back(kv.first.first);
      gtgt.push_back(kv.first.second);
      full.push_back((u8)kv.second);
      shared.push_back(kv.first.first.size() > 1);
    }
    for (auto& k : wkey) word_group.push_back(gid.at(k));
    avail.assign(N, {});
    for (int g = 0; g < G; g++) for (int s : gsrc[g]) avail[s].push_back(g);
    for (int g = 0; g < G; g++) {
      if (gsrc[g].size() != 1) continue;
      int s = gsrc[g][0], t = gtgt[g];
      if (s == t) loops.push_back(g);
      else if (s < t) {
        auto it = gid.find({vector<int>{t}, s});
        if (it != gid.end()) pairs.push_back({g, it->second});
      }
    }
    reach.assign(N, 0); seen.assign(N, 0); single_loop.assign(N, 0); shared_loop.assign(N, 0);
    labels.assign(N, -1); nsucc.assign(N, 0); succ_off.assign(N + 1, 0); pred_off.assign(N + 2, 0); rem.assign(N, 0);
    mark.assign(N, 0);
  }

  // step 1 + 2 into r (r may alias nothing)
  void reduce(int cur, const u8* in, u8* r) {
    memcpy(r, in, G);
    for (auto& pr : pairs) { u8 a = min(r[pr.first], r[pr.second]); r[pr.first] -= a; r[pr.second] -= a; }
    for (int g : loops) r[g] %= 2;
    fill(reach.begin(), reach.end(), 0);
    queue_.clear();
    reach[cur] = 1;
    queue_.push_back(cur);
    for (size_t qi = 0; qi < queue_.size(); qi++) {
      int s = queue_[qi];
      for (int g : avail[s]) if (r[g]) { int t = gtgt[g]; if (!reach[t]) { reach[t] = 1; queue_.push_back(t); } }
    }
    for (int g = 0; g < G; g++) {
      if (!r[g]) continue;
      bool any = false;
      for (int s : gsrc[g]) if (reach[s]) { any = true; break; }
      if (!any) r[g] = 0;
    }
  }
  // step 3: least fixed point of the static labels (worklist; the fixed point is unique)
  void static_labels(const u8* c) {
    fill(single_loop.begin(), single_loop.end(), 0);
    fill(shared_loop.begin(), shared_loop.end(), 0);
    succ.clear();
    for (int s = 0; s < N; s++) {
      succ_off[s] = (int)succ.size();
      ++stamp;
      for (int g : avail[s]) {
        if (!c[g]) continue;
        int t = gtgt[g];
        if (t == s) { if (gsrc[g].size() == 1) single_loop[s] = 1; else shared_loop[s] = 1; }
        else if (mark[t] != stamp) { mark[t] = stamp; succ.push_back(t); }
      }
    }
    succ_off[N] = (int)succ.size();
    fill(pred_off.begin(), pred_off.end(), 0);
    for (int t : succ) pred_off[t + 2]++;
    for (int v = 0; v < N; v++) pred_off[v + 2] += pred_off[v + 1];
    pred.resize(succ.size());
    for (int s = 0; s < N; s++) for (int k = succ_off[s]; k < succ_off[s + 1]; k++) pred[pred_off[succ[k] + 1]++] = s;
    // now pred of t = pred[pred_off[t] .. pred_off[t+1])
    work.clear();
    for (int v = 0; v < N; v++) {
      labels[v] = -1;
      rem[v] = succ_off[v + 1] - succ_off[v];
      if (rem[v] == 0 && !shared_loop[v]) { labels[v] = single_loop[v]; work.push_back(v); }
    }
    for (size_t wi = 0; wi < work.size(); wi++) {
      int t = work[wi];
      for (int k = pred_off[t]; k < pred_off[t + 1]; k++) {
        int u = pred[k];
        if (labels[u] != -1) continue;
        if (labels[t] == 0) { labels[u] = 1; work.push_back(u); }
        else if (--rem[u] == 0 && !shared_loop[u]) { labels[u] = single_loop[u]; work.push_back(u); }
      }
    }
  }
  // canonical form of (cur, in) into out; returns the static label of cur (-1, 0, 1)
  int normalize(int cur, const u8* in, u8* out) {
    reduce(cur, in, out);
    static_labels(out);
    if (labels[cur] != -1) return labels[cur];
    fill(seen.begin(), seen.end(), 0);
    queue_.clear();
    seen[cur] = 1;
    queue_.push_back(cur);
    for (size_t qi = 0; qi < queue_.size(); qi++) {
      int s = queue_[qi];
      for (int g : avail[s]) if (out[g]) { int t = gtgt[g]; if (labels[t] == -1 && !seen[t]) { seen[t] = 1; queue_.push_back(t); } }
    }
    for (int g = 0; g < G; g++) {
      if (!out[g]) continue;
      bool keep = labels[gtgt[g]] == -1;
      if (keep) { keep = false; for (int s : gsrc[g]) if (seen[s]) { keep = true; break; } }
      if (!keep) out[g] = 0;
    }
    return -1;
  }
  string numeric_input(int cur, const vector<u8>& counts) const {
    string s = to_string(N) + " " + to_string(G) + " " + to_string(cur) + "\n";
    for (int g = 0; g < G; g++) {
      s += to_string(gsrc[g].size());
      for (int x : gsrc[g]) s += " " + to_string(x);
      s += " " + to_string(gtgt[g]) + " " + to_string(counts[g]) + "\n";
    }
    return s;
  }
};

static string read_file(const string& path) {
  FILE* f = fopen(path.c_str(), "rb");
  if (!f) throw VErr("cannot open " + path);
  string s;
  char buf[1 << 16];
  size_t n;
  while ((n = fread(buf, 1, sizeof buf, f)) > 0) s.append(buf, n);
  bool bad = ferror(f);
  fclose(f);
  if (bad) throw VErr("read error: " + path);
  return s;
}

// Python int() of an ASCII token: optional sign, digits with single underscores between digits
static bool py_int(const string& t, i64& v, bool& big) {
  size_t i = 0;
  bool neg = false;
  big = false;
  if (i < t.size() && (t[i] == '+' || t[i] == '-')) { neg = t[i] == '-'; i++; }
  if (i >= t.size() || !isdigit((u8)t[i])) return false;
  i64 x = 0;
  size_t digits = 0;
  for (; i < t.size(); i++) {
    if (t[i] == '_') { if (i + 1 >= t.size() || !isdigit((u8)t[i + 1])) return false; continue; }
    if (!isdigit((u8)t[i])) return false;
    if (++digits > 18) big = true;
    else x = x * 10 + (t[i] - '0');
  }
  if (digits > 4300) return false;
  v = neg ? -x : x;
  return true;
}

// ------------------------------------------------------------------ proof stream (plain or gzip, members concatenated)
struct ProofReader {
  FILE* f = nullptr;
  bool gz = false;
  z_stream zs{};
  bool z_init = false, member_open = false, eof_raw = false;
  vector<u8> inbuf, outbuf;
  string pending;
  size_t pend_pos = 0;
  bool done = false;
  Sha256 sha;
  explicit ProofReader(const string& path) {
    f = fopen(path.c_str(), "rb");
    if (!f) throw VErr("cannot open proof " + path);
    inbuf.resize(1 << 20);
    outbuf.resize(1 << 20);
    int c1 = fgetc(f), c2 = fgetc(f);
    gz = c1 == 0x1f && c2 == 0x8b;
    rewind(f);
    if (gz) {
      if (inflateInit2(&zs, 15 + 16) != Z_OK) throw VErr("zlib init failure");
      z_init = true;
      member_open = true;
    }
  }
  ~ProofReader() {
    if (z_init) inflateEnd(&zs);
    if (f) fclose(f);
  }
  bool refill_raw() {
    size_t n = fread(inbuf.data(), 1, inbuf.size(), f);
    if (ferror(f)) throw VErr("proof read error");
    if (n == 0) { eof_raw = true; return false; }
    sha.update(inbuf.data(), n);
    zs.next_in = inbuf.data();
    zs.avail_in = (uInt)n;
    return true;
  }
  // append more decompressed data to pending; false at the end of the stream
  bool more() {
    if (done) return false;
    if (!gz) {
      size_t n = fread(outbuf.data(), 1, outbuf.size(), f);
      if (ferror(f)) throw VErr("proof read error");
      if (n == 0) { done = true; return false; }
      sha.update(outbuf.data(), n);
      pending.append((const char*)outbuf.data(), n);
      return true;
    }
    for (;;) {
      if (zs.avail_in == 0 && !eof_raw) refill_raw();
      if (!member_open) {
        if (zs.avail_in == 0 && eof_raw) { done = true; return false; }
        // more bytes after a member: they must form another gzip member (as Python's gzip requires)
        if (inflateReset(&zs) != Z_OK) throw VErr("zlib reset failure");
        member_open = true;
      }
      zs.next_out = outbuf.data();
      zs.avail_out = (uInt)outbuf.size();
      int r = inflate(&zs, Z_NO_FLUSH);
      size_t got = outbuf.size() - zs.avail_out;
      if (r == Z_STREAM_END) member_open = false;
      else if (r != Z_OK && r != Z_BUF_ERROR) throw VErr(string("invalid gzip data: ") + (zs.msg ? zs.msg : "error"));
      if (got) { pending.append((const char*)outbuf.data(), got); return true; }
      // no output and no more input: the member is cut short (inflate keeps nothing buffered then)
      if (member_open && zs.avail_in == 0 && eof_raw) throw VErr("Compressed file ended before the end-of-stream marker was reached");
    }
  }
  bool getline(string& line) {
    for (;;) {
      size_t nl = pending.find('\n', pend_pos);
      if (nl != string::npos) {
        line.assign(pending, pend_pos, nl - pend_pos);
        pend_pos = nl + 1;
        return true;
      }
      if (pend_pos) { pending.erase(0, pend_pos); pend_pos = 0; }
      if (!more()) {
        if (pending.empty()) return false;
        line.swap(pending);
        pending.clear();
        return true;
      }
    }
  }
  string finish_hex() {  // drain remaining raw bytes into the hash (normally none)
    if (gz) { while (!eof_raw) { zs.avail_in = 0; refill_raw(); } }
    else { string l; while (more()) pending.clear(); }
    return sha.hex();
  }
};

// ------------------------------------------------------------------ certificate
struct Cert {
  vector<u8> result;      // 1 = W
  vector<u8> kstatic;     // "k":"static" given
  vector<u64> off{0};     // moves of node i: mv[2*off[i] .. 2*off[i+1])
  vector<u32> mv;
};

// exact compact solver line: {"id":D,"r":"X","m":[[D,D],...]} with optional trailing CR
static bool fast_line(const string& s, u64& id, bool& win, vector<u64>& nums) {
  const char* p = s.data();
  const char* e = p + s.size();
  if (e > p && e[-1] == '\r') e--;
  auto lit = [&](const char* w) { size_t n = strlen(w); if ((size_t)(e - p) < n || memcmp(p, w, n)) return false; p += n; return true; };
  auto num = [&](u64& v) {
    if (p >= e || *p < '0' || *p > '9') return false;
    if (*p == '0') { p++; v = 0; return !(p < e && *p >= '0' && *p <= '9'); }
    const char* s0 = p;
    v = 0;
    while (p < e && *p >= '0' && *p <= '9') { v = v * 10 + (u64)(*p - '0'); p++; }
    return p - s0 <= 18;
  };
  nums.clear();
  if (!lit("{\"id\":") || !num(id) || !lit(",\"r\":\"")) return false;
  if (p < e && (*p == 'W' || *p == 'L')) { win = *p == 'W'; p++; } else return false;
  if (!lit("\",\"m\":[")) return false;
  if (p < e && *p == ']') p++;
  else {
    for (;;) {
      u64 a, b;
      if (!lit("[") || !num(a) || !lit(",") || !num(b) || !lit("]")) return false;
      nums.push_back(a); nums.push_back(b);
      if (p < e && *p == ',') { p++; continue; }
      if (p < e && *p == ']') { p++; break; }
      return false;
    }
  }
  return lit("}") && p == e;
}

static bool int_ok(const JV* v) { return v && v->t == JV::INT; }

// Recorded states. Exact mode: each state is a raw-deflate stream (level 6) with the root
// state as preset dictionary (states resemble the root; about half the size of plain zlib);
// comparisons decompress and compare all G bytes. Digest mode: a SHA-256 per recorded state.
// Compressed bytes live in 64 MB chunks (no reallocation spikes).
struct Store {
  static const u64 CHUNK = 1ull << 26;
  bool digest_only;
  vector<u32> vertex;
  vector<u64> start;
  vector<uint16_t> len;
  vector<vector<u8>> chunks;
  unordered_map<u32, string> pending;  // digest mode: packed states waiting for expansion
  vector<u8> dict, zbuf;
  z_stream ds{}, is{};
  Store(size_t n, bool d, const vector<u8>& dictionary) : digest_only(d), vertex(n), start(n), len(n), dict(dictionary) {
    if (deflateInit2(&ds, 6, Z_DEFLATED, -15, 9, Z_DEFAULT_STRATEGY) != Z_OK || inflateInit2(&is, -15) != Z_OK)
      throw VErr("zlib init failure");
  }
  ~Store() { deflateEnd(&ds); inflateEnd(&is); }
  string pack(const u8* c, size_t G) {
    if (deflateReset(&ds) != Z_OK || deflateSetDictionary(&ds, dict.data(), (uInt)dict.size()) != Z_OK) throw VErr("zlib failure");
    zbuf.resize(deflateBound(&ds, G) + 64);
    ds.next_in = (Bytef*)c; ds.avail_in = (uInt)G;
    ds.next_out = zbuf.data(); ds.avail_out = (uInt)zbuf.size();
    if (deflate(&ds, Z_FINISH) != Z_STREAM_END) throw VErr("zlib compress failure");
    return string((const char*)zbuf.data(), zbuf.size() - ds.avail_out);
  }
  void unpack(const u8* z, size_t zl, vector<u8>& out, size_t G) {
    out.resize(G);
    if (inflateReset(&is) != Z_OK || inflateSetDictionary(&is, dict.data(), (uInt)dict.size()) != Z_OK) throw VErr("zlib failure");
    is.next_in = (Bytef*)z; is.avail_in = (uInt)zl;
    is.next_out = out.data(); is.avail_out = (uInt)G;
    int r = inflate(&is, Z_FINISH);
    if (r != Z_STREAM_END || is.avail_out != 0 || is.avail_in != 0) throw VErr("zlib uncompress failure");
  }
  const u8* at(u64 pos) { return chunks[pos / CHUNK].data() + pos % CHUNK; }
  u64 put(const void* p, size_t n) {
    if (chunks.empty() || chunks.back().size() + n > CHUNK) { chunks.emplace_back(); chunks.back().reserve(CHUNK); }
    u64 pos = (chunks.size() - 1) * CHUNK + chunks.back().size();
    chunks.back().insert(chunks.back().end(), (const u8*)p, (const u8*)p + n);
    return pos;
  }
  void record(u32 id, u32 v, const u8* c, size_t G) {
    vertex[id] = v;
    if (digest_only) {
      Sha256 h; h.update(c, G); u8 d[32]; h.digest(d);
      start[id] = put(d, 32);
      pending[id] = pack(c, G);
    } else {
      string z = pack(c, G);
      if (z.size() > 65535) throw VErr("state too large");
      len[id] = (uint16_t)z.size();
      start[id] = put(z.data(), z.size());
    }
  }
  bool same(u32 id, u32 v, const u8* c, size_t G, vector<u8>& tmp) {
    if (vertex[id] != v) return false;
    if (digest_only) {
      Sha256 h; h.update(c, G); u8 d[32]; h.digest(d);
      return memcmp(at(start[id]), d, 32) == 0;
    }
    unpack(at(start[id]), len[id], tmp, G);
    return memcmp(tmp.data(), c, G) == 0;  // exact bytes
  }
  u32 take(u32 id, vector<u8>& out, size_t G) {
    if (digest_only) {
      auto it = pending.find(id);
      unpack((const u8*)it->second.data(), it->second.size(), out, G);
      pending.erase(it);
    } else unpack(at(start[id]), len[id], out, G);
    return vertex[id];
  }
};

static string jstr(const string& s) {  // json.dumps(ensure_ascii=False) for valid strings
  string o = "\"";
  for (unsigned char c : s) {
    if (c == '"') o += "\\\"";
    else if (c == '\\') o += "\\\\";
    else if (c == '\n') o += "\\n";
    else if (c == '\r') o += "\\r";
    else if (c == '\t') o += "\\t";
    else if (c == '\b') o += "\\b";
    else if (c == '\f') o += "\\f";
    else if (c < 0x20) { char b[8]; snprintf(b, sizeof b, "\\u%04x", c); o += b; }
    else o += (char)c;
  }
  return o + "\"";
}
static string jlist(const vector<string>& v) {
  if (v.empty()) return "[]";
  string s = "[\n";
  for (size_t i = 0; i < v.size(); i++) s += "    " + jstr(v[i]) + (i + 1 < v.size() ? ",\n" : "\n");
  return s + "  ]";
}

int main(int argc, char** argv) {
  auto t0 = chrono::steady_clock::now();
  string dict_path, pos_path, proof_path, input_path, dump_path;
  bool have_input = false, digest_only = false, have_count = false;
  i64 expected = 0;
  for (int i = 1; i < argc; i++) {
    string a = argv[i];
    auto val = [&]() -> string { if (i + 1 >= argc) { fprintf(stderr, "missing value for %s\n", a.c_str()); exit(2); } return argv[++i]; };
    if (a == "--dictionary") dict_path = val();
    else if (a == "--position") pos_path = val();
    else if (a == "--proof") proof_path = val();
    else if (a == "--input") { input_path = val(); have_input = true; }
    else if (a == "--expected-word-count") {
      string v = val(); bool big;
      if (!py_int(v, expected, big) || big) { fprintf(stderr, "invalid --expected-word-count\n"); return 2; }
      have_count = true;
    }
    else if (a == "--digest-only") digest_only = true;
    else if (a == "--dump-states") dump_path = val();  // test aid: "id vertex static sha256(state)" per expanded node
    else { fprintf(stderr, "unknown argument %s\n", a.c_str()); return 2; }
  }
  if (dict_path.empty() || pos_path.empty() || proof_path.empty() || !have_count) {
    fprintf(stderr, "usage: verify_v4 --dictionary D --expected-word-count N --position P --proof PROOF [--input IN] [--digest-only]\n");
    return 2;
  }
  try {
    string dict_bytes = read_file(dict_path), pos_bytes = read_file(pos_path);
    // position JSON: json.loads(bytes) decodes UTF-8 (BOM allowed, surrogatepass)
    JV pos;
    {
      string b = pos_bytes;
      if (b.size() >= 3 && (u8)b[0] == 0xEF && (u8)b[1] == 0xBB && (u8)b[2] == 0xBF) b = b.substr(3);
      for (size_t i = 0; i < min<size_t>(4, b.size()); i++)
        require(b[i] != 0, "invalid position JSON: UTF-16/UTF-32 position files are not supported");
      vector<u32> tmp;
      require(utf8_decode(b, tmp, true), "invalid position JSON: not UTF-8");
      try { JParser jp(b.data(), b.data() + b.size()); pos = jp.document(); }
      catch (const VErr& ex) { throw VErr(string("invalid position JSON: ") + ex.what()); }
    }
    Model M(dict_bytes, expected);
    const int G = M.G, N = M.N;
    // ---- position replay (ModelV3.position)
    require(pos.t == JV::OBJ, "position must be an object");
    const JV* init = pos.get("initial_syllable");
    require(init != nullptr, "missing initial_syllable");
    vector<u32> icp;
    require(init->t == JV::STR && utf8_decode(init->s, icp, true) && icp.size() == 1, "initial_syllable must be one syllable");
    int cur = M.vertex_of(icp[0]);
    const JV* hist = pos.get("history");
    require(hist && hist->t == JV::ARR, "history must be an explicit list");
    const JV* iu = pos.get("initial_used_words");
    JV empty_arr; empty_arr.t = JV::ARR;
    if (!iu) iu = &empty_arr;
    require(iu->t == JV::ARR, "initial_used_words must be a list");
    vector<u8> counts(M.full);
    unordered_set<int> used;
    vector<string> iu_out, hist_out;
    for (auto& w : iu->a) {
      require(w.t == JV::STR && M.word_index.count(w.s), "unknown initially used word: " + (w.t == JV::STR ? w.s : string("<non-string>")));
      int wi = M.word_index[w.s];
      require(!used.count(wi), "reused initially used word: " + w.s);
      counts[M.word_group[wi]]--;
      used.insert(wi);
      iu_out.push_back(w.s);
    }
    int ply = 0;
    for (auto& w : hist->a) {
      ply++;
      require(w.t == JV::STR && M.word_index.count(w.s), "unknown history word at ply " + to_string(ply));
      int wi = M.word_index[w.s];
      require(!used.count(wi), "reused history word at ply " + to_string(ply) + ": " + w.s);
      const auto& k = M.keys[cur];
      require(find(k.begin(), k.end(), M.words[wi][0]) != k.end(),
              "illegal history connection at ply " + to_string(ply) + ": " + w.s + "; expected " + M.names[cur]);
      counts[M.word_group[wi]]--;
      cur = M.vertex_of(M.words[wi].back());
      used.insert(wi);
      hist_out.push_back(w.s);
    }
    const int root_vertex = cur;
    vector<u8> root_state(G);
    M.normalize(root_vertex, counts.data(), root_state.data());
    // ---- numeric input
    string input_digest;
    if (have_input) {
      string data;
      try { data = read_file(input_path); } catch (const VErr&) { throw VErr("invalid numeric solver input"); }
      for (unsigned char c : data) require(c < 0x80, "invalid numeric solver input");
      vector<string> tok;
      string t;
      for (size_t i = 0; i <= data.size(); i++) {
        if (i == data.size() || py_space((u8)data[i])) { if (!t.empty()) { tok.push_back(t); t.clear(); } }
        else t += data[i];
      }
      string exp = M.numeric_input(root_vertex, counts);
      vector<i64> want;
      {
        i64 x = 0; bool in = false;
        for (char c : exp) { if (c >= '0' && c <= '9') { x = x * 10 + (c - '0'); in = true; } else if (in) { want.push_back(x); x = 0; in = false; } }
        if (in) want.push_back(x);
      }
      vector<i64> got;
      bool mismatch = false;
      for (auto& s : tok) {
        i64 v; bool big;
        if (!py_int(s, v, big)) throw VErr("invalid numeric solver input");
        if (big) mismatch = true;
        got.push_back(v);
      }
      require(!mismatch && got == want, "numeric solver input differs from dictionary/history");
      input_digest = sha_hex(data);
    }
    // ---- read certificate
    ProofReader rd(proof_path);
    Cert C;
    string line;
    u64 lineno = 1;
    require(rd.getline(line), "invalid JSON on line 1: empty file");
    JV head = parse_line(line, 1);
    require(head.t == JV::OBJ, "line 1 is not an object");
    for (auto& kv : head.o)
      require(kv.first == "format" || kv.first == "groups" || kv.first == "vertices" || kv.first == "root" || kv.first == "input_sha256",
              "unknown header key(s): " + kv.first);
    const JV* fmt = head.get("format");
    require(fmt && fmt->t == JV::STR && fmt->s == "route-proof-v4", "unknown proof format");
    const JV* hg = head.get("groups");
    require(int_ok(hg) && !hg->big && hg->i == G, "proof group count differs from independently reconstructed model");
    const JV* hv = head.get("vertices");
    require(int_ok(hv) && !hv->big && hv->i == N, "proof vertex count differs from independently reconstructed model");
    const JV* hr = head.get("root");
    require(int_ok(hr) && !hr->big && hr->i >= 0, "invalid proof root id");
    const JV* hs = head.get("input_sha256");
    if (hs) {
      require(have_input, "input_sha256 requires --input");
      require(hs->t == JV::STR && hs->s == input_digest, "proof input hash mismatch");
    }
    vector<u64> nums;
    vector<u64> gmark(G, 0);  // id + 1 of the last node that used the group
    while (rd.getline(line)) {
      lineno++;
      u64 id = C.result.size();
      u64 lid;
      bool win, ks = false;
      if (!fast_line(line, lid, win, nums)) {
        JV node = parse_line(line, lineno);
        require(node.t == JV::OBJ, "line " + to_string(lineno) + " is not an object");
        for (auto& kv : node.o)
          require(kv.first == "id" || kv.first == "r" || kv.first == "m" || kv.first == "k", "node " + to_string(id) + ": unknown key(s)");
        const JV* jid = node.get("id");
        require(int_ok(jid) && !jid->big && jid->i >= 0 && (u64)jid->i == id, "line " + to_string(lineno) + ": ids must be contiguous from zero");
        lid = id;
        const JV* jr = node.get("r");
        require(jr && jr->t == JV::STR && (jr->s == "W" || jr->s == "L"), "node " + to_string(id) + ": unknown result");
        win = jr->s == "W";
        const JV* jk = node.get("k");
        if (jk) { require(jk->t == JV::STR && jk->s == "static", "node " + to_string(id) + ": unknown kind"); ks = true; }
        const JV* jm = node.get("m");
        require(jm && jm->t == JV::ARR, "node " + to_string(id) + ": missing moves");
        nums.clear();
        for (auto& mvv : jm->a) {
          require(mvv.t == JV::ARR && mvv.a.size() == 2 && int_ok(&mvv.a[0]) && int_ok(&mvv.a[1]), "node " + to_string(id) + ": malformed move");
          for (int k = 0; k < 2; k++) {
            const JV& x = mvv.a[k];
            nums.push_back(x.big || x.i < 0 ? ~0ull : (u64)x.i);  // out of range either way
          }
        }
      }
      require(lid == id, "line " + to_string(lineno) + ": ids must be contiguous from zero");
      for (size_t k = 0; k < nums.size(); k += 2) {
        require(nums[k] < (u64)G, "node " + to_string(id) + ": group out of range");
        require(nums[k + 1] < id, "node " + to_string(id) + ": child must precede parent");
      }
      for (size_t k = 0; k < nums.size(); k += 2) {
        require(gmark[nums[k]] != id + 1, "node " + to_string(id) + ": duplicate move group");
        gmark[nums[k]] = id + 1;
      }
      require(id < 0xFFFFFFFFull, "too many nodes");
      C.result.push_back(win);
      C.kstatic.push_back(ks);
      for (u64 x : nums) C.mv.push_back((u32)x);
      C.off.push_back(C.mv.size() / 2);
    }
    require(!C.result.empty(), "empty certificate");
    require(!hr->big && (u64)hr->i == C.result.size() - 1, "root must be last node");
    string proof_hex = rd.finish_hex();
    // ---- replay from the root (iterative DFS)
    const u32 total = (u32)C.result.size(), root = total - 1;
    Store st(total, digest_only, root_state);
    vector<u8> reached(total, 0);
    reached[root] = 1;
    st.record(root, root_vertex, root_state.data(), G);
    vector<u32> stack{root};
    u64 reached_count = 1, checked_moves = 0, static_leaves = 0;
    vector<u8> S(G), canon(G), tmp(G), child(G), cmp;
    vector<int> legal_mark(G, 0);
    int lstamp = 0;
    FILE* dump = dump_path.empty() ? nullptr : fopen(dump_path.c_str(), "wb");
    if (!dump_path.empty() && !dump) throw VErr("cannot write " + dump_path);
    while (!stack.empty()) {
      u32 id = stack.back();
      stack.pop_back();
      int v = (int)st.take(id, S, G);
      int stat = M.normalize(v, S.data(), canon.data());
      require(memcmp(canon.data(), S.data(), G) == 0, "node " + to_string(id) + ": not canonically reduced");
      if (dump) { Sha256 h; h.update(S.data(), G); fprintf(dump, "%u %d %d %s\n", id, v, stat, h.hex().c_str()); }
      bool w = C.result[id];
      u64 lo = C.off[id], hi = C.off[id + 1];
      if (stat != -1) {
        require(lo == hi, "node " + to_string(id) + ": static node must be a leaf");
        require((int)w == stat, "node " + to_string(id) + ": static label is false");
        static_leaves++;
        continue;
      }
      require(!C.kstatic[id], "node " + to_string(id) + ": false static claim");
      if (w) require(hi - lo == 1, "node " + to_string(id) + ": W needs one witness");
      ++lstamp;
      size_t nlegal = 0;
      for (int g : M.avail[v]) if (S[g]) { legal_mark[g] = lstamp; nlegal++; }
      size_t nseen = 0;
      for (u64 k = lo; k < hi; k++) {
        u32 g = C.mv[2 * k], c = C.mv[2 * k + 1];
        require(legal_mark[g] == lstamp, "node " + to_string(id) + ": illegal move group");
        legal_mark[g] = -lstamp;  // seen (groups within a node are distinct; checked at parse time too)
        nseen++;
        require(c < id, "node " + to_string(id) + ": child must precede parent");
        memcpy(tmp.data(), S.data(), G);
        tmp[g]--;
        int t = M.gtgt[g];
        M.normalize(t, tmp.data(), child.data());
        if (reached[c]) {
          require(st.same(c, (u32)t, child.data(), G, cmp),
                  "node " + to_string(id) + ": incorrect child state (node " + to_string(c) + " reached with a different state)");
        } else {
          reached[c] = 1;
          reached_count++;
          st.record(c, (u32)t, child.data(), G);
          stack.push_back(c);
        }
        require(C.result[c] == (w ? 0 : 1), "node " + to_string(id) + ": child verdict contradicts minimax");
        checked_moves++;
      }
      if (!w) require(nseen == nlegal, "node " + to_string(id) + ": losing node omits legal move");
    }
    if (dump) fclose(dump);
    int shared_groups = 0;
    for (u8 x : M.shared) shared_groups += x;
    u64 root_words = 0;
    for (u8 x : root_state) root_words += x;
    double el = chrono::duration<double>(chrono::steady_clock::now() - t0).count();
    char elb[64];
    snprintf(elb, sizeof elb, "%.3f", el);
    string o = "{\n";
    o += "  \"verified\": true,\n  \"format\": \"route-proof-v4\",\n  \"rule\": " + jstr(RULE_NAME) + ",\n";
    o += string("  \"result_for_player_to_move\": \"") + (C.result[root] ? "W" : "L") + "\",\n";
    o += "  \"initial_syllable\": " + jstr(init->s) + ",\n";
    o += "  \"current_vertex\": " + jstr(M.names[root_vertex]) + ",\n";
    o += "  \"history\": " + jlist(hist_out) + ",\n";
    o += "  \"initial_used_words\": " + jlist(iu_out) + ",\n";
    o += "  \"dictionary_words\": " + to_string(M.words.size()) + ",\n  \"used_words\": " + to_string(used.size()) + ",\n";
    o += "  \"model_vertices\": " + to_string(N) + ",\n  \"model_groups\": " + to_string(G) + ",\n";
    o += "  \"shared_groups\": " + to_string(shared_groups) + ",\n";
    o += "  \"checked_certificate_states\": " + to_string(reached_count) + ",\n";
    o += "  \"checked_certificate_moves\": " + to_string(checked_moves) + ",\n";
    o += "  \"checked_static_leaves\": " + to_string(static_leaves) + ",\n";
    o += "  \"reduced_root_word_count\": " + to_string(root_words) + ",\n";
    o += "  \"certificate_nodes\": " + to_string(total) + ",\n  \"unreached_nodes\": " + to_string(total - reached_count) + ",\n";
    o += string("  \"state_storage\": \"") + (digest_only ? "sha256" : "deflate-exact") + "\",\n";
    o += "  \"dictionary_sha256\": \"" + sha_hex(dict_bytes) + "\",\n";
    o += "  \"position_sha256\": \"" + sha_hex(pos_bytes) + "\",\n";
    o += "  \"proof_sha256\": \"" + proof_hex + "\",\n";
    o += "  \"input_sha256\": " + (have_input ? "\"" + input_digest + "\"" : string("null")) + ",\n";
    o += string("  \"elapsed_seconds\": ") + elb + "\n}\n";
    fputs(o.c_str(), stdout);
    return 0;
  } catch (const exception& ex) {
    printf("{\"verified\": false, \"error\": %s}\n", jstr(ex.what()).c_str());
    return 1;
  }
}
