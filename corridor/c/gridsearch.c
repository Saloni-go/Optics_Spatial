/* Track 3 - compiled grid route search (Dijkstra, A*, landmark A*) on the implicit 8-connected DEM grid.
 *
 * Same cost model as corridor/optimizer.py:
 *     c(u, v) = L_uv * (1 + alpha * (E_u + E_v) / 2) + beta * max(0, z_v - z_u)
 * with L_uv = cell or cell*sqrt(2), and blocked cells never entered.
 *
 * The graph is never stored: neighbours and edge costs are computed from the grid on the fly, so
 * memory is a few arrays of N values instead of SciPy's explicit sparse graph (8 edges per node).
 *
 * Build (MinGW-w64 GCC):  gcc -O3 -shared -o gridsearch.dll gridsearch.c
 * Called from Python through ctypes (corridor/cgrid.py); ctypes releases the GIL during calls, so
 * independent searches (e.g. landmark preprocessing) can run on several threads.
 */
#include <math.h>
#include <stdint.h>
#include <stdlib.h>

#ifdef _WIN32
#define EXPORT __declspec(dllexport)
#else
#define EXPORT
#endif

static const int DR[8] = {-1, -1, -1, 0, 0, 1, 1, 1};
static const int DC[8] = {-1, 0, 1, -1, 1, -1, 0, 1};

/* ------------------------------------------------------------------ binary min-heap (lazy deletion) */
typedef struct { double f; double g; int32_t v; } item;
typedef struct { item *a; int64_t n, cap; } heap;

static int less(const item *x, const item *y) {
    /* order by f; on ties prefer the larger g (deeper node), which speeds A* up on plateaus */
    return x->f < y->f || (x->f == y->f && x->g > y->g);
}

static int hpush(heap *h, double f, double g, int32_t v) {
    if (h->n == h->cap) {
        int64_t cap = h->cap ? h->cap * 2 : (1 << 16);
        item *a = (item *)realloc(h->a, (size_t)cap * sizeof(item));
        if (!a) return -1;
        h->a = a; h->cap = cap;
    }
    item it = {f, g, v};
    int64_t i = h->n++;
    while (i > 0) {
        int64_t p = (i - 1) >> 1;
        if (!less(&it, &h->a[p])) break;
        h->a[i] = h->a[p]; i = p;
    }
    h->a[i] = it;
    return 0;
}

static item hpop(heap *h) {
    item top = h->a[0];
    item last = h->a[--h->n];
    if (h->n == 0) return top;
    int64_t i = 0;
    for (;;) {
        int64_t c = 2 * i + 1;
        if (c >= h->n) break;
        if (c + 1 < h->n && less(&h->a[c + 1], &h->a[c])) c++;
        if (!less(&h->a[c], &last)) break;
        h->a[i] = h->a[c]; i = c;
    }
    h->a[i] = last;
    return top;
}

/* ------------------------------------------------------------------ heuristics */
typedef struct {
    int mode;                 /* 0 none (Dijkstra), 1 straight line + climb, 2 = 1 + landmarks (ALT) */
    int32_t W, gr, gc, g;
    double cell, beta, zg;
    int32_t K; int64_t N;
    const float *fwd, *bwd;   /* K x N: d(L_k, v) and d(v, L_k) */
} heur;

static double h_of(const heur *H, const double *z, int32_t u) {
    if (H->mode == 0) return 0.0;
    int32_t r = u / H->W, c = u % H->W;
    double dz = H->zg - z[u];
    double h = hypot((double)(r - H->gr), (double)(c - H->gc)) * H->cell + (dz > 0 ? H->beta * dz : 0.0);
    if (H->mode == 2) {
        for (int k = 0; k < H->K; k++) {
            const float *f = H->fwd + (int64_t)k * H->N, *b = H->bwd + (int64_t)k * H->N;
            /* d(u,g) >= d(u,L) - d(g,L)   and   d(u,g) >= d(L,g) - d(L,u);  -1: float32 rounding margin */
            if (isfinite(b[u]) && isfinite(b[H->g])) { double t = (double)b[u] - b[H->g] - 1.0; if (t > h) h = t; }
            if (isfinite(f[H->g]) && isfinite(f[u])) { double t = (double)f[H->g] - f[u] - 1.0; if (t > h) h = t; }
        }
    }
    return h;
}

/* ------------------------------------------------------------------ single-pair search
 * Returns the number of path nodes written to path_out (start..goal), 0 if the goal is
 * unreachable, -1 on allocation failure, or -(needed length) if path_cap is too small. */
