/* ================================================================== parallel cost-to-go field (delta-stepping)
 * Included from gridsearch.c; needs OpenMP (-fopenmp).
 *
 * Dijkstra settles one node at a time, so it cannot use more than one core.  Delta-stepping (Meyer and
 * Sanders 2003) relaxes a whole bucket of nodes at once: all nodes whose tentative cost lies in
 * [i*delta, (i+1)*delta) are relaxed in parallel, repeatedly until the bucket stays empty, then the next
 * bucket is processed.  Nodes can be relaxed more than once (label-correcting), but the final costs are
 * exactly Dijkstra's.  delta trades parallelism (large: big buckets) against wasted re-relaxations.
 *
 * One parallel region for the whole search (no thread start-up per phase); every thread files the
 * nodes it improved into its own buckets, so there is no serial merge step - a phase costs two barriers.
 * Costs are updated with a lock-free atomic minimum: non-negative doubles order like their 64-bit
 * patterns, so compare-and-swap on the bits is enough.  Next pointers are not tracked during the search
 * (racing writers could leave one inconsistent with the cost); a final parallel pass sets each to the
 * neighbour that attains the minimum, which is exact and acyclic because every edge cost is positive. */
#include <string.h>
#ifdef _OPENMP
#include <omp.h>
#endif

typedef struct { int32_t *a; int64_t n, cap; } ivec;
typedef struct { ivec *b; int64_t nb; } tbuckets;            /* one thread's buckets */

static int ivec_push(ivec *v, int32_t x) {
    if (v->n == v->cap) {
        int64_t cap = v->cap ? v->cap * 2 : 256;
        int32_t *a = (int32_t *)realloc(v->a, (size_t)cap * sizeof(int32_t));
        if (!a) return -1;
        v->a = a; v->cap = cap;
    }
    v->a[v->n++] = x;
    return 0;
}

static int tb_push(tbuckets *t, int64_t b, int32_t x) {
    if (b >= t->nb) {
        int64_t nn = t->nb ? t->nb : 1024;
        while (nn <= b) nn *= 2;
        ivec *B2 = (ivec *)realloc(t->b, (size_t)nn * sizeof(ivec));
        if (!B2) return -1;
        memset(B2 + t->nb, 0, (size_t)(nn - t->nb) * sizeof(ivec));
        t->b = B2; t->nb = nn;
    }
    return ivec_push(&t->b[b], x);
}

static inline double aload(const double *p) {
    uint64_t b = __atomic_load_n((const uint64_t *)p, __ATOMIC_RELAXED);
    double d; memcpy(&d, &b, 8); return d;
}

static inline int amin(double *p, double val) {           /* 1 if *p was lowered to val */
    uint64_t *a = (uint64_t *)p, nv, old = __atomic_load_n(a, __ATOMIC_RELAXED);
    memcpy(&nv, &val, 8);
    for (;;) {
        double od; memcpy(&od, &old, 8);
        if (!(val < od)) return 0;
        if (__atomic_compare_exchange_n(a, &old, nv, 1, __ATOMIC_RELAXED, __ATOMIC_RELAXED)) return 1;
    }
}

/* sense-reversing spin barrier: the libgomp barrier on Windows sleeps (tens of microseconds per phase,
 * growing with the thread count); phases here are short, so threads spin instead */
typedef struct { int count, sense, n; } sbar;
static void sbar_wait(sbar *b, int *local) {
    *local = !*local;
    if (__atomic_add_fetch(&b->count, 1, __ATOMIC_ACQ_REL) == b->n) {
        __atomic_store_n(&b->count, 0, __ATOMIC_RELAXED);
        __atomic_store_n(&b->sense, *local, __ATOMIC_RELEASE);
    } else {
        while (__atomic_load_n(&b->sense, __ATOMIC_ACQUIRE) != *local) __builtin_ia32_pause();
    }
}

