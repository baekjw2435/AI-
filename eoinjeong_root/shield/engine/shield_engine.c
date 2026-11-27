/* 보호막 계산 엔진 (C). 규칙과 판정 순서는 shield_calc.py(파이썬 엔진)와 같다.
 *
 *   보호막 s ≥ 1 : 한 수씩 둔다(Calc.value). 단어 w는 cont(w의 끝 음절) ≥ s일 때만.
 *                  같은 끝 음절의 '기록 안 하는 단어'는 하나로, 기록하는 단어는 묶음(루트 단어는 단어)마다 하나로.
 *   보호막 0      : Calc.oracle — 전체 사전의 보호막 0 판정(StaticModel, 쓴 단어 반영 증분 재판정),
 *                  루트 음절은 루트전(쓴 루트 단어가 없으면 확정 결과, 있으면 eoin_solver.c로 계산),
 *                  루트 밖 순환 음절은 단어를 하나씩 두어 보는 탐색(Calc.cyc_value).
 * 입력: 모형 파일(shield_export.py)과 질문(받은 음절, 보호막, --all 여부)
 * 출력: JSON 한 덩어리(값, 판정 근거 자리들, 첫 자리의 수 분류) — shield_calc.py가 읽어 증명서·출력으로 만든다.
 *
 * 빌드: gcc -O2 -o shield_engine shield_engine.c
 */
#define NATIVE
#define EOIN_NO_MAIN
#include "../../site/solver/eoin_solver.c"
#include <stdint.h>
#include <unistd.h>

/* ── 모형 ───────────────────────────────────────── */
static int NW, NS, NV, NGR;
static char **wstr;
static u8 *wtrk;
static int *wgrp, *wroute;
static char **sstr;
static int *scont, *srv, *smv;
static signed char *sroute;
static u8 *scyc;
static int *sm_off, *sm_n;          /* 음절마다 끝 음절 칸 [sm_off, sm_off+sm_n) */
static int *me_y, *me_off, *me_n;   /* 끝 음절 칸: 끝 음절, 단어 목록 */
static int *mwords;
static int *gt, *gcount, *grc0, *grev, *gs_off, *gs_n, *gsrcs;
static u8 *gflag;                   /* 1 제자리, 2 왕복 쌍, 4 출발 하나 */
static signed char *val0;           /* 1 W, 0 L, -1 미정 */
static u8 *loop0, *shl0;
static int *lcnt0, *s0_off, *s0_n, *p0_off, *p0_n, *gb_off, *gb_n, *vpool;
static int RV, RG, RWN, *rwg, NBU, *bu;   /* 루트 모형 */

static void die(const char *m) { fprintf(stderr, "error: %s\n", m); exit(2); }
static void *xm(size_t n) { void *p = malloc(n ? n : 1); if (!p) die("memory"); return p; }

static char *rdtok(FILE *f) {
  static char buf[4096];
  if (fscanf(f, "%4095s", buf) != 1) die("model token");
  return strdup(buf);
}
static int rdi(FILE *f) { int v; if (fscanf(f, "%d", &v) != 1) die("model int"); return v; }

static void load_model(const char *path) {
  FILE *f = fopen(path, "r");
  char line[1 << 16];
  int i, j;
  if (!f) die("open model");
  if (!fgets(line, sizeof line, f) || strncmp(line, "shield-engine-model-1", 21)) die("model format");
  if (!fgets(line, sizeof line, f)) die("model header");
  NW = rdi(f); NS = rdi(f); NV = rdi(f); NGR = rdi(f);
  wstr = xm(sizeof(char *) * NW); wtrk = xm(NW); wgrp = xm(sizeof(int) * NW); wroute = xm(sizeof(int) * NW);
  for (i = 0; i < NW; i++) { wstr[i] = rdtok(f); wtrk[i] = (u8)rdi(f); wgrp[i] = rdi(f); wroute[i] = rdi(f); }
  sstr = xm(sizeof(char *) * NS); scont = xm(sizeof(int) * NS); sroute = xm(NS); scyc = xm(NS);
  srv = xm(sizeof(int) * NS); smv = xm(sizeof(int) * NS); sm_off = xm(sizeof(int) * NS); sm_n = xm(sizeof(int) * NS);
  int cap_e = 1 << 16, ne = 0, cap_w = 1 << 20, nwd = 0;
  me_y = xm(sizeof(int) * cap_e); me_off = xm(sizeof(int) * cap_e); me_n = xm(sizeof(int) * cap_e);
  mwords = xm(sizeof(int) * cap_w);
  for (i = 0; i < NS; i++) {
    sstr[i] = rdtok(f); scont[i] = rdi(f); sroute[i] = (signed char)rdi(f); scyc[i] = (u8)rdi(f);
    srv[i] = rdi(f); smv[i] = rdi(f);
    int k = rdi(f);
    sm_off[i] = ne; sm_n[i] = k;
    int c;
    for (j = 0; j < k; j++) {
      if (ne >= cap_e) { cap_e *= 2; me_y = realloc(me_y, sizeof(int) * cap_e); me_off = realloc(me_off, sizeof(int) * cap_e); me_n = realloc(me_n, sizeof(int) * cap_e); }
      me_y[ne] = rdi(f); me_off[ne] = nwd; me_n[ne] = 0;
      /* 같은 줄의 단어 번호들 */
      while ((c = fgetc(f)) == ' ') {
        int w = rdi(f);
        if (nwd >= cap_w) { cap_w *= 2; mwords = realloc(mwords, sizeof(int) * cap_w); }
        mwords[nwd++] = w; me_n[ne]++;
      }
      ne++;
    }
  }
  gt = xm(sizeof(int) * NGR); gcount = xm(sizeof(int) * NGR); grc0 = xm(sizeof(int) * NGR); grev = xm(sizeof(int) * NGR);
  gs_off = xm(sizeof(int) * NGR); gs_n = xm(sizeof(int) * NGR); gflag = xm(NGR);
  int ngs = 0, capgs = NGR * 2 + 16;
  gsrcs = xm(sizeof(int) * capgs);
  for (i = 0; i < NGR; i++) {
    gt[i] = rdi(f); gcount[i] = rdi(f); grc0[i] = rdi(f); gflag[i] = (u8)rdi(f); grev[i] = rdi(f);
    int k = rdi(f);
    gs_off[i] = ngs; gs_n[i] = k;
    for (j = 0; j < k; j++) { if (ngs >= capgs) { capgs *= 2; gsrcs = realloc(gsrcs, sizeof(int) * capgs); } gsrcs[ngs++] = rdi(f); }
  }
  val0 = xm(NV); loop0 = xm(NV); shl0 = xm(NV);
  lcnt0 = xm(sizeof(int) * NV); s0_off = xm(sizeof(int) * NV); s0_n = xm(sizeof(int) * NV);
  p0_off = xm(sizeof(int) * NV); p0_n = xm(sizeof(int) * NV); gb_off = xm(sizeof(int) * NV); gb_n = xm(sizeof(int) * NV);
  int np = 0, capp = 1 << 20;
  vpool = xm(sizeof(int) * capp);
  for (i = 0; i < NV; i++) {
    val0[i] = (signed char)rdi(f); loop0[i] = (u8)rdi(f); shl0[i] = (u8)rdi(f); lcnt0[i] = rdi(f);
    int a = rdi(f), b = rdi(f), c = rdi(f);
    if (np + a + b + c >= capp) { while (np + a + b + c >= capp) capp *= 2; vpool = realloc(vpool, sizeof(int) * capp); }
    s0_off[i] = np; s0_n[i] = a; for (j = 0; j < a; j++) vpool[np++] = rdi(f);
    p0_off[i] = np; p0_n[i] = b; for (j = 0; j < b; j++) vpool[np++] = rdi(f);
    gb_off[i] = np; gb_n[i] = c; for (j = 0; j < c; j++) vpool[np++] = rdi(f);
  }
  RV = rdi(f); RG = rdi(f); RWN = rdi(f);
  for (i = 0; i < RG; i++) { int s = rdi(f), t = rdi(f), n = rdi(f); set_group(i, s, t, n); }
  rwg = xm(sizeof(int) * RWN);
  for (i = 0; i < RWN; i++) rwg[i] = rdi(f);
  NBU = rdi(f); bu = xm(sizeof(int) * (NBU + 1));
  for (i = 0; i < NBU; i++) bu[i] = rdi(f);
  if (init(RV, RG)) die("route model");
  fclose(f);
}