EXPORT int64_t grid_search(int32_t Hh, int32_t W, const double *z, const double *E, const uint8_t *blocked,
                           double cell, double alpha, double beta, int32_t start, int32_t goal,
                           int32_t hmode, double weight, int32_t K, const float *fwd, const float *bwd,
                           double *cost_out, int64_t *expanded_out, int32_t *path_out, int64_t path_cap) {
    int64_t N = (int64_t)Hh * W;
    double *dist = (double *)malloc((size_t)N * sizeof(double));
    int32_t *parent = (int32_t *)malloc((size_t)N * sizeof(int32_t));
    uint8_t *closed = (uint8_t *)calloc((size_t)N, 1);
    heap hp = {0};
    if (!dist || !parent || !closed) { free(dist); free(parent); free(closed); return -1; }
    for (int64_t i = 0; i < N; i++) { dist[i] = INFINITY; parent[i] = -1; }

    heur H = {hmode, W, goal / W, goal % W, goal, cell, beta, z[goal], K, N, fwd, bwd};
    const double sq2 = 1.4142135623730951;
    int64_t expanded = 0;
    dist[start] = 0.0;
    hpush(&hp, weight * h_of(&H, z, start), 0.0, start);
    while (hp.n > 0) {
        item it = hpop(&hp);
        int32_t u = it.v;
        if (closed[u]) continue;
        closed[u] = 1; expanded++;
        if (u == goal) break;
        int32_t ur = u / W, uc = u % W;
        double du = dist[u], zu = z[u], eu = E[u];
        for (int k = 0; k < 8; k++) {
            int32_t vr = ur + DR[k], vc = uc + DC[k];
            if (vr < 0 || vr >= Hh || vc < 0 || vc >= W) continue;
            int32_t v = vr * W + vc;
            if (blocked[v] || closed[v]) continue;
            double lf = (DR[k] && DC[k]) ? sq2 : 1.0;
            double dz = z[v] - zu;
            double nd = du + lf * cell * (1.0 + alpha * 0.5 * (eu + E[v])) + (dz > 0 ? beta * dz : 0.0);
            if (nd < dist[v]) {
                dist[v] = nd; parent[v] = u;
                if (hpush(&hp, nd + weight * h_of(&H, z, v), nd, v)) { expanded = -1; goto done; }
            }
        }
    }
done:;
    int64_t len = 0;
    *expanded_out = expanded;
    *cost_out = dist[goal];
    if (expanded >= 0 && isfinite(dist[goal])) {
        for (int32_t v = goal; v != -1; v = parent[v]) len++;
        if (len > path_cap) { len = -len; }
        else {
            int64_t i = len - 1;
            for (int32_t v = goal; v != -1; v = parent[v]) path_out[i--] = v;
        }
    } else if (expanded < 0) len = -1;
    free(dist); free(parent); free(closed); free(hp.a);
    return len;
}

/* ------------------------------------------------------------------ one-to-all (landmark preprocessing)
 * reverse = 0: dist_out[v] = d(source, v);  reverse = 1: dist_out[v] = d(v, source).
 * Returns the number of nodes settled, or -1 on allocation failure. */
EXPORT int64_t grid_sssp(int32_t Hh, int32_t W, const double *z, const double *E, const uint8_t *blocked,
                         double cell, double alpha, double beta, int32_t source, int32_t reverse, float *dist_out) {
    int64_t N = (int64_t)Hh * W;
    double *dist = (double *)malloc((size_t)N * sizeof(double));
    uint8_t *closed = (uint8_t *)calloc((size_t)N, 1);
    heap hp = {0};
    if (!dist || !closed) { free(dist); free(closed); return -1; }
    for (int64_t i = 0; i < N; i++) dist[i] = INFINITY;
    const double sq2 = 1.4142135623730951;
    int64_t settled = 0;
    dist[source] = 0.0;
    hpush(&hp, 0.0, 0.0, source);
    while (hp.n > 0) {
        item it = hpop(&hp);
        int32_t u = it.v;
        if (closed[u]) continue;
        closed[u] = 1; settled++;
        int32_t ur = u / W, uc = u % W;
        double du = dist[u], zu = z[u], eu = E[u];
        for (int k = 0; k < 8; k++) {
            int32_t vr = ur + DR[k], vc = uc + DC[k];
            if (vr < 0 || vr >= Hh || vc < 0 || vc >= W) continue;
            int32_t v = vr * W + vc;
            if (blocked[v] || closed[v]) continue;
            double lf = (DR[k] && DC[k]) ? sq2 : 1.0;
            /* forward: edge u->v climbs z_v - z_u; reverse: we walk the edge v->u, which climbs z_u - z_v */
            double dz = reverse ? (zu - z[v]) : (z[v] - zu);
            double nd = du + lf * cell * (1.0 + alpha * 0.5 * (eu + E[v])) + (dz > 0 ? beta * dz : 0.0);
            if (nd < dist[v]) {
                dist[v] = nd;
                if (hpush(&hp, nd, nd, v)) { settled = -1; goto done; }
            }
        }
    }
done:
    for (int64_t i = 0; i < N; i++) dist_out[i] = (float)dist[i];
    free(dist); free(closed); free(hp.a);
    return settled;
}