EXPORT int64_t grid_costtogo_par(int32_t Hh, int32_t W, const double *z, const double *E, const uint8_t *blocked,
                                 double cell, double alpha, double beta, int32_t goal, double delta, int32_t threads,
                                 double *dist, int32_t *next, int64_t *relax_out) {
    int64_t N = (int64_t)Hh * W;
    const double sq2 = 1.4142135623730951;
#ifdef _OPENMP
    int T = threads > 0 ? threads : omp_get_max_threads();
#else
    int T = 1; (void)threads;
#endif
    double *done = (double *)malloc((size_t)N * sizeof(double));      /* cost at which a node was last relaxed */
    tbuckets *TB = (tbuckets *)calloc((size_t)T, sizeof(tbuckets));
    ivec *F = (ivec *)calloc((size_t)T, sizeof(ivec));                /* current frontier: one piece per thread */
    int64_t *off = (int64_t *)calloc((size_t)T + 1, sizeof(int64_t));
    if (!done || !TB || !F || !off) { free(done); free(TB); free(F); free(off); return -1; }
    int64_t relaxations = 0, phases = 0, cur = 0, total = 0, nextj = 0;
    int fail = 0, stop = 0, started = 0;
    sbar bar = {0, 0, T};
    const int64_t CH = 64;
    #pragma omp parallel num_threads(T)
    {
#ifdef _OPENMP
        int tid = omp_get_thread_num(), nt = omp_get_num_threads();
#else
        int tid = 0, nt = 1;
#endif
        int sense = 0;
        int64_t myrel = 0;
        if (tid == 0) { bar.n = nt; __atomic_store_n(&started, 1, __ATOMIC_RELEASE); }
        while (!__atomic_load_n(&started, __ATOMIC_ACQUIRE)) __builtin_ia32_pause();
        int64_t lo = N * tid / nt, hi = N * (tid + 1) / nt;
        for (int64_t i = lo; i < hi; i++) { dist[i] = INFINITY; done[i] = -1.0; next[i] = -1; }
        sbar_wait(&bar, &sense);
        if (tid == 0) { dist[goal] = 0.0; if (tb_push(&TB[0], 0, goal)) fail = 1; }
        for (;;) {
            if (tid == 0) {
                /* lowest non-empty bucket >= cur over all threads becomes the frontier */
                stop = 1;
                for (;;) {
                    int64_t maxnb = 0, any = 0;
                    for (int t = 0; t < nt; t++) {
                        if (TB[t].nb > maxnb) maxnb = TB[t].nb;
                        if (cur < TB[t].nb && TB[t].b[cur].n) any = 1;
                    }
                    if (any) { stop = 0; break; }
                    if (cur >= maxnb || fail) break;
                    for (int t = 0; t < nt; t++) if (cur < TB[t].nb) { free(TB[t].b[cur].a); TB[t].b[cur].a = NULL; TB[t].b[cur].cap = 0; }
                    cur++;
                }
                total = 0;
                if (!stop) {
                    for (int t = 0; t < nt; t++) {
                        free(F[t].a);
                        if (cur < TB[t].nb) { F[t] = TB[t].b[cur]; TB[t].b[cur].a = NULL; TB[t].b[cur].n = TB[t].b[cur].cap = 0; }
                        else { F[t].a = NULL; F[t].n = F[t].cap = 0; }
                        off[t] = total; total += F[t].n;
                    }
                    off[nt] = total;
                    phases++;
                }
                nextj = 0;
            }
            sbar_wait(&bar, &sense);
            if (stop) break;
            int64_t i = cur;
            for (;;) {
                int64_t j0 = __atomic_fetch_add(&nextj, CH, __ATOMIC_RELAXED);
                if (j0 >= total) break;
                int64_t j1 = j0 + CH < total ? j0 + CH : total;
                int t = 0;
                for (int64_t j = j0; j < j1; j++) {
                    while (j >= off[t + 1]) t++;
                    int32_t u = F[t].a[j - off[t]];
                    double du = aload(&dist[u]);
                    if (du == done[u] || (int64_t)(du / delta) != i) continue;   /* stale or already relaxed */
                    done[u] = du;
                    int32_t ur = u / W, uc = u % W;
                    for (int k = 0; k < 8; k++) {
                        int32_t vr = ur + DR[k], vc = uc + DC[k];
                        if (vr < 0 || vr >= Hh || vc < 0 || vc >= W) continue;
                        int32_t v = vr * W + vc;
                        if (blocked[v]) continue;
                        double nd = du + edge_cost(z, E, cell, alpha, beta, v, u, (DR[k] && DC[k]) ? sq2 : 1.0);
                        myrel++;
                        if (amin(&dist[v], nd)) {
                            int64_t b = (int64_t)(nd / delta);
                            if (b < i) b = i;
                            if (tb_push(&TB[tid], b, v)) fail = 1;
                        }
                    }
                }
            }
            sbar_wait(&bar, &sense);
        }
        /* next pointers from the final costs */
        for (int64_t i = lo; i < hi; i++) {
            if (i == goal || blocked[i] || !isfinite(dist[i])) continue;
            int32_t u = (int32_t)i, ur = u / W, uc = u % W, bn = -1; double best = INFINITY;
            for (int k = 0; k < 8; k++) {
                int32_t vr = ur + DR[k], vc = uc + DC[k];
                if (vr < 0 || vr >= Hh || vc < 0 || vc >= W) continue;
                int32_t v = vr * W + vc;
                if (blocked[v] || !isfinite(dist[v])) continue;
                double c = dist[v] + edge_cost(z, E, cell, alpha, beta, u, v, (DR[k] && DC[k]) ? sq2 : 1.0);
                if (c < best) { best = c; bn = v; }
            }
            next[u] = bn;
        }
        __atomic_add_fetch(&relaxations, myrel, __ATOMIC_RELAXED);
    }
    for (int t = 0; t < T; t++) {
        for (int64_t b = 0; b < TB[t].nb; b++) free(TB[t].b[b].a);
        free(TB[t].b); free(F[t].a);
    }
    free(TB); free(F); free(off); free(done);
    *relax_out = relaxations;
    return fail ? -1 : phases;
}