/* ── 해시 표(키 = int 배열) ───────────────────────── */
typedef struct { u64 *h; int *koff, *klen, *val; int cap, n; } Map;
static int *karena; static size_t ktop, kcap;
static u64 hkey(const int *k, int n) {
  u64 h = 1469598103934665603ull ^ (u64)n;
  for (int i = 0; i < n; i++) { h ^= (u64)(u32)k[i]; h *= 1099511628211ull; h ^= h >> 29; }
  return h | 1;
}
static void map_init(Map *m, int cap) {
  m->cap = cap; m->n = 0;
  m->h = calloc(cap, sizeof(u64)); m->koff = xm(sizeof(int) * cap); m->klen = xm(sizeof(int) * cap); m->val = xm(sizeof(int) * cap);
}
static int *map_slot(Map *m, const int *k, int n, int create);
static void map_grow(Map *m) {
  Map o = *m;
  map_init(m, o.cap * 2);
  for (int i = 0; i < o.cap; i++) if (o.h[i]) {
    u64 h = o.h[i]; int j = (int)(h & (u64)(m->cap - 1));
    while (m->h[j]) j = (j + 1) & (m->cap - 1);
    m->h[j] = h; m->koff[j] = o.koff[i]; m->klen[j] = o.klen[i]; m->val[j] = o.val[i]; m->n++;
  }
  free(o.h); free(o.koff); free(o.klen); free(o.val);
}
/* 값 칸의 주소. 없으면 create일 때 만들어 -1을 넣는다(없고 create 아니면 NULL). */
static int *map_slot(Map *m, const int *k, int n, int create) {
  u64 h = hkey(k, n);
  int j = (int)(h & (u64)(m->cap - 1));
  while (m->h[j]) {
    if (m->h[j] == h && m->klen[j] == n && !memcmp(karena + m->koff[j], k, sizeof(int) * n)) return &m->val[j];
    j = (j + 1) & (m->cap - 1);
  }
  if (!create) return NULL;
  if ((m->n + 1) * 2 > m->cap) { map_grow(m); return map_slot(m, k, n, create); }
  if (ktop + n >= kcap) { while (ktop + n >= kcap) kcap = kcap ? kcap * 2 : (1 << 20); karena = realloc(karena, sizeof(int) * kcap); if (!karena) die("memory"); }
  memcpy(karena + ktop, k, sizeof(int) * n);
  m->h[j] = h; m->koff[j] = (int)ktop; m->klen[j] = n; m->val[j] = -1; m->n++;
  ktop += n;
  return &m->val[j];
}

/* ── 쓴 단어 집합(정렬된 번호 배열 = 문자열 순) ─────── */
#define MAXU 96
typedef struct { int n; int w[MAXU]; } Set;
static int set_has(const Set *s, int w) {
  int lo = 0, hi = s->n - 1;
  while (lo <= hi) { int m = (lo + hi) >> 1; if (s->w[m] == w) return 1; if (s->w[m] < w) lo = m + 1; else hi = m - 1; }
  return 0;
}
static void set_add(const Set *s, int w, Set *o) {
  int i = 0, j = 0;
  if (set_has(s, w)) { *o = *s; return; }
  if (s->n + 1 > MAXU) die("too many used words");
  while (i < s->n && s->w[i] < w) o->w[j++] = s->w[i++];
  o->w[j++] = w;
  while (i < s->n) o->w[j++] = s->w[i++];
  o->n = j;
}
static int sensitive(int w) {
  int g = wgrp[w];
  return g >= 0 && ((gflag[g] & 3) || gcount[g] <= 12);
}
static int tracked(int w) { return wroute[w] >= 0 || sensitive(w); }
static void child_used(const Set *u, int w, Set *o) { if (tracked(w)) set_add(u, w, o); else *o = *u; }

/* ── 보호막 0: 전체 사전 판정의 증분 재판정(StaticModel.delta와 같음) ── */
static Map delta_map;
static int *dpool_v; static signed char *dpool_l; static size_t dtop, dcap;
static int *d_off, *d_n, nd, cap_d;
static u32 ep = 1;
static u32 *inU, *safeE, *newE, *rcE, *ulE;
static int *ulC;
static int *safeV, *newIdx, *rcV, *labA, *leftA;
static u8 *blk;
static int *stk, *front, *ULl, *Ul;

