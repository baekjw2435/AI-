/* Optional C engine for verify_fast.py: route-proof-v2 canonicalization only.
 * Written independently of solver_v2.cpp (no shared code).  Static labels use
 * Gauss-Seidel sweeps of the fixed-point rules (not the solver's counter queue).
 * Build: gcc -O2 -shared -fPIC -o fastnorm.so fastnorm.c
 */
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

static int V = 0, G = 0, NP = 0, NL = 0;
static int *SRC, *DST, *LO, *HI, *PA, *PB, *LOOPS;
static uint8_t *C;      /* working counts */
static int8_t *LAB;     /* -1 unknown, 0 L, 1 W */
static uint8_t *MARK;   /* reachability / core marks */
static int *QUEUE, *PEND;

static int *dup(const int *x, int n) {
    int *r = (int *)malloc(sizeof(int) * (n > 0 ? n : 1));
    if (r && n > 0) memcpy(r, x, sizeof(int) * n);
    return r;
}

int fn_init(int v, int g, const int *src, const int *dst, const int *lo, const int *hi,
            int np, const int *pa, const int *pb, int nl, const int *loops) {
    V = v; G = g; NP = np; NL = nl;
    SRC = dup(src, g); DST = dup(dst, g); LO = dup(lo, v); HI = dup(hi, v);
    PA = dup(pa, np); PB = dup(pb, np); LOOPS = dup(loops, nl);
    C = (uint8_t *)malloc(g > 0 ? g : 1);
    LAB = (int8_t *)malloc(v); MARK = (uint8_t *)malloc(v);
    QUEUE = (int *)malloc(sizeof(int) * v); PEND = (int *)malloc(sizeof(int) * v);
    return (SRC && DST && LO && HI && PA && PB && LOOPS && C && LAB && MARK && QUEUE && PEND) ? 0 : -1;
}

/* Returns -1 (unresolved core), 0 (static L) or 1 (static W); writes canonical counts. */
int fn_normalize(int current, const uint8_t *in, uint8_t *out) {
    int i, k, n, head;
    memcpy(C, in, (size_t)G);
    for (k = 0; k < NP; k++) {               /* reciprocal pairs */
        uint8_t a = C[PA[k]], b = C[PB[k]], m = a < b ? a : b;
        C[PA[k]] = (uint8_t)(a - m); C[PB[k]] = (uint8_t)(b - m);
    }
    for (k = 0; k < NL; k++) C[LOOPS[k]] = (uint8_t)(C[LOOPS[k]] % 2);   /* loop parity */
    memset(MARK, 0, (size_t)V);              /* forward reachability */
    n = 0; QUEUE[n++] = current; MARK[current] = 1;
    for (head = 0; head < n; head++) {
        int s = QUEUE[head];
        for (i = LO[s]; i < HI[s]; i++)
            if (C[i] && !MARK[DST[i]]) { MARK[DST[i]] = 1; QUEUE[n++] = DST[i]; }
    }
    memset(LAB, -1, (size_t)V);              /* least fixed point, sweeps */
    int np = n;
    memcpy(PEND, QUEUE, sizeof(int) * (size_t)n);
    for (;;) {
        int rest = 0, changed = 0;
        for (k = 0; k < np; k++) {
            int s = PEND[k], losing = 0, allwin = 1, loop = 0;
            for (i = LO[s]; i < HI[s]; i++) {
                if (!C[i]) continue;
                int t = DST[i];
                if (t == s) { loop = 1; continue; }
                if (LAB[t] == 0) { losing = 1; break; }
                if (LAB[t] != 1) allwin = 0;
            }
            if (losing) { LAB[s] = 1; changed = 1; }
            else if (allwin) { LAB[s] = (int8_t)loop; changed = 1; }
            else PEND[rest++] = s;
        }
        np = rest;
        if (!changed || !np) break;
    }
    memset(out, 0, (size_t)G);
    if (LAB[current] != -1) {                /* static: reachable counts kept */
        for (k = 0; k < n; k++) {
            int s = QUEUE[k];
            for (i = LO[s]; i < HI[s]; i++) out[i] = C[i];
        }
        return LAB[current];
    }
    memset(MARK, 0, (size_t)V);              /* unknown core */
    n = 0; QUEUE[n++] = current; MARK[current] = 1;
    for (head = 0; head < n; head++) {
        int s = QUEUE[head];
        for (i = LO[s]; i < HI[s]; i++) {
            int t = DST[i];
            if (C[i] && LAB[t] == -1) {
                out[i] = C[i];
                if (!MARK[t]) { MARK[t] = 1; QUEUE[n++] = t; }
            }
        }
    }
    return -1;
}
