/* 어인정 수순 지도: 브라우저 계산기 (WebAssembly).
 *
 * 규칙·모델은 guopsaem_root/verifier_v3/verify_v3.py의 ModelV3와 같습니다.
 *   꼭짓점 = 받은 음절로 낼 수 있는 첫 음절 집합(표준두음법칙, 한 방향), 묶음 = 같은 출발·도착 꼭짓점의 단어들.
 *   이 사전에는 공유 묶음이 없어(출발 꼭짓점이 하나) 묶음 하나가 간선 하나입니다.
 * 정규형(ModelV3.normalize와 같은 단계): 왕복 쌍 상쇄 → 고리는 2로 나눈 나머지 → 닿지 않는 묶음 제거 →
 *   고정 라벨(최소 고정점) → 지금 꼭짓점이 라벨이 없으면 라벨 없는 꼭짓점으로 이어지는 핵심만 남김.
 * 탐색: 증명수 탐색(df-pn, negamax 형태, 1+1/4 규칙)과 4-방향 치환표(64비트 해시).
 * verify_v4 증명서를 만들지 않으므로 사이트에서 이 결과는 '확정'이 아니라 '계산'입니다.
 *
 * 빌드 (WebAssembly):
 *   clang --target=wasm32 -O3 -nostdlib -mbulk-memory -Wl,--no-entry -Wl,--export-dynamic -o eoin_solver.wasm eoin_solver.c
 * 빌드 (시험용, 이 컴퓨터):
 *   gcc -O2 -DNATIVE -o eoin_solver_native eoin_solver.c
 */
#ifdef NATIVE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define EXPORT
#else
#define EXPORT __attribute__((visibility("default")))
#define memcpy(d, s, n) __builtin_memcpy(d, s, n)
#define memset(d, v, n) __builtin_memset(d, v, n)
#endif

typedef unsigned char u8;
typedef unsigned int u32;
typedef unsigned long long u64;

#define MAXV 192
#define MAXG 448
#define MAXOUT 16
#define MAXDEPTH 640
#define INF 0x3fffffffu
#define TT_BITS 21
#define TT_SIZE (1u << TT_BITS)

static int V, G;
static int src[MAXG], tgt[MAXG];
static u8 full[MAXG];
static int outN[MAXV], outG[MAXV][MAXOUT];
static int pairA[MAXG], pairB[MAXG], nPairs;
static int loopG[MAXG], nLoops;

/* ── 정규화 ───────────────────────────────────────────── */
typedef unsigned short u16;
static u32 epoch;
static u32 reachE[MAXV], seenE[MAXV], headE[MAXV], inE[MAXV];
static int head[MAXV], inHead[MAXV], unk[MAXV], q[MAXV], wl[MAXV];
static int nxt[MAXG], inNxt[MAXG];
static signed char lab[MAXV];
static u8 loopf[MAXV];

/* 성긴 국면(ids[i] 묶음에 cnt[i]개, 0이면 없는 것으로 봄)을 cur에서 정규화합니다. 입력은 왕복 쌍 상쇄와 고리 나머지가
 * 이미 된 국면이어야 합니다(정규형에서 단어 하나를 뺀 국면은 늘 그렇습니다). 고정 라벨(1 승, 0 패)이면 그 값을,
 * 아니면 -1을 돌려주고 핵심을 (oid, ocnt, *on)에, cur에서 둘 수 있는 묶음 수를 *mob에 씁니다. */