static int vs_has(const int *a, int n, int x) {
  int lo = 0, hi = n - 1;
  while (lo <= hi) { int m = (lo + hi) >> 1; if (a[m] == x) return 1; if (a[m] < x) lo = m + 1; else hi = m - 1; }
  return 0;
}
static int cmpint(const void *a, const void *b) { int x = *(const int *)a, y = *(const int *)b; return (x > y) - (x < y); }

/* 바뀐 꼭짓점의 구조 */
typedef struct { int n; int *s; u8 loop1, shl; } VStruct;
static VStruct *newS; static int nnew;
static int *nsPool; static int nsTop, nsCap;
static int *rcG; static int nrc;
static int rcget(int g) { return rcE[g] == ep ? rcV[g] : grc0[g]; }

static int succ_has(int p, int v) {
  if (newE[p] == ep) { VStruct *s = &newS[newIdx[p]]; return vs_has(s->s, s->n, v); }
  return vs_has(vpool + s0_off[p], s0_n[p], v);
}
/* newpred: 새로 생긴 간선 t ← v */
static int *npHead, *npNext, *npV, npTop, npCap; static u32 *npE;

static int delta(const Set *removed_sensitive) {
  /* effective: 제자리·왕복 쌍 묶음의 단어, 그리고 다 써서 0이 된 묶음의 단어 */
  int eff[MAXU], ne = 0, i, j;
  int bg[MAXU], bk[MAXU], nb = 0;
  for (i = 0; i < removed_sensitive->n; i++) {
    int g = wgrp[removed_sensitive->w[i]];
    for (j = 0; j < nb; j++) if (bg[j] == g) break;
    if (j == nb) { bg[nb] = g; bk[nb] = 0; nb++; }
    bk[j]++;
  }
  for (i = 0; i < removed_sensitive->n; i++) {
    int w = removed_sensitive->w[i], g = wgrp[w], k = 0;
    for (j = 0; j < nb; j++) if (bg[j] == g) k = bk[j];
    if ((gflag[g] & 3) || k >= gcount[g]) eff[ne++] = w;
  }
  if (ne == 0) return -1;
  int key[MAXU + 1]; key[0] = 3; memcpy(key + 1, eff, sizeof(int) * ne);
  int *slot = map_slot(&delta_map, key, ne + 1, 1);
  if (*slot >= 0) return *slot;
  ep++;
  /* 묶음별 남은 수(mc)와 왕복 쌍 정리(rc) */
  nb = 0;
  for (i = 0; i < ne; i++) {
    int g = wgrp[eff[i]];
    for (j = 0; j < nb; j++) if (bg[j] == g) break;
    if (j == nb) { bg[nb] = g; bk[nb] = 0; nb++; }
    bk[j]++;
  }
  nrc = 0;
#define RCSET(g, v) do { if (rcE[g] != ep) { rcE[g] = ep; rcG[nrc++] = (g); } rcV[g] = (v); } while (0)
  for (i = 0; i < nb; i++) {
    int g = bg[i], mcg = gcount[g] - bk[i];
    RCSET(g, mcg);
    if (gflag[g] & 2) {
      int r = grev[g], cr = gcount[r];
      for (j = 0; j < nb; j++) if (bg[j] == r) cr = gcount[r] - bk[j];
      int a = mcg - cr, b = cr - mcg;
      RCSET(g, a > 0 ? a : 0); RCSET(r, b > 0 ? b : 0);
    }
  }
  /* 바뀐 꼭짓점 */
  nnew = 0; nsTop = 0;
  int affected[4096], na = 0;
  for (i = 0; i < nrc; i++) {
    int g = rcG[i];
    for (j = 0; j < gs_n[g]; j++) {
      int v = gsrcs[gs_off[g] + j], k;
      for (k = 0; k < na; k++) if (affected[k] == v) break;
      if (k == na) { if (na >= 4096) die("affected"); affected[na++] = v; }
    }
  }
  npTop = 0;
  for (i = 0; i < na; i++) {
    int v = affected[i], start = nsTop, n = 0;
    u8 l1 = 0, sh = 0;
    for (j = 0; j < gb_n[v]; j++) {
      int g = vpool[gb_off[v] + j], c = rcget(g);
      if (c <= 0) continue;
      int t = gt[g];
      if (t == v) { if (gflag[g] & 4) l1 = (u8)(c % 2); else sh = 1; }
      else { if (nsTop + 1 >= nsCap) { nsCap = nsCap ? nsCap * 2 : 1 << 16; nsPool = realloc(nsPool, sizeof(int) * nsCap); } nsPool[nsTop++] = t; n++; }
    }
    qsort(nsPool + start, n, sizeof(int), cmpint);
    int m = 0;
    for (j = 0; j < n; j++) if (!m || nsPool[start + m - 1] != nsPool[start + j]) nsPool[start + m++] = nsPool[start + j];
    nsTop = start + m;
    int same = (m == s0_n[v] && l1 == loop0[v] && sh == shl0[v] && !memcmp(nsPool + start, vpool + s0_off[v], sizeof(int) * m));
    if (same) { nsTop = start; continue; }
    newE[v] = ep; newIdx[v] = nnew;
    newS[nnew].n = m; newS[nnew].s = (int *)(intptr_t)start; newS[nnew].loop1 = l1; newS[nnew].shl = sh;
    nnew++;
  }
  for (i = 0; i < nnew; i++) newS[i].s = nsPool + (intptr_t)newS[i].s;
  if (nnew == 0) {
    if (nd >= cap_d) { cap_d = cap_d ? cap_d * 2 : 1024; d_off = realloc(d_off, sizeof(int) * cap_d); d_n = realloc(d_n, sizeof(int) * cap_d); }
    d_off[nd] = 0; d_n[nd] = 0; *map_slot(&delta_map, key, ne + 1, 0) = nd; return nd++;
  }
  /* newpred */
  for (int a = 0; a < NV; a++) if (newE[a] == ep) {
    VStruct *s = &newS[newIdx[a]];
    for (j = 0; j < s->n; j++) {
      int t = s->s[j];
      if (vs_has(vpool + s0_off[a], s0_n[a], t)) continue;
      if (npTop >= npCap) { npCap = npCap ? npCap * 2 : 1 << 14; npNext = realloc(npNext, sizeof(int) * npCap); npV = realloc(npV, sizeof(int) * npCap); }
      if (npE[t] != ep) { npE[t] = ep; npHead[t] = -1; }
      npV[npTop] = a; npNext[npTop] = npHead[t]; npHead[t] = npTop; npTop++;
    }
  }
  /* 닫힘 U */
  int nU = 0, nUL = 0, nf = 0;
/* v의 앞 꼭짓점 p마다 BODY. edge_ok = 'v가 지금 p의 후속인가'. pred0의 p는 구조가 안 바뀌었으면 늘 참이고
 * (pred0은 succ0에서 만듦), newpred의 p는 새로 생긴 간선이라 늘 참이다. 구조가 바뀐 p만 실제로 찾아본다. */
#define PRED_LOOP(v, p, BODY) do { \
    for (int _i = 0; _i < p0_n[v]; _i++) { int p = vpool[p0_off[v] + _i]; int edge_ok = newE[p] != ep || succ_has(p, v); BODY } \
    if (npE[v] == ep) for (int _k = npHead[v]; _k >= 0; _k = npNext[_k]) { int p = npV[_k]; int edge_ok = 1; BODY } } while (0)
  {
    /* add(v) */
    for (int a = 0; a < NV; a++) if (newE[a] == ep) {
      int ns = 0; stk[ns++] = a;
      while (ns) {
        int v = stk[--ns];
        if (inU[v] == ep) continue;
        inU[v] = ep; Ul[nU++] = v; front[nf++] = v;
        if (val0[v] == 0) {
          ULl[nUL++] = v;
          PRED_LOOP(v, p, { if (edge_ok) { if (ulE[p] != ep) { ulE[p] = ep; ulC[p] = 0; } ulC[p]++; }
                            if (safeE[p] == ep && inU[p] != ep && edge_ok) { if (--safeV[p] == 0) stk[ns++] = p; } });
        }
      }
    }
    while (nf) {
      int v = front[--nf];
      PRED_LOOP(v, p, {
        if (inU[p] == ep || !edge_ok) continue;
        if (val0[p] == 1) {
          if (safeE[p] != ep) {
            safeE[p] = ep;
            int c = 0;
            if (newE[p] == ep) { VStruct *s = &newS[newIdx[p]]; for (int k = 0; k < s->n; k++) { int t = s->s[k]; if (inU[t] != ep && val0[t] == 0) c++; } }
            else c = lcnt0[p] - (ulE[p] == ep ? ulC[p] : 0);   /* 원래 패 후속 중 U 안의 것(ulC)을 뺀다 */
            safeV[p] = c;
          }
          if (safeV[p] > 0) continue;
        }
        /* add(p) */
        int ns = 0; stk[ns++] = p;
        while (ns) {
          int q = stk[--ns];
          if (inU[q] == ep) continue;
          inU[q] = ep; Ul[nU++] = q; front[nf++] = q;
          if (val0[q] == 0) {
            ULl[nUL++] = q;
            PRED_LOOP(q, pp, { if (edge_ok) { if (ulE[pp] != ep) { ulE[pp] = ep; ulC[pp] = 0; } ulC[pp]++; }
                               if (safeE[pp] == ep && inU[pp] != ep && edge_ok) { if (--safeV[pp] == 0) stk[ns++] = pp; } });
          }
        }
      });
    }
  }
  /* U 안의 최소 고정점 */
  int nq = 0;
  for (i = 0; i < nU; i++) {
    int v = Ul[i], n_in = 0, hasL = 0, unk = 0;
    const int *ss; int sn; u8 l1, sh;
    if (newE[v] == ep) { VStruct *s = &newS[newIdx[v]]; ss = s->s; sn = s->n; l1 = s->loop1; sh = s->shl; }
    else { ss = vpool + s0_off[v]; sn = s0_n[v]; l1 = loop0[v]; sh = shl0[v]; }
    for (j = 0; j < sn; j++) {
      int t = ss[j];
      if (inU[t] == ep) n_in++;
      else if (val0[t] == 0) hasL = 1;
      else if (val0[t] < 0) unk = 1;
    }
    leftA[v] = n_in; blk[v] = (u8)(unk || sh); labA[v] = -1;
    if (hasL) { labA[v] = 1; stk[nq++] = v; }
    else if (n_in == 0 && !blk[v]) { labA[v] = l1 ? 1 : 0; stk[nq++] = v; }
  }
  while (nq) {
    int t = stk[--nq];
    PRED_LOOP(t, p, {
      if (inU[p] != ep || labA[p] >= 0 || !edge_ok) continue;
      if (labA[t] == 0) { labA[p] = 1; stk[nq++] = p; }
      else if (--leftA[p] == 0 && !blk[p]) {
        u8 l1 = newE[p] == ep ? newS[newIdx[p]].loop1 : loop0[p];
        labA[p] = l1 ? 1 : 0; stk[nq++] = p;
      }
    });
  }
  /* 저장(꼭짓점 순) */
  qsort(Ul, nU, sizeof(int), cmpint);
  if (dtop + nU >= dcap) { while (dtop + nU >= dcap) dcap = dcap ? dcap * 2 : 1 << 16; dpool_v = realloc(dpool_v, sizeof(int) * dcap); dpool_l = realloc(dpool_l, dcap); }
  if (nd >= cap_d) { cap_d = cap_d ? cap_d * 2 : 1024; d_off = realloc(d_off, sizeof(int) * cap_d); d_n = realloc(d_n, sizeof(int) * cap_d); }
  d_off[nd] = (int)dtop; d_n[nd] = nU;
  for (i = 0; i < nU; i++) { dpool_v[dtop] = Ul[i]; dpool_l[dtop] = (signed char)labA[Ul[i]]; dtop++; }
  *map_slot(&delta_map, key, ne + 1, 0) = nd;
  return nd++;
}

