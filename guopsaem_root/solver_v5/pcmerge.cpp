// pcmerge: merge proven-cache files (solver_v5 --proven-save) into one file of at most MAX entries.
// Duplicate keys keep the record with the larger work; when there are more than MAX distinct keys the
// records with the largest work are kept. All inputs must belong to the same game graph.
//   pcmerge OUT.pc MAX IN.pc [IN.pc ...]
// The cache only holds search hints (proven pn/dn values of canonical states); certificates are still
// rebuilt by replay and checked by the verifier, so a lost or dropped record can only cost time.
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>
using namespace std;
typedef uint64_t u64; typedef uint32_t u32; typedef uint16_t u16; typedef uint8_t u8;
struct PCHeader { char magic[8]; u64 graph0, graph1; u32 min_work, reserved; u64 count, created; };
struct PCRec { u64 k0, k1; u32 work; u16 best; u8 win, pad; };
static_assert(sizeof(PCRec) == 24, "PCRec layout");
static const char PC_MAGIC[8] = {'Y', 'S', 'P', 'C', '1', 0, 0, 0};
static const char PC_END[8] = {'Y', 'S', 'P', 'C', 'E', 'N', 'D', 0};
static inline void ck_add(u64& h, u64 w) { h = (h ^ w) * 0x100000001b3ull; h ^= h >> 31; }
struct KeyHash { size_t operator()(const pair<u64, u64>& k) const { return k.first ^ (k.second * 0x9E3779B97F4A7C15ull); } };

int main(int argc, char** argv) {
  try {
    if (argc < 4) throw runtime_error("usage: pcmerge OUT.pc MAX IN.pc [IN.pc ...]");
    const string out = argv[1];
    const u64 maxn = strtoull(argv[2], nullptr, 10);
    u64 g0 = 0, g1 = 0; bool have_graph = false;
    unordered_map<pair<u64, u64>, PCRec, KeyHash> recs;
    u64 read_total = 0;
    for (int a = 3; a < argc; a++) {
      FILE* f = fopen(argv[a], "rb");
      if (!f) throw runtime_error(string("cannot open ") + argv[a]);
      PCHeader h;
      if (fread(&h, sizeof h, 1, f) != 1 || memcmp(h.magic, PC_MAGIC, 8)) throw runtime_error(string("not a proven-cache file: ") + argv[a]);
      if (!have_graph) { g0 = h.graph0; g1 = h.graph1; have_graph = true; }
      else if (h.graph0 != g0 || h.graph1 != g1) throw runtime_error(string("different game graph: ") + argv[a]);
      u64 ck = 0x5eedcac4e;
      vector<PCRec> buf(8192);
      for (u64 done = 0; done < h.count;) {
        size_t k = (size_t)min<u64>(h.count - done, buf.size());
        if (fread(buf.data(), sizeof(PCRec), k, f) != k) throw runtime_error(string("truncated: ") + argv[a]);
        for (size_t i = 0; i < k; i++) {
          const PCRec& x = buf[i];
          if (x.win > 1 || x.pad) throw runtime_error(string("bad record: ") + argv[a]);
          ck_add(ck, x.k0); ck_add(ck, x.k1); ck_add(ck, (u64)x.work | ((u64)x.best << 32) | ((u64)x.win << 48));
          auto key = make_pair(x.k0, x.k1);
          auto it = recs.find(key);
          if (it == recs.end()) recs.emplace(key, x);
          else {
            if (it->second.win != x.win) throw runtime_error("conflicting proven values for one key (hash collision?)");
            if (x.work > it->second.work) it->second = x;
          }
        }
        done += k;
        read_total += k;
      }
      u64 tail[2]; char end[8];
      if (fread(tail, 8, 2, f) != 2 || fread(end, 8, 1, f) != 1 || memcmp(end, PC_END, 8)) throw runtime_error(string("truncated: ") + argv[a]);
      if (tail[0] != h.count || tail[1] != ck) throw runtime_error(string("checksum mismatch: ") + argv[a]);
      fclose(f);
    }
    const u64 distinct = recs.size();
    vector<PCRec> all;
    all.reserve(recs.size());
    for (auto& kv : recs) all.push_back(kv.second);
    recs.clear();
    if (all.size() > maxn) {
      nth_element(all.begin(), all.begin() + maxn, all.end(), [](const PCRec& a, const PCRec& b) { return a.work > b.work; });
      all.resize(maxn);
    }
    sort(all.begin(), all.end(), [](const PCRec& a, const PCRec& b) { return a.k1 != b.k1 ? a.k1 < b.k1 : a.k0 < b.k0; });
    const string tmp = out + ".tmp";
    FILE* o = fopen(tmp.c_str(), "wb");
    if (!o) throw runtime_error("cannot create " + tmp);
    PCHeader h; memset(&h, 0, sizeof h);
    memcpy(h.magic, PC_MAGIC, 8); h.graph0 = g0; h.graph1 = g1; h.min_work = 1; h.count = all.size(); h.created = (u64)time(nullptr);
    bool ok = fwrite(&h, sizeof h, 1, o) == 1;
    u64 ck = 0x5eedcac4e;
    for (auto& x : all) { ck_add(ck, x.k0); ck_add(ck, x.k1); ck_add(ck, (u64)x.work | ((u64)x.best << 32) | ((u64)x.win << 48)); }
    if (ok && !all.empty()) ok = fwrite(all.data(), sizeof(PCRec), all.size(), o) == all.size();
    u64 tail[2] = {(u64)all.size(), ck};
    if (ok) ok = fwrite(tail, 8, 2, o) == 2 && fwrite(PC_END, 8, 1, o) == 1;
    if (fclose(o) != 0) ok = false;
    if (!ok) { remove(tmp.c_str()); throw runtime_error("write failure"); }
    if (rename(tmp.c_str(), out.c_str())) { remove(tmp.c_str()); throw runtime_error("rename failure"); }
    printf("{\"read\":%llu,\"distinct\":%llu,\"written\":%llu}\n", (unsigned long long)read_total,
           (unsigned long long)distinct, (unsigned long long)all.size());
    return 0;
  } catch (const exception& e) {
    fprintf(stderr, "pcmerge: %s\n", e.what());
    return 1;
  }
}