static int nsparse(int cur, const u16 *ids, const u8 *cnt, int n, u16 *oid, u8 *ocnt, int *on, int *mob) {
  int i, u, t, g, qn = 0, wn = 0, qi;
  epoch++;
  for (i = 0; i < n; i++) {
    if (!cnt[i]) continue;
    u = src[ids[i]];
    if (headE[u] != epoch) { headE[u] = epoch; head[u] = -1; }
    nxt[i] = head[u]; head[u] = i;
  }
  q[qn++] = cur; reachE[cur] = epoch;
  for (qi = 0; qi < qn; qi++) {
    u = q[qi];
    if (headE[u] != epoch) continue;
    for (i = head[u]; i >= 0; i = nxt[i]) { t = tgt[ids[i]]; if (reachE[t] != epoch) { reachE[t] = epoch; q[qn++] = t; } }
  }
  for (qi = 0; qi < qn; qi++) { u = q[qi]; lab[u] = -1; unk[u] = 0; loopf[u] = 0; }
  for (qi = 0; qi < qn; qi++) {
    u = q[qi];
    if (headE[u] != epoch) continue;
    for (i = head[u]; i >= 0; i = nxt[i]) {
      t = tgt[ids[i]];
      if (t == u) { loopf[u] = 1; continue; }
      unk[u]++;
      if (inE[t] != epoch) { inE[t] = epoch; inHead[t] = -1; }
      inNxt[i] = inHead[t]; inHead[t] = i;
    }
  }
  for (qi = 0; qi < qn; qi++) { u = q[qi]; if (unk[u] == 0) { lab[u] = loopf[u]; wl[wn++] = u; } }
  while (wn) {
    t = wl[--wn];
    if (inE[t] != epoch) continue;
    for (i = inHead[t]; i >= 0; i = inNxt[i]) {
      u = src[ids[i]];
      if (lab[u] != -1) continue;
      if (lab[t] == 0) { lab[u] = 1; wl[wn++] = u; }
      else if (--unk[u] == 0) { lab[u] = loopf[u]; wl[wn++] = u; }
    }
  }
  if (lab[cur] != -1) return lab[cur];
  qn = 0; q[qn++] = cur; seenE[cur] = epoch;
  for (qi = 0; qi < qn; qi++) {
    u = q[qi];
    if (headE[u] != epoch) continue;
    for (i = head[u]; i >= 0; i = nxt[i]) { t = tgt[ids[i]]; if (lab[t] == -1 && seenE[t] != epoch) { seenE[t] = epoch; q[qn++] = t; } }
  }
  int m = 0, mv = 0;
  for (i = 0; i < n; i++) {
    if (!cnt[i]) continue;
    g = ids[i];
    if (seenE[src[g]] == epoch && lab[tgt[g]] == -1) { oid[m] = (u16)g; ocnt[m] = cnt[i]; m++; if (src[g] == cur) mv++; }
  }
  *on = m; *mob = mv;
  return -1;
}

static u64 hash_state(int cur, const u16 *ids, const u8 *cnt, int n) {
  u64 h = 0x9e3779b97f4a7c15ull ^ ((u64)(cur + 1) * 0xff51afd7ed558ccdull);
  for (int i = 0; i < n; i++) {
    h ^= ((u64)ids[i] << 8) | cnt[i];
    h *= 0xc4ceb9fe1a85ec53ull; h ^= h >> 29;
  }
  h ^= (u64)n << 40;
  h ^= h >> 31; h *= 0xff51afd7ed558ccdull; h ^= h >> 33;
  return h | 1;  /* 0은 빈 칸 표시 */
}

/* ── 치환표 ───────────────────────────────────────────── */
typedef struct { u64 key; u32 pn, dn; } Entry;
static Entry tt[TT_SIZE];

static int tt_get(u64 key, u32 *pn, u32 *dn) {
  Entry *b = &tt[(u32)(key >> 20) & (TT_SIZE - 4)];
  for (int i = 0; i < 4; i++) if (b[i].key == key) { *pn = b[i].pn; *dn = b[i].dn; return 1; }
  return 0;
}
static void tt_put(u64 key, u32 pn, u32 dn) {
  Entry *b = &tt[(u32)(key >> 20) & (TT_SIZE - 4)], *w = 0;
  u32 worst = 0xffffffffu;
  for (int i = 0; i < 4; i++) {
    if (b[i].key == key || b[i].key == 0) { w = &b[i]; break; }
    u32 score = (b[i].pn == 0 || b[i].dn == 0) ? 0x7fffffffu : b[i].pn + b[i].dn;
    if (score < worst) { worst = score; w = &b[i]; }
  }
  w->key = key; w->pn = pn; w->dn = dn;
}

/* ── df-pn ────────────────────────────────────────────── */
#define ARENA (6u << 20)
static u16 aid[ARENA];
static u8 acnt[ARENA];
static u32 atop;
typedef struct { u32 off[MAXOUT]; int n[MAXOUT], cur[MAXOUT]; u64 h[MAXOUT]; u32 pn[MAXOUT], dn[MAXOUT]; } Frame;
static Frame frames[MAXDEPTH];
static u32 nodes, budget;
static int stopped;