/* 받은 음절 x의 보호막 0 판정: 1 W, 0 L, -1 미정 */
static int label_of(int x, const Set *used) {
  int v = srv[x];
  if (v < 0) return -1;
  Set sens; sens.n = 0;
  for (int i = 0; i < used->n; i++) if (sensitive(used->w[i])) sens.w[sens.n++] = used->w[i];
  int d = delta(&sens);
  if (d >= 0) {
    int lo = d_off[d], hi = d_off[d] + d_n[d] - 1;
    while (lo <= hi) { int m = (lo + hi) >> 1; if (dpool_v[m] == v) return dpool_l[m]; if (dpool_v[m] < v) lo = m + 1; else hi = m - 1; }
  }
  return val0[v];
}

/* ── 판정 근거(why) ─────────────────────────────── */
enum { W_NOWORD, W_STATIC, W_ROUTE_FRESH, W_ROUTE_CALC, W_CYC, W_UNKNOWN_CYC, W_NO_MOVE, W_WORD, W_MIXED, W_ALL_LOSE };
typedef struct { signed char v; u8 kind; int a, b; int wy, ww; } Res;   /* v: 1 W, 0 L, -1 미정 */

/* ── 루트전 ─────────────────────────────────────── */
static Map route_map;
static signed char *rvals; static int nrv, caprv;
static long route_calls;
static Res route_value(int x, const Set *used) {
  int ru[MAXU + 64], n = 0, i;
  for (i = 0; i < NBU; i++) ru[n++] = bu[i];
  for (i = 0; i < used->n; i++) if (wroute[used->w[i]] >= 0) ru[n++] = wroute[used->w[i]];
  Res r = { 0, W_ROUTE_FRESH, 0, 0, -1, -1 };
  if (n == 0) { r.v = sroute[x]; return r; }
  qsort(ru, n, sizeof(int), cmpint);
  int key[MAXU + 66]; key[0] = 4; key[1] = x; memcpy(key + 2, ru, sizeof(int) * n);
  int *slot = map_slot(&route_map, key, n + 2, 1);
  if (*slot < 0) {
    memcpy(rawc, full, G);
    for (i = 0; i < n; i++) rawc[rwg[ru[i]]]--;
    rawcur = smv[x];
    int v;
    do v = position_value(1u << 30); while (v < 0);
    route_calls++;
    if (nrv >= caprv) { caprv = caprv ? caprv * 2 : 1024; rvals = realloc(rvals, caprv); }
    rvals[nrv] = (signed char)v; *slot = nrv++;
  }
  r.v = rvals[*slot]; r.kind = W_ROUTE_CALC; r.a = n;
  return r;
}

