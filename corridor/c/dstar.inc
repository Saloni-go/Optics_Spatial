/* ================================================================== D* Lite (Koenig and Likhachev 2002)
 * Included from gridsearch.c.
 * Incremental replanning for ONE route whose start may move and whose edge costs may change.
 * Searches backward from the goal (g, rhs = cost-to-goal estimates); after a change only the states
 * whose values matter for the current start are re-expanded, guided by h(start, s).
 * Priority queue with lazy deletion: an entry is processed only if it still matches the key of its state. */
typedef struct { double k1, k2; int32_t v; } dk;
typedef struct { dk *a; int64_t n, cap; } dheap;

static int dless(const dk *x, const dk *y) { return x->k1 < y->k1 || (x->k1 == y->k1 && x->k2 < y->k2); }
static int dpush(dheap *h, double k1, double k2, int32_t v) {
    if (h->n == h->cap) {
        int64_t cap = h->cap ? h->cap * 2 : (1 << 16);
        dk *a = (dk *)realloc(h->a, (size_t)cap * sizeof(dk));
        if (!a) return -1;
        h->a = a; h->cap = cap;
    }
    dk it = {k1, k2, v};
    int64_t i = h->n++;
    while (i > 0) { int64_t p = (i - 1) >> 1; if (!dless(&it, &h->a[p])) break; h->a[i] = h->a[p]; i = p; }
    h->a[i] = it;
    return 0;
}
static dk dpop(dheap *h) {
    dk top = h->a[0], last = h->a[--h->n];
    if (h->n == 0) return top;
    int64_t i = 0;
    for (;;) {
        int64_t c = 2 * i + 1;
        if (c >= h->n) break;
        if (c + 1 < h->n && dless(&h->a[c + 1], &h->a[c])) c++;
        if (!dless(&h->a[c], &last)) break;
        h->a[i] = h->a[c]; i = c;
    }
    h->a[i] = last;
    return top;
}

typedef struct {
    int32_t Hh, W; const double *z; const double *E; const uint8_t *blocked; double cell, alpha, beta;
    int32_t goal, start, last; double km;
    double *g, *rhs; dheap U; int64_t expanded;
} dstar;

static double dh(const dstar *d, int32_t a, int32_t b) {   /* lower bound on the cost of a -> b */
    int32_t ar = a / d->W, ac = a % d->W, br = b / d->W, bc = b % d->W;
    double dz = d->z[b] - d->z[a];
    return hypot((double)(ar - br), (double)(ac - bc)) * d->cell + (dz > 0 ? d->beta * dz : 0.0);
}
static void dkey(const dstar *d, int32_t s, double *k1, double *k2) {
    double m = d->g[s] < d->rhs[s] ? d->g[s] : d->rhs[s];
    *k1 = m + dh(d, d->start, s) + d->km; *k2 = m;
}
static double drhs(const dstar *d, int32_t u) {             /* min over successors of c(u, s2) + g(s2) */
    const double sq2 = 1.4142135623730951;
    int32_t ur = u / d->W, uc = u % d->W;
    double best = INFINITY;
    for (int k = 0; k < 8; k++) {
        int32_t vr = ur + DR[k], vc = uc + DC[k];
        if (vr < 0 || vr >= d->Hh || vc < 0 || vc >= d->W) continue;
        int32_t v = vr * d->W + vc;
        if (d->blocked[v] || !isfinite(d->g[v])) continue;
        double c = d->g[v] + edge_cost(d->z, d->E, d->cell, d->alpha, d->beta, u, v, (DR[k] && DC[k]) ? sq2 : 1.0);
        if (c < best) best = c;
    }
    return best;
}
static int dupdate(dstar *d, int32_t u) {
    if (u != d->goal) d->rhs[u] = drhs(d, u);
    if (d->g[u] != d->rhs[u]) { double k1, k2; dkey(d, u, &k1, &k2); return dpush(&d->U, k1, k2, u); }
    return 0;
}
static int dcompute(dstar *d) {
    for (;;) {
        while (d->U.n && d->g[d->U.a[0].v] == d->rhs[d->U.a[0].v]) dpop(&d->U);   /* drop consistent states */
        if (!d->U.n) break;
        double s1, s2; dkey(d, d->start, &s1, &s2);
        dk top = d->U.a[0];
        if (!(top.k1 < s1 || (top.k1 == s1 && top.k2 < s2)) && d->rhs[d->start] == d->g[d->start]) break;
        dpop(&d->U);
        int32_t u = top.v;
        double n1, n2; dkey(d, u, &n1, &n2);
        if (top.k1 < n1 || (top.k1 == n1 && top.k2 < n2)) { if (dpush(&d->U, n1, n2, u)) return -1; continue; }
        if (top.k1 > n1 || (top.k1 == n1 && top.k2 > n2)) continue;                 /* outdated duplicate */
        d->expanded++;
        int32_t ur = u / d->W, uc = u % d->W;
        if (d->g[u] > d->rhs[u]) d->g[u] = d->rhs[u];
        else { d->g[u] = INFINITY; if (dupdate(d, u)) return -1; }
        for (int k = 0; k < 8; k++) {                                                /* predecessors = neighbours */
            int32_t vr = ur + DR[k], vc = uc + DC[k];
            if (vr < 0 || vr >= d->Hh || vc < 0 || vc >= d->W) continue;
            int32_t v = vr * d->W + vc;
            if (d->blocked[v]) continue;
            if (dupdate(d, v)) return -1;
        }
    }
    return 0;
}

