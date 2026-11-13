/* Track 3 - compiled grid route search (Dijkstra, A*, landmark A*) on the implicit 8-connected DEM grid.
 *
 * Same cost model as corridor/optimizer.py:
 *     c(u, v) = L_uv * (1 + alpha * (E_u + E_v) / 2) + beta * max(0, z_v - z_u)
 * with L_uv = cell or cell*sqrt(2), and blocked cells never entered.
 *
 * The graph is never stored: neighbours and edge costs are computed from the grid on the fly, so
 * memory is a few arrays of N values instead of SciPy's explicit sparse graph (8 edges per node).
 *
 * Build (MinGW-w64 GCC):  gcc -O3 -fopenmp -shared -static -o gridsearch.dll gridsearch.c
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

/* ------------------------------------------------------------------ edge cost helpers */
static inline double edge_cost(const double *z, const double *E, double cell, double alpha, double beta,
                               int32_t from, int32_t to, double lf) {
    double dz = z[to] - z[from];
    return lf * cell * (1.0 + alpha * 0.5 * (E[from] + E[to])) + (dz > 0 ? beta * dz : 0.0);
}

/* ------------------------------------------------------------------ cost-to-go field (Level 2)
 * Backward Dijkstra from `goal`: dist_out[v] = cost of the best route v -> goal, next_out[v] = the
 * neighbour to step to (-1 at the goal or if unreachable).  Afterwards a route from ANY start is
 * found by following next_out, with no search at all.  Returns nodes settled, -1 on failure. */
EXPORT int64_t grid_costtogo(int32_t Hh, int32_t W, const double *z, const double *E, const uint8_t *blocked,
                             double cell, double alpha, double beta, int32_t goal, double *dist_out, int32_t *next_out) {
    int64_t N = (int64_t)Hh * W;
    uint8_t *closed = (uint8_t *)calloc((size_t)N, 1);
    heap hp = {0};
    if (!closed) return -1;
    for (int64_t i = 0; i < N; i++) { dist_out[i] = INFINITY; next_out[i] = -1; }
    const double sq2 = 1.4142135623730951;
    int64_t settled = 0;
    dist_out[goal] = 0.0;
    hpush(&hp, 0.0, 0.0, goal);
    while (hp.n > 0) {
        item it = hpop(&hp);
        int32_t u = it.v;
        if (closed[u]) continue;
        closed[u] = 1; settled++;
        int32_t ur = u / W, uc = u % W;
        for (int k = 0; k < 8; k++) {
            int32_t vr = ur + DR[k], vc = uc + DC[k];
            if (vr < 0 || vr >= Hh || vc < 0 || vc >= W) continue;
            int32_t v = vr * W + vc;
            if (blocked[v] || closed[v]) continue;
            /* the route runs v -> u, so the edge cost is c(v, u) */
            double nd = dist_out[u] + edge_cost(z, E, cell, alpha, beta, v, u, (DR[k] && DC[k]) ? sq2 : 1.0);
            if (nd < dist_out[v]) {
                dist_out[v] = nd; next_out[v] = u;
                if (hpush(&hp, nd, nd, v)) { settled = -1; goto done; }
            }
        }
    }
done:
    free(closed); free(hp.a);
    return settled;
}

/* ------------------------------------------------------------------ incremental repair of a cost-to-go field
 * After the exposure E changed (e.g. a radar moved), repair dist/next in place instead of recomputing.
 * changed[v] = 0 unchanged, 1 cost went up (or mixed), 2 cost went down only.
 *   1. affected = cells whose cost went UP + every cell whose route (next chain) passes through one;
 *      only these can have become worse, so only these are reset;
 *   2. seed each affected cell from its best unaffected neighbour;
 *   3. cells whose cost went DOWN keep their value (still a valid upper bound) but are re-evaluated
 *      and queued, so the improvement can spread;
 *   4. run Dijkstra from the seeds; improvements also propagate into unaffected cells
 *      (Ramalingam-Reps style dynamic shortest paths).
 * Work is proportional to the affected region, not to the whole grid.
 * Returns the number of affected cells, -1 on failure; *settled_out = nodes settled by step 3. */