/* ── 보호막 0 판정(oracle)과 순환 음절 탐색 ──────── */
static Map cyc_map; static signed char *cvals; static int ncv, capcv;
static Res oracle(int x, const Set *used);
static int cyc_value(int x, const Set *used) {
  int key[MAXU + 2]; key[0] = 5; key[1] = x; memcpy(key + 2, used->w, sizeof(int) * used->n);
  int *slot = map_slot(&cyc_map, key, used->n + 2, 0);
  if (slot && *slot >= 0) return cvals[*slot];
  int res = 0, unknown = 0;
  for (int e = sm_off[x]; e < sm_off[x] + sm_n[x] && res == 0; e++) {
    int y = me_y[e];
    for (int k = 0; k < me_n[e]; k++) {
      int w = mwords[me_off[e] + k];
      if (set_has(used, w)) continue;
      Set cu; int cv;
      if (scyc[y]) { set_add(used, w, &cu); cv = cyc_value(y, &cu); }
      else { child_used(used, w, &cu); cv = oracle(y, &cu).v; }
      if (cv == 0) { res = 1; break; }
      if (cv != 1) unknown = 1;
    }
  }
  if (res == 0 && unknown) res = -1;
  slot = map_slot(&cyc_map, key, used->n + 2, 1);
  if (ncv >= capcv) { capcv = capcv ? capcv * 2 : 1024; cvals = realloc(cvals, capcv); }
  cvals[ncv] = (signed char)res; *slot = ncv++;
  return res;
}
static int has_unused_word(int x, const Set *used) {
  for (int e = sm_off[x]; e < sm_off[x] + sm_n[x]; e++)
    for (int k = 0; k < me_n[e]; k++) if (!set_has(used, mwords[me_off[e] + k])) return 1;
  return 0;
}
static Res oracle(int x, const Set *used) {
  Res r = { -1, W_UNKNOWN_CYC, 0, 0, -1, -1 };
  int lab = label_of(x, used);
  if (lab >= 0) {
    r.v = (signed char)lab;
    r.kind = (lab == 0 && !has_unused_word(x, used)) ? W_NOWORD : W_STATIC;
    return r;
  }
  if (sroute[x] >= 0) return route_value(x, used);
  if (scyc[x]) {
    int v = cyc_value(x, used);
    if (v >= 0) { r.v = (signed char)v; r.kind = W_CYC; return r; }
  }
  return r;
}

/* ── 보호막 1 이상: 한 수씩 ─────────────────────── */
typedef struct { int y, w, e; } Choice;   /* e: 끝 음절 칸(같은 단어 목록 표시용) */
static int choices(int x, int s, const Set *used, Choice *out, int maxo) {
  int n = 0;
  for (int e = sm_off[x]; e < sm_off[x] + sm_n[x]; e++) {
    int y = me_y[e], any = 0, k;
    for (k = 0; k < me_n[e]; k++) if (!set_has(used, mwords[me_off[e] + k])) { any = 1; break; }
    if (!any || scont[y] < s) continue;
    for (k = 0; k < me_n[e]; k++) {
      int w = mwords[me_off[e] + k];
      if (!set_has(used, w) && !tracked(w)) { if (n >= maxo) die("choices"); out[n].y = y; out[n].w = w; out[n].e = e; n++; break; }
    }
    int seen[256], ns = 0;
    for (k = 0; k < me_n[e]; k++) {
      int w = mwords[me_off[e] + k];
      if (set_has(used, w) || !tracked(w)) continue;
      int key = wroute[w] >= 0 ? -(w + 1) : wgrp[w], j;
      for (j = 0; j < ns; j++) if (seen[j] == key) break;
      if (j < ns) continue;
      if (ns < 256) seen[ns++] = key;
      if (n >= maxo) die("choices");
      out[n].y = y; out[n].w = w; out[n].e = -1; n++;
    }
  }
  return n;
}
static int base_label(int y) { return srv[y] >= 0 ? val0[srv[y]] : -1; }
static int ord_t;
static int nchoice_at(int y, int t) {
  int n = 0;
  for (int e = sm_off[y]; e < sm_off[y] + sm_n[y]; e++) if (scont[me_y[e]] >= t) n++;
  return n;
}
typedef struct { int a, n, y, idx; Choice c; } Ord;
static int cmpord(const void *p, const void *q) {
  const Ord *a = p, *b = q;
  if (a->a != b->a) return a->a - b->a;
  if (a->n != b->n) return a->n - b->n;
  if (a->y != b->y) return a->y - b->y;
  return a->idx - b->idx;
}

