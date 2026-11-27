// site2tab: proof2tab for the route site; the record's last u16 holds the core size (sum of the canonical counts),
// which the site uses to split each book into files by core size.
//
// usage: site2tab PROOF.jsonl[.gz] OUT.bin
//
// For every W node whose chosen child is not a static/terminal L leaf (those moves the engine
// finds by itself), writes a 20-byte record:
//   u32 a, u32 b   FNV-1a over [v & 255, v >> 8, c[0..G-1]] forward (basis 2166136261) and
//                  backward (basis 0x9747b28c), exactly as engine.js computes its lookup key
//   u64 s          an independent 64-bit state hash, used only to detect key collisions at build time
//   u16 g          the winning group
//   u16 core       sum of c[0..G-1] (the canonical core size)
// Prints one JSON line: groups, nodes, W nodes, written records, root id and root result.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <zlib.h>

static char* buf;
static size_t cap = 1 << 22;

static int read_line(gzFile f) {
  size_t n = 0;
  for (;;) {
    if (!gzgets(f, buf + n, (int)(cap - n))) return n > 0;
    n += strlen(buf + n);
    if (n && buf[n - 1] == '\n') return 1;
    if (n + 1 >= cap) { cap *= 2; buf = realloc(buf, cap); if (!buf) { fprintf(stderr, "out of memory\n"); exit(2); } }
  }
}

static long field_int(const char* line, const char* key) {
  const char* p = strstr(line, key);
  if (!p) { fprintf(stderr, "missing %s in: %.80s\n", key, line); exit(2); }
  return strtol(p + strlen(key), NULL, 10);
}

static int hexval(char ch) {
  if (ch >= '0' && ch <= '9') return ch - '0';
  if (ch >= 'a' && ch <= 'f') return ch - 'a' + 10;
  fprintf(stderr, "bad hex digit\n"); exit(2);
}

struct Rec { uint32_t a, b; uint64_t s; uint16_t g, pad; uint32_t child; };

int main(int argc, char** argv) {
  if (argc != 3) { fprintf(stderr, "usage: proof2tab PROOF OUT.bin\n"); return 2; }
  buf = malloc(cap);
  gzFile f = gzopen(argv[1], "rb");
  if (!f) { fprintf(stderr, "cannot open proof\n"); return 2; }
  if (!read_line(f)) { fprintf(stderr, "empty proof\n"); return 2; }
  if (!strstr(buf, "\"route-proof-v2\"")) { fprintf(stderr, "not route-proof-v2\n"); return 2; }
  long G = field_int(buf, "\"groups\":"), root = field_int(buf, "\"root\":");
  size_t ncap = 1 << 20, nodes = 0, rcap = 1 << 20, nrec = 0, wnodes = 0;
  uint8_t* leafL = calloc(ncap, 1);   // 1 = L node without moves (static/terminal L leaf)
  uint8_t* isW = calloc(ncap, 1);
  struct Rec* recs = malloc(rcap * sizeof *recs);
  uint8_t* key = malloc(G + 2);
  int root_res = -1;
  while (read_line(f)) {
    if (buf[0] != '{') continue;
    long id = field_int(buf, "{\"id\":");
    if ((size_t)id != nodes) { fprintf(stderr, "ids are not consecutive at %ld\n", id); return 2; }
    if (nodes == ncap) {
      ncap *= 2; leafL = realloc(leafL, ncap); isW = realloc(isW, ncap);
      memset(leafL + nodes, 0, ncap - nodes); memset(isW + nodes, 0, ncap - nodes);
    }
    const char* r = strstr(buf, "\"r\":\"");
    const char* m = strstr(buf, "\"m\":[");
    if (!r || !m) { fprintf(stderr, "bad node line %ld\n", id); return 2; }
    int win = r[5] == 'W';
    if (id == root) root_res = win;
    isW[id] = win;
    int nomoves = m[5] == ']';
    if (!win) { leafL[id] = nomoves; nodes++; continue; }
    nodes++; wnodes++;
    if (nomoves) continue;  // static W leaf: the engine finds its move
    long v = field_int(buf, "\"v\":");
    const char* c = strstr(buf, "\"c\":\"");
    if (!c) { fprintf(stderr, "no counts in node %ld\n", id); return 2; }
    c += 5;
    key[0] = (uint8_t)(v & 255); key[1] = (uint8_t)(v >> 8);
    unsigned core = 0;
    for (long g = 0; g < G; g++) { key[2 + g] = (uint8_t)(hexval(c[2 * g]) * 16 + hexval(c[2 * g + 1])); core += key[2 + g]; }
    if (c[2 * G] != '"') { fprintf(stderr, "count length mismatch in node %ld\n", id); return 2; }
    uint32_t a = 2166136261u, b = 0x9747b28cu;
    uint64_t s = 0x6a09e667f3bcc909ull;
    for (long i = 0; i < G + 2; i++) { a ^= key[i]; a *= 16777619u; }
    for (long i = G + 1; i >= 0; i--) { b ^= key[i]; b *= 16777619u; }
    for (long i = 0; i < G + 2; i++) { s ^= key[i] + 0x9e3779b97f4a7c15ull + (s << 6) + (s >> 2); s *= 0xbf58476d1ce4e5b9ull; }
    long g0 = strtol(m + 6, NULL, 10);
    const char* comma = strchr(m + 6, ',');
    long child = strtol(comma + 1, NULL, 10);
    if (nrec == rcap) { rcap *= 2; recs = realloc(recs, rcap * sizeof *recs); }
    recs[nrec++] = (struct Rec){a, b, s, (uint16_t)g0, (uint16_t)core, (uint32_t)child};
  }
  gzclose(f);
  FILE* o = fopen(argv[2], "wb");
  if (!o) { fprintf(stderr, "cannot write output\n"); return 2; }
  size_t written = 0, skipped = 0;
  for (size_t i = 0; i < nrec; i++) {
    struct Rec* x = &recs[i];
    if (x->child >= nodes) { fprintf(stderr, "child id out of range\n"); return 2; }
    if (isW[x->child]) { fprintf(stderr, "W node moves into a W node\n"); return 2; }
    if (leafL[x->child]) { skipped++; continue; }
    fwrite(&x->a, 4, 1, o); fwrite(&x->b, 4, 1, o); fwrite(&x->s, 8, 1, o); fwrite(&x->g, 2, 1, o); fwrite(&x->pad, 2, 1, o);
    written++;
  }
  if (fclose(o)) { fprintf(stderr, "write failure\n"); return 2; }
  printf("{\"groups\":%ld,\"nodes\":%zu,\"w_nodes\":%zu,\"records\":%zu,\"skipped_static_child\":%zu,\"root\":%ld,\"root_result\":\"%s\"}\n",
         G, nodes, wnodes, written, skipped, root, root_res == 1 ? "W" : root_res == 0 ? "L" : "?");
  return 0;
}