static u32 cap(u64 x) { return x >= INF ? INF : (u32)x; }

/* 정규화된 국면(cur, ids/cnt n개, 해시 h)을 문턱 (thpn, thdn) 안에서 풉니다. 결과 증명수를 *opn, *odn에 둡니다. */
static void mid(int d, int cur, u16 *ids, u8 *cnt, int n, u64 h, u32 thpn, u32 thdn, u32 *opn, u32 *odn) {
  Frame *f = &frames[d];
  u32 mark = atop;
  int k = 0, i;
  nodes++;
  if (d + 1 >= MAXDEPTH || atop + (u32)MAXOUT * (u32)n > ARENA) { stopped = 1; *opn = 1; *odn = 1; return; }
  for (i = 0; i < n; i++) {
    if (src[ids[i]] != cur) continue;
    int t = tgt[ids[i]], cn, mob;
    cnt[i]--;
    int labc = nsparse(t, ids, cnt, n, aid + atop, acnt + atop, &cn, &mob);
    cnt[i]++;
    if (labc == 1) continue;                     /* 상대가 이기는 자리: 지는 수 */
    if (labc == 0) { atop = mark; tt_put(h, 0, INF); *opn = 0; *odn = INF; return; }
    u64 hc = hash_state(t, aid + atop, acnt + atop, cn);
    u32 p, q2;
    if (!tt_get(hc, &p, &q2)) { p = 1; q2 = (u32)mob; }
    if (p == 0) continue;
    if (q2 == 0) { atop = mark; tt_put(h, 0, INF); *opn = 0; *odn = INF; return; }
    f->off[k] = atop; f->n[k] = cn; f->cur[k] = t; f->h[k] = hc; f->pn[k] = p; f->dn[k] = q2;
    atop += (u32)cn;
    k++;
  }
  if (k == 0) { atop = mark; tt_put(h, INF, 0); *opn = INF; *odn = 0; return; }
  for (;;) {
    u32 min1 = INF, min2 = INF; u64 sum = 0; int best = 0;
    for (i = 0; i < k; i++) {
      if (f->dn[i] < min1) { min2 = min1; min1 = f->dn[i]; best = i; }
      else if (f->dn[i] < min2) min2 = f->dn[i];
      sum += f->pn[i];
    }
    u32 pn = min1, dn = cap(sum);
    if (pn == 0) dn = INF;
    if (dn == 0) pn = INF;
    if (pn >= thpn || dn >= thdn || pn == 0 || dn == 0 || stopped) {
      atop = mark; tt_put(h, pn, dn); *opn = pn; *odn = dn; return;
    }
    u32 cthpn = cap((u64)thdn - dn + f->pn[best]);
    u64 e2 = (u64)min2 + (min2 >> 2) + 1;
    u32 cthdn = thpn < cap(e2) ? thpn : cap(e2);
    mid(d + 1, f->cur[best], aid + f->off[best], acnt + f->off[best], f->n[best], f->h[best], cthpn, cthdn,
        &f->pn[best], &f->dn[best]);
    if (nodes >= budget) stopped = 1;
  }
}

/* ── JS가 부르는 함수 ─────────────────────────────────── */
static u8 rawc[MAXG], work[MAXG];
static u16 rid[MAXG];
static u8 rcnt[MAXG];
static int rawcur;

EXPORT void set_group(int g, int s, int t, int n) { src[g] = s; tgt[g] = t; full[g] = (u8)n; }
EXPORT int init(int v, int g) {
  int i, j;
  V = v; G = g;
  if (V > MAXV || G > MAXG) return -1;
  for (i = 0; i < V; i++) outN[i] = 0;
  nPairs = nLoops = 0;
  for (i = 0; i < G; i++) {
    if (outN[src[i]] >= MAXOUT) return -2;
    outG[src[i]][outN[src[i]]++] = i;
    if (src[i] == tgt[i]) loopG[nLoops++] = i;
    else if (src[i] < tgt[i])
      for (j = 0; j < G; j++) if (src[j] == tgt[i] && tgt[j] == src[i]) { pairA[nPairs] = i; pairB[nPairs] = j; nPairs++; }
  }
  memset(tt, 0, sizeof tt);
  return 0;
}
EXPORT void tt_clear(void) { memset(tt, 0, sizeof tt); }
EXPORT void set_count(int g, int n) { rawc[g] = (u8)n; }
EXPORT void set_cur(int v) { rawcur = v; }
EXPORT u32 node_count(void) { return nodes; }