static Map val_map; static Res *vres; static int nvr, capvr;
/* 이기는 수 순서 도움(killer): 같은 보호막에서 최근에 이긴 수(끝 음절, 단어)를 먼저 둬 본다.
 * 찾는 순서만 바꾸므로 값은 그대로다(승 자리는 이기는 수 하나, 패 자리는 모든 수를 본다). */
#define NKILL 2
static int kill_y[64][NKILL], kill_w[64][NKILL];
static int use_killer = 1;
static long nodes_searched;
static Res value(int x, int s, const Set *used) {
  if (s < 0) s = 0;
  int key[MAXU + 3]; key[0] = 1; key[1] = x; key[2] = s; memcpy(key + 3, used->w, sizeof(int) * used->n);
  int *slot = map_slot(&val_map, key, used->n + 3, 0);
  if (slot && *slot >= 0) return vres[*slot];
  Res r;
  nodes_searched++;
  if (s == 0) r = oracle(x, used);
  else {
    static Choice chbuf[64][4096];
    if (s >= 64) die("shield");
    Choice *ch = chbuf[s];
    int n = choices(x, s, used, ch, 4096), i;
    if (n == 0) { r.v = 0; r.kind = W_NO_MOVE; r.a = s; r.b = 0; r.wy = r.ww = -1; }
    else {
      Ord *o = xm(sizeof(Ord) * n);
      int t = s - 1;
      for (i = 0; i < n; i++) {
        o[i].c = ch[i]; o[i].idx = i; o[i].y = ch[i].y;
        if (t == 0) {
          /* 보호막 0 자식: 값이 싸게 나오는 것부터(전체 사전 판정이 패 → 판정 있음 → 루트 계산이 필요 없는 것 → 루트 계산) */
          o[i].a = 0; o[i].n = 0;
          if (use_killer) {   /* 쓴 단어를 빼기 전 판정만 본다(다시 판정하면 오히려 느림) */
            int lab = base_label(ch[i].y);
            if (lab == 0) o[i].a = 0;
            else if (lab == 1) o[i].a = 3;
            else if (sroute[ch[i].y] >= 0) o[i].a = sroute[ch[i].y] == 0 ? 1 : 2;
            else o[i].a = 1;
          }
        }
        else { o[i].a = base_label(ch[i].y) == 0 ? 0 : 1; o[i].n = nchoice_at(ch[i].y, t); }
      }
      qsort(o, n, sizeof(Ord), cmpord);
      if (use_killer) {
        int front_n = 0;
        for (int k = 0; k < NKILL; k++) {
          for (int j = front_n; j < n; j++) if (o[j].c.y == kill_y[s][k] && o[j].c.w == kill_w[s][k] && kill_w[s][k] >= 0) {
            Ord tmp = o[j]; memmove(o + front_n + 1, o + front_n, sizeof(Ord) * (j - front_n)); o[front_n++] = tmp; break;
          }
        }
      }
      int unknown = 0, found = 0;
      for (i = 0; i < n && !found; i++) {
        Set cu; child_used(used, o[i].c.w, &cu);
        Res c = value(o[i].c.y, t, &cu);
        if (c.v == 0) {
          r.v = 1; r.kind = W_WORD; r.a = o[i].c.w; r.b = o[i].c.y; r.wy = o[i].c.y; r.ww = o[i].c.w; found = 1;
          if (use_killer && !(kill_y[s][0] == o[i].c.y && kill_w[s][0] == o[i].c.w)) {
            kill_y[s][1] = kill_y[s][0]; kill_w[s][1] = kill_w[s][0]; kill_y[s][0] = o[i].c.y; kill_w[s][0] = o[i].c.w;
          }
        }
        else if (c.v < 0) unknown = 1;
      }
      free(o);
      if (!found) {
        r.wy = r.ww = -1; r.b = 0;
        if (unknown) { r.v = -1; r.kind = W_MIXED; r.a = 0; }
        else { r.v = 0; r.kind = W_ALL_LOSE; r.a = n; }
      }
    }
  }
  slot = map_slot(&val_map, key, used->n + 3, 1);
  if (nvr >= capvr) { capvr = capvr ? capvr * 2 : 1 << 16; vres = realloc(vres, sizeof(Res) * capvr); }
  vres[nvr] = r; *slot = nvr++;
  return r;
}

static FILE *OUT;   /* JSON을 쓰는 곳(기본 stdout, 나눠 돌리기에서는 수마다 파일) */
#define PUTC(c) fputc((c), OUT)
/* ── JSON 출력 ─────────────────────────────────── */
static void js(const char *s) {
  PUTC('"');
  for (; *s; s++) { if (*s == '"' || *s == '\\') PUTC('\\'); PUTC(*s); }
  PUTC('"');
}
static const char *vstr(int v) { return v == 1 ? "W" : v == 0 ? "L" : "?"; }
static void why_str(const Res *r, char *buf, size_t n) {
  switch (r->kind) {
    case W_NOWORD: snprintf(buf, n, "보호막 0 판정: 낼 단어 없음"); break;
    case W_STATIC: snprintf(buf, n, "보호막 0 판정(전체 사전)"); break;
    case W_ROUTE_FRESH: snprintf(buf, n, "루트전 결과(확정)"); break;
    case W_ROUTE_CALC: snprintf(buf, n, "루트전 계산(쓴 루트 단어 %d개 반영)", r->a); break;
    case W_CYC: snprintf(buf, n, "루트 밖 순환 음절: 단어를 하나씩 두어 본 탐색"); break;
    case W_UNKNOWN_CYC: snprintf(buf, n, "미정(루트 밖 순환)"); break;
    case W_NO_MOVE: snprintf(buf, n, "보호막 %d에서 낼 수 있는 단어 없음", r->a); break;
    case W_WORD: snprintf(buf, n, "%s(→%s)", wstr[r->a], sstr[r->b]); break;
    case W_MIXED: snprintf(buf, n, "미정이 섞임"); break;
    case W_ALL_LOSE: snprintf(buf, n, "낼 수 있는 수 %d가지가 모두 상대 승", r->a); break;
  }
}
static void key_str(int y, int t, const Set *u) {
  fprintf(OUT, "\"%s|%d|", sstr[y], t);
  for (int i = 0; i < u->n; i++) { if (i) PUTC(','); fputs(wstr[u->w[i]], OUT); }
  PUTC('"');
}

