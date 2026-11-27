// tt2pc: extract the proven entries (pn == 0 or dn == 0) of a solver_v5 --tt-save file into a
// solver_v5_cache proven-cache file (--proven-load). The graph fingerprint is copied from the TT header;
// the root binding of the TT file is dropped. Usage: tt2pc IN.tt OUT.pc [MIN_WORK]
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <vector>
typedef uint64_t u64; typedef uint32_t u32; typedef uint16_t u16; typedef uint8_t u8;
struct TTHeader { char magic[8]; u64 graph0, graph1, root0, root1; int32_t init, init_div, wpn, reserved; u64 count, created; };
struct PCHeader { char magic[8]; u64 graph0, graph1; u32 min_work, reserved; u64 count, created; };
struct PCRec { u64 k0, k1; u32 work; u16 best; u8 win, pad; };
static inline void ck_add(u64& h, u64 w) { h = (h ^ w) * 0x100000001b3ull; h ^= h >> 31; }
static const char TT_MAGIC[8] = {'Y', 'S', 'T', 'T', '1', 0, 0, 0};
static const char PC_MAGIC[8] = {'Y', 'S', 'P', 'C', '1', 0, 0, 0};
static const char PC_END[8] = {'Y', 'S', 'P', 'C', 'E', 'N', 'D', 0};
int main(int argc, char** argv) {
  if (argc < 3) { fprintf(stderr, "usage: tt2pc IN.tt OUT.pc [MIN_WORK]\n"); return 2; }
  u32 minw = argc > 3 ? (u32)strtoul(argv[3], 0, 10) : 1;
  FILE* f = fopen(argv[1], "rb"); if (!f) { perror("in"); return 2; }
  TTHeader h; if (fread(&h, sizeof h, 1, f) != 1 || memcmp(h.magic, TT_MAGIC, 8)) { fprintf(stderr, "not a TT file\n"); return 2; }
  FILE* o = fopen(argv[2], "wb"); if (!o) { perror("out"); return 2; }
  PCHeader p; memset(&p, 0, sizeof p); memcpy(p.magic, PC_MAGIC, 8); p.graph0 = h.graph0; p.graph1 = h.graph1; p.min_work = minw; p.created = (u64)time(0);
  fwrite(&p, sizeof p, 1, o);
  u64 ckin = 0x5eedc0de, ck = 0x5eedcac4e, n = 0, proven = 0;
  std::vector<u64> buf(4 * 8192);
  for (u64 done = 0; done < h.count;) {
    size_t k = (size_t)((h.count - done) < 8192 ? (h.count - done) : 8192);
    if (fread(buf.data(), 32, k, f) != k) { fprintf(stderr, "truncated\n"); return 2; }
    for (size_t r = 0; r < k; r++) {
      const u64* rec = &buf[4 * r];
      for (int j = 0; j < 4; j++) ck_add(ckin, rec[j]);
      u32 pn = (u32)rec[2], dn = (u32)(rec[2] >> 32), work = (u32)rec[3];
      if (pn != 0 && dn != 0) continue;
      proven++;
      if (work < minw) continue;
      PCRec x; memset(&x, 0, sizeof x);
      x.k0 = rec[0]; x.k1 = rec[1]; x.work = work; x.best = (u16)((rec[3] >> 32) & 0xFFFF); x.win = pn == 0;
      ck_add(ck, x.k0); ck_add(ck, x.k1); ck_add(ck, (u64)x.work | ((u64)x.best << 32) | ((u64)x.win << 48));
      fwrite(&x, sizeof x, 1, o); n++;
    }
    done += k;
  }
  u64 tail[2]; if (fread(tail, 8, 2, f) != 2 || tail[0] != h.count || tail[1] != ckin) { fprintf(stderr, "TT checksum mismatch\n"); return 2; }
  fclose(f);
  u64 t2[2] = {n, ck}; fwrite(t2, 8, 2, o); fwrite(PC_END, 8, 1, o);
  p.count = n; fseek(o, 0, SEEK_SET); fwrite(&p, sizeof p, 1, o);
  if (fclose(o)) { perror("close"); return 2; }
  printf("{\"tt_entries\":%llu,\"proven\":%llu,\"written\":%llu,\"min_work\":%u}\n", (unsigned long long)h.count, (unsigned long long)proven, (unsigned long long)n, minw);
  return 0;
}