/* 둘 차례인 쪽 기준 값: 1 승, 0 패, -1 이번 예산 안에 못 끝냄(다시 부르면 치환표를 이어서 씀).
 * c는 전체 개수 배열(정규화 전). 왕복 쌍 상쇄와 고리 나머지를 한 뒤 성긴 국면으로 바꿔 정규화합니다. */
static int solve_from(int cur, u8 *c, u32 step) {
  int i, n = 0, on, mob;
  for (i = 0; i < nPairs; i++) { int a = pairA[i], b = pairB[i], m = c[a] < c[b] ? c[a] : c[b]; c[a] -= m; c[b] -= m; }
  for (i = 0; i < nLoops; i++) c[loopG[i]] &= 1;
  for (i = 0; i < G; i++) if (c[i]) { rid[n] = (u16)i; rcnt[n] = c[i]; n++; }
  atop = 0;
  int labr = nsparse(cur, rid, rcnt, n, aid, acnt, &on, &mob);
  if (labr != -1) return labr;
  atop = (u32)on;
  u64 h = hash_state(cur, aid, acnt, on);
  u32 pn, dn;
  if (tt_get(h, &pn, &dn) && (pn == 0 || dn == 0)) return pn == 0;
  stopped = 0; budget = nodes + step;
  mid(0, cur, aid, acnt, on, h, INF, INF, &pn, &dn);
  if (pn == 0) return 1;
  if (dn == 0) return 0;
  return -1;
}
/* 지금 국면(set_count/set_cur)의 값 */
EXPORT int position_value(u32 step) { memcpy(work, rawc, G); return solve_from(rawcur, work, step); }
/* 지금 국면에서 묶음 g를 둔 뒤, 그때 둘 차례인 쪽(상대) 기준 값 */
EXPORT int child_value(int g, u32 step) {
  if (src[g] != rawcur || !rawc[g]) return -2;
  memcpy(work, rawc, G); work[g]--;
  return solve_from(tgt[g], work, step);
}

#if defined(NATIVE) && !defined(EOIN_NO_MAIN)
/* 시험: model.txt(V G, 묶음마다 "src tgt full", 단어마다 묶음 번호)와 positions.txt(줄마다 "시작꼭짓점 기대값 n w1..wn")를 받아
 * 모든 국면의 값을 기대값과 맞춥니다. 기대값 -1은 비교하지 않고 값만 적습니다. */
int main(int argc, char **argv) {
  FILE *fm = fopen(argv[1], "r"), *fp = fopen(argv[2], "r");
  int v, g, nw, i;
  if (!fm || !fp || fscanf(fm, "%d %d %d", &v, &g, &nw) != 3) return 2;
  for (i = 0; i < g; i++) { int s, t, n; if (fscanf(fm, "%d %d %d", &s, &t, &n) != 3) return 2; set_group(i, s, t, n); }
  int *wg = malloc(sizeof(int) * nw);
  for (i = 0; i < nw; i++) if (fscanf(fm, "%d", &wg[i]) != 1) return 2;
  if (init(v, g)) return 3;
  long tot = 0, same = 0, diff = 0;
  int start, want, n;
  while (fscanf(fp, "%d %d %d", &start, &want, &n) == 3) {
    memcpy(rawc, full, G);
    int cur = start, unordered = n < 0;   /* n < 0: the |n| words are only removed (already used), the mover stays at start */
    if (unordered) n = -n;
    for (i = 0; i < n; i++) { int w; if (fscanf(fp, "%d", &w) != 1) return 2; rawc[wg[w]]--; if (!unordered) cur = tgt[wg[w]]; }
    rawcur = cur;
    int r;
    do r = position_value(1u << 30); while (r < 0);
    tot++;
    if (want < 0) printf("%d\n", r);
    else if (r == want) same++;
    else { diff++; fprintf(stderr, "differ at line %ld: want %d got %d\n", tot, want, r); }
  }
  fprintf(stderr, "{\"positions\":%ld,\"same\":%ld,\"differ\":%ld,\"nodes\":%u}\n", tot, same, diff, nodes);
  return diff ? 1 : 0;
}
#endif