/* 판정 근거 자리 모으기(Python certificate와 같은 순회) */
typedef struct { int y, t; Set u; } Todo;
static Map cert_map;
static void certificate(int x, int s, const Set *u0) {
  Todo *todo = xm(sizeof(Todo) * 1024); int cap = 1024, nt = 0, first = 1;
  todo[nt].y = x; todo[nt].t = s; todo[nt].u = *u0; nt++;
  char buf[2048];
  static Choice ch[4096];
  fprintf(OUT, "\"nodes\":{");
  while (nt) {
    Todo it = todo[--nt];
    int key[MAXU + 3]; key[0] = 9; key[1] = it.y; key[2] = it.t; memcpy(key + 3, it.u.w, sizeof(int) * it.u.n);
    int *slot = map_slot(&cert_map, key, it.u.n + 3, 1);
    if (*slot >= 0) continue;
    *slot = 1;
    Res r = value(it.y, it.t, &it.u);
    if (!first) PUTC(',');
    first = 0;
    key_str(it.y, it.t, &it.u);
    fprintf(OUT, ":{\"x\":"); js(sstr[it.y]); fprintf(OUT, ",\"t\":%d,\"used\":[", it.t);
    for (int i = 0; i < it.u.n; i++) { if (i) PUTC(','); js(wstr[it.u.w[i]]); }
    why_str(&r, buf, sizeof buf);
    fprintf(OUT, "],\"v\":\"%s\",\"why\":", vstr(r.v)); js(buf);
    if (it.t == 0) fprintf(OUT, ",\"leaf\":true");
    else if (r.v == 1) {
      Set cu; child_used(&it.u, r.ww, &cu);
      fprintf(OUT, ",\"word\":"); js(wstr[r.ww]); fprintf(OUT, ",\"child\":"); key_str(r.wy, it.t - 1, &cu);
      if (nt + 1 >= cap) { cap *= 2; todo = realloc(todo, sizeof(Todo) * cap); }
      todo[nt].y = r.wy; todo[nt].t = it.t - 1; todo[nt].u = cu; nt++;
    } else if (r.v == 0) {
      int n = choices(it.y, it.t, &it.u, ch, 4096);
      fprintf(OUT, ",\"words\":[");
      for (int i = 0; i < n; i++) { if (i) PUTC(','); js(wstr[ch[i].w]); }
      PUTC(']');
      for (int i = 0; i < n; i++) {
        Set cu; child_used(&it.u, ch[i].w, &cu);
        if (nt + 1 >= cap) { cap *= 2; todo = realloc(todo, sizeof(Todo) * cap); }
        todo[nt].y = ch[i].y; todo[nt].t = it.t - 1; todo[nt].u = cu; nt++;
      }
    }
    PUTC('}');
  }
  fprintf(OUT, "}");
  free(todo);
}

/* 보호막 0에서 이기는 단어 하나(표시용, Calc.win_at0) */
static int win_at0(int x, const Set *used, int *wy) {
  static Choice ch[4096];
  if (value(x, 0, used).v != 1) return -1;
  int n = choices(x, 0, used, ch, 4096);
  for (int i = 0; i < n; i++) {
    Set cu; child_used(used, ch[i].w, &cu);
    if (oracle(ch[i].y, &cu).v == 0) { *wy = ch[i].y; return ch[i].w; }
  }
  return -1;
}

static void alloc_work(void) {
  ulE = calloc(NV, 4); ulC = xm(4 * NV);
  inU = calloc(NV, 4); safeE = calloc(NV, 4); newE = calloc(NV, 4); rcE = calloc(NGR, 4); npE = calloc(NV, 4);
  safeV = xm(4 * NV); newIdx = xm(4 * NV); rcV = xm(4 * NGR); labA = xm(4 * NV); leftA = xm(4 * NV); blk = xm(NV);
  stk = xm(4 * (NV * 4 + 16)); front = xm(4 * (NV * 4 + 16)); ULl = xm(4 * (NV + 16)); Ul = xm(4 * (NV + 16));
  newS = xm(sizeof(VStruct) * NV); rcG = xm(4 * NGR); npHead = xm(4 * NV);
  map_init(&delta_map, 1 << 12); map_init(&route_map, 1 << 10); map_init(&cyc_map, 1 << 10);
  map_init(&val_map, 1 << 16); map_init(&cert_map, 1 << 12);
}

static int syl_id(const char *s) {
  int lo = 0, hi = NS - 1;
  while (lo <= hi) { int m = (lo + hi) >> 1, c = strcmp(sstr[m], s); if (!c) return m; if (c < 0) lo = m + 1; else hi = m - 1; }
  return -1;
}

/* usage: shield_engine MODEL SYLLABLE T [all | list | part I,J,K OUTDIR]
 *   T = 받은 쪽의 보호막. all이면 이기는 수를 찾은 뒤에도 첫 자리의 모든 수를 분류. */