EXPORT void *dstar_new(int32_t Hh, int32_t W, const double *z, const double *E, const uint8_t *blocked,
                       double cell, double alpha, double beta, int32_t start, int32_t goal) {
    dstar *d = (dstar *)calloc(1, sizeof(dstar));
    int64_t N = (int64_t)Hh * W;
    if (!d) return NULL;
    d->Hh = Hh; d->W = W; d->z = z; d->E = E; d->blocked = blocked; d->cell = cell; d->alpha = alpha; d->beta = beta;
    d->goal = goal; d->start = start; d->last = start; d->km = 0.0;
    d->g = (double *)malloc((size_t)N * sizeof(double)); d->rhs = (double *)malloc((size_t)N * sizeof(double));
    if (!d->g || !d->rhs) { free(d->g); free(d->rhs); free(d); return NULL; }
    for (int64_t i = 0; i < N; i++) { d->g[i] = INFINITY; d->rhs[i] = INFINITY; }
    d->rhs[goal] = 0.0;
    double k1, k2; dkey(d, goal, &k1, &k2);
    dpush(&d->U, k1, k2, goal);
    return d;
}

/* (Re)plan from `start` (the start may have moved); returns states expanded by this call, -1 on failure. */
EXPORT int64_t dstar_plan(void *h, int32_t start) {
    dstar *d = (dstar *)h;
    double a = dh(d, d->last, start), b = dh(d, start, d->last);
    d->km += a < b ? a : b;
    d->last = start; d->start = start;
    int64_t before = d->expanded;
    if (dcompute(d)) return -1;
    return d->expanded - before;
}

/* The exposure changed on the cells with changed[v] != 0 (E points at the new values): every edge
 * touching such a cell changed, so re-evaluate those cells and their neighbours, then replan.
 * Returns states expanded, -1 on failure. */
EXPORT int64_t dstar_update(void *h, const double *E, const uint8_t *changed) {
    dstar *d = (dstar *)h;
    int64_t N = (int64_t)d->Hh * d->W;
    d->E = E;
    uint8_t *mark = (uint8_t *)calloc((size_t)N, 1);
    if (!mark) return -1;
    for (int64_t i = 0; i < N; i++) {
        if (!changed[i]) continue;
        int32_t u = (int32_t)i, ur = u / d->W, uc = u % d->W;
        mark[u] = 1;
        for (int k = 0; k < 8; k++) {
            int32_t vr = ur + DR[k], vc = uc + DC[k];
            if (vr >= 0 && vr < d->Hh && vc >= 0 && vc < d->W) mark[vr * d->W + vc] = 1;
        }
    }
    for (int64_t i = 0; i < N; i++) if (mark[i] && !d->blocked[i]) if (dupdate(d, (int32_t)i)) { free(mark); return -1; }
    free(mark);
    int64_t before = d->expanded;
    if (dcompute(d)) return -1;
    return d->expanded - before;
}

EXPORT double dstar_cost(void *h) { dstar *d = (dstar *)h; return d->g[d->start]; }

/* Route from the current start: step to the successor minimising c + g.  Returns length, 0 if none. */
EXPORT int64_t dstar_path(void *h, int32_t *path_out, int64_t path_cap) {
    dstar *d = (dstar *)h;
    const double sq2 = 1.4142135623730951;
    if (!isfinite(d->g[d->start])) return 0;
    int64_t len = 0; int32_t u = d->start;
    while (len < path_cap) {
        path_out[len++] = u;
        if (u == d->goal) return len;
        int32_t ur = u / d->W, uc = u % d->W, bn = -1; double best = INFINITY;
        for (int k = 0; k < 8; k++) {
            int32_t vr = ur + DR[k], vc = uc + DC[k];
            if (vr < 0 || vr >= d->Hh || vc < 0 || vc >= d->W) continue;
            int32_t v = vr * d->W + vc;
            if (d->blocked[v] || !isfinite(d->g[v])) continue;
            double c = d->g[v] + edge_cost(d->z, d->E, d->cell, d->alpha, d->beta, u, v, (DR[k] && DC[k]) ? sq2 : 1.0);
            if (c < best) { best = c; bn = v; }
        }
        if (bn < 0) return 0;
        u = bn;
    }
    return -len;
}

EXPORT void dstar_free(void *h) { dstar *d = (dstar *)h; if (d) { free(d->g); free(d->rhs); free(d->U.a); free(d); } }

