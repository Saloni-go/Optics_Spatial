/* ================================================================== tile searches for the overlay graph
 * Included from gridsearch.c.  Used by corridor/tiles.py (Customizable-Route-Planning-style overlay).
 *
 * window_multi: Dijkstra searches restricted to the window [r0,r1) x [c0,c1) of the full grid.
 *   reverse = 0: for every source s and target t, out[s*nt + t] = d(s -> t) inside the window;
 *   reverse = 1: out[s*nt + t] = d(t -> s)  (one backward search per source).
 *   Cells are given as full-grid indices.  Window-local arrays only, so a 250 x 250 tile costs
 *   0.06 M nodes per search whatever the map size. */
EXPORT int64_t window_multi(int32_t Hh, int32_t W, const double *z, const double *E, const uint8_t *blocked,
                            double cell, double alpha, double beta, int32_t r0, int32_t r1, int32_t c0, int32_t c1,
                            int32_t ns, const int32_t *src, int32_t nt, const int32_t *tgt, int32_t reverse, double *out) {
    (void)Hh;
    int32_t h = r1 - r0, w = c1 - c0;
    int64_t n = (int64_t)h * w;
    double *dist = (double *)malloc((size_t)n * sizeof(double));
    uint8_t *closed = (uint8_t *)malloc((size_t)n);
    int32_t *tl = (int32_t *)malloc((size_t)(nt > 0 ? nt : 1) * sizeof(int32_t));
    heap hp = {0};
    if (!dist || !closed || !tl) { free(dist); free(closed); free(tl); return -1; }
    for (int32_t t = 0; t < nt; t++) tl[t] = (tgt[t] / W - r0) * w + (tgt[t] % W - c0);
    const double sq2 = 1.4142135623730951;
    int64_t settled = 0;
    for (int32_t si = 0; si < ns; si++) {
        for (int64_t i = 0; i < n; i++) { dist[i] = INFINITY; closed[i] = 0; }
        int32_t s = (src[si] / W - r0) * w + (src[si] % W - c0);
        hp.n = 0;
        dist[s] = 0.0;
        if (hpush(&hp, 0.0, 0.0, s)) { settled = -1; break; }
        while (hp.n > 0) {
            item it = hpop(&hp);
            int32_t u = it.v;
            if (closed[u]) continue;
            closed[u] = 1; settled++;
            int32_t ur = u / w, uc = u % w;
            int32_t gu = (ur + r0) * W + (uc + c0);
            for (int k = 0; k < 8; k++) {
                int32_t vr = ur + DR[k], vc = uc + DC[k];
                if (vr < 0 || vr >= h || vc < 0 || vc >= w) continue;
                int32_t v = vr * w + vc;
                int32_t gv = (vr + r0) * W + (vc + c0);
                if (blocked[gv] || closed[v]) continue;
                double lf = (DR[k] && DC[k]) ? sq2 : 1.0;
                double c = reverse ? edge_cost(z, E, cell, alpha, beta, gv, gu, lf) : edge_cost(z, E, cell, alpha, beta, gu, gv, lf);
                double nd = dist[u] + c;
                if (nd < dist[v]) { dist[v] = nd; if (hpush(&hp, nd, nd, v)) { settled = -1; goto done; } }
            }
        }
        for (int32_t t = 0; t < nt; t++) out[(int64_t)si * nt + t] = dist[tl[t]];
    }
done:
    free(dist); free(closed); free(tl); free(hp.a);
    return settled;
}

/* overlay_query: Dijkstra on the overlay graph (CSR) from several sources with initial costs sd, to
 * several targets with final costs td; stops once no target can improve.  pred[] (-1 at sources) lets
 * the caller unpack the route.  Returns the index of the best target (or -1), cost in *best. */
EXPORT int32_t overlay_query(int32_t n, const int64_t *indptr, const int32_t *indices, const double *data,
                             int32_t ns, const int32_t *src, const double *sd, int32_t nt, const int32_t *tgt,
                             const double *td, double *best, int32_t *pred) {
    double *dist = (double *)malloc((size_t)n * sizeof(double));
    double *tcost = (double *)malloc((size_t)n * sizeof(double));
    uint8_t *closed = (uint8_t *)calloc((size_t)n, 1);
    heap hp = {0};
    if (!dist || !tcost || !closed) { free(dist); free(tcost); free(closed); return -2; }
    for (int32_t i = 0; i < n; i++) { dist[i] = INFINITY; tcost[i] = INFINITY; pred[i] = -1; }
    for (int32_t t = 0; t < nt; t++) if (td[t] < tcost[tgt[t]]) tcost[tgt[t]] = td[t];
    for (int32_t k = 0; k < ns; k++)
        if (sd[k] < dist[src[k]]) { dist[src[k]] = sd[k]; hpush(&hp, sd[k], sd[k], src[k]); }
    double b = INFINITY; int32_t bt = -1;
    while (hp.n > 0) {
        item it = hpop(&hp);
        int32_t u = it.v;
        if (closed[u]) continue;
        if (dist[u] >= b) break;
        closed[u] = 1;
        if (dist[u] + tcost[u] < b) { b = dist[u] + tcost[u]; bt = u; }
        for (int64_t e = indptr[u]; e < indptr[u + 1]; e++) {
            int32_t v = indices[e];
            double nd = dist[u] + data[e];
            if (nd < dist[v]) { dist[v] = nd; pred[v] = u; hpush(&hp, nd, nd, v); }
        }
    }
    *best = b;
    free(dist); free(tcost); free(closed); free(hp.a);
    return bt;
}
