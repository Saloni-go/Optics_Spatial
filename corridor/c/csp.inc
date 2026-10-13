/* ================================================================== resource-constrained shortest path
 * Included from gridsearch.c.
 *
 * "Shortest route whose detection risk stays within a budget" is a resource-constrained shortest path
 * (NP-hard in general).  With the additive risk R = sum(length x hazard) and the length-like cost
 * L = length + beta x climb:
 *
 *   grid_costtogo_w   backward field for any weighted mix  wL*length + wE*length*hazard + wB*beta*climb;
 *                     (1,0,1) gives the least remaining L, (0,1,0) the least remaining R from every cell:
 *                     admissible bounds for pruning.
 *   csp_label         exact label-setting search (best-first on L + hL) inside an allowed region:
 *                     a label (L, R) at a cell is dropped if R + hR > budget (can never become feasible),
 *                     if L + hL >= the best feasible L known (cannot win), or if another label at the same
 *                     cell is no worse in both L and R (dominated), or if the Lagrangian bound
 *                     L + lam*R + d_lam(v) - lam*budget (d_lam = cost-to-go at the risk price lam)
 *                     already reaches the best feasible L (Carlyle, Royset and Wood 2008).
 *                     rtol > 0 merges labels whose risk differs by less than rtol (resource resolution):
 *                     the budget is still checked exactly, so the result is always feasible, and it is
 *                     optimal up to that resolution; rtol = 0 is the exact search.  The first label that reaches the goal is
 *                     the optimum within the region.  Labels are capped; -2 is returned if the cap is hit. */

EXPORT int64_t grid_costtogo_w(int32_t Hh, int32_t W, const double *z, const double *E, const uint8_t *blocked,
                               double cell, double beta, double wL, double wE, double wB, int32_t goal, double *dist) {
    int64_t N = (int64_t)Hh * W;
    uint8_t *closed = (uint8_t *)calloc((size_t)N, 1);
    heap hp = {0};
    if (!closed) return -1;
    for (int64_t i = 0; i < N; i++) dist[i] = INFINITY;
    const double sq2 = 1.4142135623730951;
    int64_t settled = 0;
    dist[goal] = 0.0;
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
            double lf = ((DR[k] && DC[k]) ? sq2 : 1.0) * cell;        /* route runs v -> u */
            double dz = z[u] - z[v];
            double c = wL * lf + wE * lf * 0.5 * (E[v] + E[u]) + (dz > 0 ? wB * beta * dz : 0.0);
            double nd = dist[u] + c;
            if (nd < dist[v]) { dist[v] = nd; if (hpush(&hp, nd, nd, v)) { settled = -1; goto done; } }
        }
    }
done:
    free(closed); free(hp.a);
    return settled;
}

typedef struct { double L, R; int32_t v, parent, nextl; uint8_t dead; } label;

EXPORT int64_t csp_label(int32_t Hh, int32_t W, const double *z, const double *E, const uint8_t *allowed,
                         double cell, double beta, int32_t start, int32_t goal, double budget, double ub,
                         const double *hL, const double *hR, double lam, const double *dlam, double rtol,
                         int64_t max_labels,
                         double *L_out, double *R_out, int64_t *labels_out, int32_t *path_out, int64_t path_cap) {
    int64_t N = (int64_t)Hh * W;
    int32_t *head = (int32_t *)malloc((size_t)N * sizeof(int32_t));
    int64_t cap = 1 << 20, n = 0;
    label *lab = (label *)malloc((size_t)cap * sizeof(label));
    heap hp = {0};
    if (!head || !lab) { free(head); free(lab); return -1; }
    for (int64_t i = 0; i < N; i++) head[i] = -1;
    const double sq2 = 1.4142135623730951;
    int64_t result = 0, found = -1;
    lab[0] = (label){0.0, 0.0, start, -1, -1, 0};
    head[start] = 0; n = 1;
    hpush(&hp, hL[start], 0.0, 0);
    while (hp.n > 0) {
        item it = hpop(&hp);
        int32_t li = it.v;
        if (lab[li].dead) continue;
        if (lab[li].L + hL[lab[li].v] >= ub) break;                  /* nothing left can beat the incumbent */
        int32_t u = lab[li].v;
        if (u == goal) { found = li; break; }
        double Lu = lab[li].L, Ru = lab[li].R;
        int32_t ur = u / W, uc = u % W;
        for (int k = 0; k < 8; k++) {
            int32_t vr = ur + DR[k], vc = uc + DC[k];
            if (vr < 0 || vr >= Hh || vc < 0 || vc >= W) continue;
            int32_t v = vr * W + vc;
            if (!allowed[v]) continue;
            double lf = ((DR[k] && DC[k]) ? sq2 : 1.0) * cell;
            double dz = z[v] - z[u];
            double nL = Lu + lf + (dz > 0 ? beta * dz : 0.0);
            double nR = Ru + lf * 0.5 * (E[u] + E[v]);
            if (nR + hR[v] > budget || nL + hL[v] >= ub) continue;
            /* Lagrangian bound: any completion has L + lam*R >= nL + lam*nR + dlam[v] and R <= budget */
            if (dlam && nL + lam * nR + dlam[v] - lam * budget >= ub) continue;
            /* dominance against the live labels at v; drop the ones the new label dominates */
            int dominated = 0;
            for (int32_t j = head[v]; j >= 0; j = lab[j].nextl) {
                if (lab[j].dead) continue;
                if (lab[j].L <= nL && lab[j].R <= nR + rtol) { dominated = 1; break; }
                if (nL <= lab[j].L && nR <= lab[j].R) lab[j].dead = 1;
            }
            if (dominated) continue;
            if (n == cap) {
                if (cap >= max_labels) { result = -2; goto done; }
                cap *= 2;
                label *l2 = (label *)realloc(lab, (size_t)cap * sizeof(label));
                if (!l2) { result = -1; goto done; }
                lab = l2;
            }
            lab[n] = (label){nL, nR, v, li, head[v], 0};
            head[v] = (int32_t)n;
            if (hpush(&hp, nL + hL[v], nL, (int32_t)n)) { result = -1; goto done; }
            n++;
        }
    }
    if (found >= 0) {
        int64_t len = 0;
        for (int32_t j = (int32_t)found; j >= 0; j = lab[j].parent) len++;
        *L_out = lab[found].L; *R_out = lab[found].R;
        if (len <= path_cap) {
            int64_t i = len - 1;
            for (int32_t j = (int32_t)found; j >= 0; j = lab[j].parent) path_out[i--] = lab[j].v;
            result = len;
        } else result = -3;
    }
done:
    *labels_out = n;
    free(head); free(lab); free(hp.a);
    return result;
}