int main(int argc, char **argv) {
  if (argc < 4) { fprintf(stderr, "usage: shield_engine MODEL SYLLABLE T [all]\n"); return 2; }
  OUT = stdout;
  load_model(argv[1]);
  alloc_work();
  for (int a = 0; a < 64; a++) for (int k = 0; k < NKILL; k++) { kill_y[a][k] = -1; kill_w[a][k] = -1; }
  if (getenv("SHIELD_NO_KILLER")) use_killer = 0;
  int x = syl_id(argv[2]), t = atoi(argv[3]), all = argc > 4 && !strcmp(argv[4], "all");
  if (x < 0) { fprintf(OUT, "{\"error\":\"unknown syllable\"}\n"); return 0; }
  Set u0; u0.n = 0;
  if (argc > 4 && !strcmp(argv[4], "list")) {
    /* 첫 자리(보호막 t에서 x를 받음)의 수 목록: 나눠 돌리기용 */
    static Choice cl[4096];
    int n = choices(x, t, &u0, cl, 4096);
    /* value()와 같은 순서(유망한 수부터)로 내보낸다. 번호 i는 choices 순서 그대로. */
    Ord *o = xm(sizeof(Ord) * (n + 1));
    for (int i = 0; i < n; i++) {
      o[i].c = cl[i]; o[i].idx = i; o[i].y = cl[i].y;
      if (t - 1 <= 0) { int lab = base_label(cl[i].y); o[i].n = 0;
        o[i].a = lab == 0 ? 0 : lab == 1 ? 3 : sroute[cl[i].y] >= 0 ? (sroute[cl[i].y] == 0 ? 1 : 2) : 1; }
      else { o[i].a = base_label(cl[i].y) == 0 ? 0 : 1; o[i].n = nchoice_at(cl[i].y, t - 1); }
    }
    qsort(o, n, sizeof(Ord), cmpord);
    fprintf(OUT, "[");
    for (int j = 0; j < n; j++) {
      int i = o[j].idx;
      Set cu; child_used(&u0, cl[i].w, &cu);
      if (j) PUTC(',');
      fprintf(OUT, "{\"i\":%d,\"end\":", i); js(sstr[cl[i].y]); fprintf(OUT, ",\"word\":"); js(wstr[cl[i].w]);
      fprintf(OUT, ",\"child\":"); key_str(cl[i].y, t - 1, &cu); PUTC('}');
    }
    fprintf(OUT, "]\n");
    return 0;
  }
  if (argc > 6 && !strcmp(argv[4], "part")) {
    /* 정해 준 수만: 수마다 상대 자리(보호막 t-1)의 값과 그 판정 근거를 OUTDIR/move_<i>.json에 따로 쓴다.
     * 같은 프로세스 안에서 앞 수의 파일에 이미 쓴 자리는 다시 쓰지 않는다(모두 합치면 빠짐없음). */
    static Choice cl[4096];
    int n = choices(x, t, &u0, cl, 4096);
    char *list = strdup(argv[5]), *tok, path[4096], tmp[4200];
    for (tok = strtok(list, ","); tok; tok = strtok(NULL, ",")) {
      int i = atoi(tok);
      if (i < 0 || i >= n) die("move index");
      snprintf(path, sizeof path, "%s/move_%d.json", argv[6], i);
      if (!access(path, F_OK)) continue;   /* 이미 끝난 수(다시 시작했을 때) */
      Set cu; child_used(&u0, cl[i].w, &cu);
      Res c = value(cl[i].y, t - 1, &cu);
      snprintf(tmp, sizeof tmp, "%s.tmp", path);
      OUT = fopen(tmp, "w");
      if (!OUT) die("open move file");
      char wb[2048]; why_str(&c, wb, sizeof wb);
      fprintf(OUT, "{\"i\":%d,\"end\":", i); js(sstr[cl[i].y]); fprintf(OUT, ",\"word\":"); js(wstr[cl[i].w]);
      fprintf(OUT, ",\"value\":\"%s\",\"why\":", vstr(c.v)); js(wb);
      fprintf(OUT, ",\"child\":"); key_str(cl[i].y, t - 1, &cu); PUTC(',');
      certificate(cl[i].y, t - 1, &cu);
      fprintf(OUT, ",\"stats\":{\"positions\":%d,\"route_solves\":%ld}}\n", nvr, route_calls);
      fclose(OUT);
      OUT = stdout;
      rename(tmp, path);
      fprintf(stderr, "move %d %s %s -> %s\n", i, sstr[cl[i].y], wstr[cl[i].w], vstr(c.v));
    }
    return 0;
  }
  Res r = value(x, t, &u0);
  char buf[2048];
  why_str(&r, buf, sizeof buf);
  fprintf(OUT, "{\"value\":\"%s\",\"why\":", vstr(r.v)); js(buf);
  if (r.v == 1 && r.ww >= 0) { fprintf(OUT, ",\"win\":["); js(sstr[r.wy]); PUTC(','); js(wstr[r.ww]); PUTC(']'); }
  else fprintf(OUT, ",\"win\":null");
  /* 첫 자리의 수 분류(Calc.classify) */
  int partial = r.v == 1 && r.ww >= 0 && !all;
  static Choice ch[4096];
  int n = choices(x, t, &u0, ch, 4096);
  fprintf(OUT, ",\"rows\":[");
  int firstrow = 1;
  for (int i = 0; i < n; i++) {
    if (partial && !(ch[i].y == r.wy && ch[i].w == r.ww)) continue;
    Set cu; child_used(&u0, ch[i].w, &cu);
    Res c = value(ch[i].y, t - 1, &cu);
    int wy = c.wy, ww = c.ww;
    if (ww < 0 && c.v == 1 && t - 1 <= 0) ww = win_at0(ch[i].y, &cu, &wy);
    if (!firstrow) PUTC(',');
    firstrow = 0;
    fprintf(OUT, "{\"end\":"); js(sstr[ch[i].y]); fprintf(OUT, ",\"word\":"); js(wstr[ch[i].w]); fprintf(OUT, ",\"words\":[");
    if (ch[i].e >= 0) {
      int fw = 1, e = ch[i].e;
      for (int k = 0; k < me_n[e]; k++) {
        int w = mwords[me_off[e] + k];
        if (set_has(&u0, w) || tracked(w)) continue;
        if (!fw) PUTC(',');
        fw = 0; js(wstr[w]);
      }
    } else js(wstr[ch[i].w]);
    why_str(&c, buf, sizeof buf);
    fprintf(OUT, "],\"cont\":%d,\"value\":\"%s\",\"why\":", scont[ch[i].y], vstr(c.v)); js(buf);
    fprintf(OUT, ",\"winning_word\":");
    if (ww >= 0) js(wstr[ww]); else fprintf(OUT, "null");
    PUTC('}');
  }
  fprintf(OUT, "],\"blocked\":[");
  int fb = 1;
  for (int e = sm_off[x]; e < sm_off[x] + sm_n[x]; e++) {
    int y = me_y[e];
    if (scont[y] >= t) continue;
    int any = 0;
    for (int k = 0; k < me_n[e]; k++) if (!set_has(&u0, mwords[me_off[e] + k])) any = 1;
    if (!any) continue;
    if (!fb) PUTC(',');
    fb = 0;
    fprintf(OUT, "["); js(sstr[y]); fprintf(OUT, ",%d,[", scont[y]);
    int fw = 1;
    for (int k = 0; k < me_n[e]; k++) { int w = mwords[me_off[e] + k]; if (set_has(&u0, w)) continue; if (!fw) PUTC(','); fw = 0; js(wstr[w]); }
    fprintf(OUT, "]]");
  }
  fprintf(OUT, "],\"cycle\":[");
  int fc = 1;
  for (int i = 0; i < NS; i++) if (scyc[i]) { if (!fc) PUTC(','); fc = 0; js(sstr[i]); }
  fprintf(OUT, "],");
  certificate(x, t, &u0);
  fprintf(OUT, ",\"stats\":{\"positions\":%d,\"searched\":%ld,\"delta_sets\":%d,\"route_solves\":%ld,\"cycle_positions\":%d}}\n",
         nvr, nodes_searched, nd, route_calls, ncv);
  return 0;
}
