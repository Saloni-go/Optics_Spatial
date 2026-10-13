/* ================================================================== 3-D routing: altitude as a decision
 * Included from gridsearch.c.  Used by corridor/altitude.py.
 *
 * nl flight levels (heights above ground agl[l]); node = l*N + cell.  Moves:
 *   horizontal, same level: lf*cell*(1 + gamma[l] + alpha*(E_l[u]+E_l[v])/2) + beta*max(0, climb of terrain)
 *       E_l = threat surface for an aircraft at that height (viewsheds depend on target height);
 *       gamma[l] = extra cost per metre of flying that low (terrain-following risk, fuel): without it the
 *       answer would always be "hug the ground";
 *   vertical, same cell, to the level above/below: beta*max(0, agl[l']-agl[l]) + vcost*|agl[l']-agl[l]|.
 * Backward field from the goal cell (reached at any level): dist/next over all nl*N nodes. */
EXPORT int64_t grid3_costtogo(int32_t Hh, int32_t W, int32_t nl, const double *z, const double *E, const uint8_t *blocked,
                              const double *agl, const double *gamma, double cell, double alpha, double beta, double vcost,
                              int32_t goal, double *dist, int32_t *next) {
    int64_t N = (int64_t)Hh * W, M = N * nl;
    uint8_t *closed = (uint8_t *)calloc((size_t)M, 1);
    heap hp = {0};
    if (!closed) return -1;
    for (int64_t i = 0; i < M; i++) { dist[i] = INFINITY; next[i] = -1; }
    const double sq2 = 1.4142135623730951;
    for (int32_t l = 0; l < nl; l++) {
        int64_t g = (int64_t)l * N + goal;
        if (!blocked[g]) { dist[g] = 0.0; if (hpush(&hp, 0.0, 0.0, (int32_t)g)) { free(closed); return -1; } }
    }
    int64_t settled = 0;
    while (hp.n > 0) {
        item it = hpop(&hp);
        int32_t u = it.v;
        if (closed[u]) continue;
        closed[u] = 1; settled++;
        int32_t l = (int32_t)(u / N), c = (int32_t)(u % N), ur = c / W, uc = c % W;
        const double *El = E + (int64_t)l * N;
        /* horizontal predecessors v -> u on the same level */
        for (int k = 0; k < 8; k++) {
            int32_t vr = ur + DR[k], vc = uc + DC[k];
            if (vr < 0 || vr >= Hh || vc < 0 || vc >= W) continue;
            int32_t vcell = vr * W + vc;
            int64_t v = (int64_t)l * N + vcell;
            if (blocked[v] || closed[v]) continue;
            double lf = ((DR[k] && DC[k]) ? sq2 : 1.0) * cell;
            double dz = z[c] - z[vcell];
            double cst = lf * (1.0 + gamma[l] + alpha * 0.5 * (El[vcell] + El[c])) + (dz > 0 ? beta * dz : 0.0);
            double nd = dist[u] + cst;
            if (nd < dist[v]) { dist[v] = nd; next[v] = u; if (hpush(&hp, nd, nd, (int32_t)v)) { settled = -1; goto done; } }
        }
        /* vertical predecessors: same cell, level l-1 or l+1, moving to level l */
        for (int dl = -1; dl <= 1; dl += 2) {
            int32_t m = l + dl;
            if (m < 0 || m >= nl) continue;
            int64_t v = (int64_t)m * N + c;
            if (blocked[v] || closed[v]) continue;
            double dh = agl[l] - agl[m];                       /* v (level m) -> u (level l) */
            double cst = (dh > 0 ? beta * dh : 0.0) + vcost * fabs(dh);
            double nd = dist[u] + cst;
            if (nd < dist[v]) { dist[v] = nd; next[v] = u; if (hpush(&hp, nd, nd, (int32_t)v)) { settled = -1; goto done; } }
        }
    }
done:
    free(closed); free(hp.a);
    return settled;
}