EXPORT int64_t grid_repair(int32_t Hh, int32_t W, const double *z, const double *E, const uint8_t *blocked,
                           double cell, double alpha, double beta, int32_t goal, const uint8_t *changed,
                           double *dist, int32_t *next, int64_t *settled_out) {
    int64_t N = (int64_t)Hh * W;
    /* state: 0 unknown, 1 affected, 2 unaffected */
    uint8_t *st = (uint8_t *)calloc((size_t)N, 1);
    int32_t *stack = (int32_t *)malloc((size_t)N * sizeof(int32_t));
    heap hp = {0};
    if (!st || !stack) { free(st); free(stack); return -1; }
    const double sq2 = 1.4142135623730951;
    int64_t naff = 0;
    st[goal] = 2;
    for (int64_t s0 = 0; s0 < N; s0++) {
        if (st[s0] || blocked[s0] || !isfinite(dist[s0])) { if (!st[s0]) st[s0] = 2; continue; }
        /* walk the next chain until a cell with a known state, then label the whole walk */
        int64_t top = 0; int32_t v = (int32_t)s0; uint8_t res = 2;
        while (v >= 0 && st[v] == 0) {
            if (changed[v] == 1) { res = 1; break; }
            stack[top++] = v; v = next[v];
        }
        if (v >= 0 && st[v]) res = (res == 1) ? 1 : st[v];
        if (v >= 0 && changed[v] == 1 && st[v] == 0) { st[v] = 1; naff++; res = 1; }
        while (top > 0) { int32_t u = stack[--top]; st[u] = res; if (res == 1) naff++; }
    }
    for (int64_t i = 0; i < N; i++) if (changed[i] == 1 && st[i] != 1 && i != goal && !blocked[i]) { st[i] = 1; naff++; }
    for (int64_t i = 0; i < N; i++) if (st[i] == 1) { dist[i] = INFINITY; next[i] = -1; }
    /* seed each affected cell from its unaffected neighbours */
    for (int64_t i = 0; i < N; i++) {
        if (st[i] != 1) continue;
        int32_t u = (int32_t)i, ur = u / W, uc = u % W;
        double best = INFINITY; int32_t bn = -1;
        for (int k = 0; k < 8; k++) {
            int32_t vr = ur + DR[k], vc = uc + DC[k];
            if (vr < 0 || vr >= Hh || vc < 0 || vc >= W) continue;
            int32_t v = vr * W + vc;
            if (blocked[v] || st[v] == 1 || !isfinite(dist[v])) continue;
            double c = dist[v] + edge_cost(z, E, cell, alpha, beta, u, v, (DR[k] && DC[k]) ? sq2 : 1.0);
            if (c < best) { best = c; bn = v; }
        }
        if (bn >= 0) { dist[u] = best; next[u] = bn; if (hpush(&hp, best, best, u)) { naff = -1; goto done; } }
    }
    /* cells that only got cheaper: re-evaluate from all neighbours and queue them so the gain spreads */
    for (int64_t i = 0; i < N; i++) {
        if (changed[i] != 2 || st[i] == 1 || blocked[i] || i == goal) continue;
        int32_t u = (int32_t)i, ur = u / W, uc = u % W;
        for (int k = 0; k < 8; k++) {
            int32_t vr = ur + DR[k], vc = uc + DC[k];
            if (vr < 0 || vr >= Hh || vc < 0 || vc >= W) continue;
            int32_t v = vr * W + vc;
            if (blocked[v] || !isfinite(dist[v])) continue;
            double c = dist[v] + edge_cost(z, E, cell, alpha, beta, u, v, (DR[k] && DC[k]) ? sq2 : 1.0);
            if (c < dist[u] - 1e-9) { dist[u] = c; next[u] = v; }
        }
        if (isfinite(dist[u]) && hpush(&hp, dist[u], dist[u], u)) { naff = -1; goto done; }
    }
    /* Dijkstra from the seeds (lazy deletion: skip stale heap entries) */
    int64_t settled = 0;
    while (hp.n > 0) {
        item it = hpop(&hp);
        int32_t u = it.v;
        if (it.f > dist[u]) continue;
        settled++;
        int32_t ur = u / W, uc = u % W;
        for (int k = 0; k < 8; k++) {
            int32_t vr = ur + DR[k], vc = uc + DC[k];
            if (vr < 0 || vr >= Hh || vc < 0 || vc >= W) continue;
            int32_t v = vr * W + vc;
            if (blocked[v] || v == goal) continue;
            double nd = dist[u] + edge_cost(z, E, cell, alpha, beta, v, u, (DR[k] && DC[k]) ? sq2 : 1.0);
            if (nd < dist[v] - 1e-9) {
                dist[v] = nd; next[v] = u;
                if (hpush(&hp, nd, nd, v)) { naff = -1; goto done; }
            }
        }
    }
    *settled_out = settled;
done:
    free(st); free(stack); free(hp.a);
    return naff;
}

/* ------------------------------------------------------------------ follow a cost-to-go field from any start
 * Writes the route start..goal into path_out; returns its length, 0 if unreachable, -(len) if too long. */
EXPORT int64_t grid_follow(const int32_t *next, int32_t start, int32_t goal, int32_t *path_out, int64_t path_cap) {
    int64_t len = 0;
    int32_t v = start;
    while (v >= 0 && v != goal) { if (len < path_cap) path_out[len] = v; len++; v = next[v]; if (len > 100000000) return 0; }
    if (v != goal) return 0;
    if (len < path_cap) path_out[len] = goal;
    len++;
    return len <= path_cap ? len : -len;
}

/* ------------------------------------------------------------------ compact next-step fields (1 byte per cell)
 * A next pointer always names one of the 8 neighbours, so it fits in a direction code
 * k = (dr + 1) * 3 + (dc + 1) in 0..8 (4 = none); 255 = no route.  4x smaller than int32 pointers. */
EXPORT void grid_next_to_dir(int64_t N, int32_t W, const int32_t *next, uint8_t *dir) {
    for (int64_t v = 0; v < N; v++) {
        int32_t u = next[v];
        if (u < 0) { dir[v] = 255; continue; }
        int32_t dr = (int32_t)(u / W - v / W), dc = (int32_t)(u % W - v % W);
        dir[v] = (uint8_t)((dr + 1) * 3 + (dc + 1));
    }
}

EXPORT int64_t grid_follow_dir(const uint8_t *dir, int32_t W, int32_t start, int32_t goal, int32_t *path_out, int64_t path_cap) {
    int64_t len = 0;
    int32_t v = start;
    while (v != goal) {
        uint8_t k = dir[v];
        if (k == 255 || k == 4) return 0;
        if (len < path_cap) path_out[len] = v;
        len++;
        v += (k / 3 - 1) * W + (k % 3 - 1);
        if (len > 100000000) return 0;
    }
    if (len < path_cap) path_out[len] = goal;
    len++;
    return len <= path_cap ? len : -len;
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

#include "dstar.inc"
#include "parallel.inc"
#include "csp.inc"
#include "tiles.inc"
#include "layers.inc"
