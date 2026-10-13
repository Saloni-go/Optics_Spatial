"""Track 3 - interactive corridor viewer (demo of precompute vs compute-on-the-fly).

    run.bat -m corridor.interactive [--size 4000] [--mode exposure|detection]
    run.bat -m corridor.interactive --demo results/corridor/interactive/demo.gif     (scripted, no window)

Mouse / keys (window mode):
    left click            new start      -> Level 2 lookup (exact, < 1 ms)
    b                     shortest route with P(detect) <= 50% (detection mode)
    right click           new goal       -> coarse-to-fine answer at once, field rebuilt in the background
    drag a radar          move it        -> one viewshed + field repair (exact)
    r / x                 add a radar at the mouse / remove the nearest radar
    + / -                 exposure weight alpha x2 / /2  -> alpha bank: exact route at once (precomputed ladder);
                                                        off-ladder values: nearest banked route, then exact
    toolbar zoom / pan    Level 3: the visible window is re-solved at screen resolution
The panel at the bottom says, for every action, which level answered it and how long it took.
"""
import argparse
import math
import time

import numpy as np

from corridor.interactive_core import Planner


def hillshade(z, az=315, alt=45):
    gy, gx = np.gradient(z)
    slope = np.arctan(np.hypot(gx, gy) / 30.0 * 4)
    aspect = np.arctan2(-gx, gy)
    a, b = math.radians(az), math.radians(alt)
    return np.clip(np.sin(b) * np.cos(slope) + np.cos(b) * np.sin(slope) * np.cos(a - aspect), 0, 1)


class Viewer:
    PICK_PX = 12

    def __init__(self, planner, fig=None, interactive=True):
        import matplotlib.pyplot as plt
        from matplotlib.colors import LinearSegmentedColormap
        self.P, self.plt, self.interactive = planner, plt, interactive
        P = planner
        H, W = P.p.H, P.p.W
        self.f = max(1, int(math.ceil(max(H, W) / 1000)))            # display decimation
        z = np.nan_to_num(P.dem.z[::self.f, ::self.f].astype(np.float64), nan=0.0)
        self.fig = fig or plt.figure(figsize=(9.5, 10.5))
        self.ax = self.fig.add_axes([0.05, 0.13, 0.90, 0.75])
        self.ax.imshow(hillshade(z), cmap="gray", extent=(0, W, H, 0), interpolation="bilinear", vmin=0, vmax=1)
        self.ax.imshow(z, cmap="terrain", alpha=0.35, extent=(0, W, H, 0), interpolation="bilinear")
        threat = LinearSegmentedColormap.from_list("t", [(1, 0.2, 0.1, 0), (1, 0.15, 0.05, 0.75)])
        self.threat_cmap = threat
        self.threat_img = self.ax.imshow(self._threat(), cmap=threat, extent=(0, W, H, 0), interpolation="nearest", vmin=0, vmax=1)
        self.route_ln, = self.ax.plot([], [], "-", c="#00e5ff", lw=2.2, zorder=5)
        self.stage_ln, = self.ax.plot([], [], "--", c="#ffd166", lw=1.6, zorder=6)
        self.lod_ln, = self.ax.plot([], [], "-", c="#ff4fd8", lw=2.0, zorder=7)
        self.radar_sc = self.ax.scatter([], [], marker="^", s=90, c="#d00000", edgecolors="white", zorder=8)
        self.start_sc = self.ax.scatter([], [], marker="o", s=80, c="#06d6a0", edgecolors="k", zorder=9)
        self.goal_sc = self.ax.scatter([], [], marker="*", s=180, c="#ffd60a", edgecolors="k", zorder=9)
        self.ax.set_xlim(0, W); self.ax.set_ylim(H, 0)
        self.ax.set_xticks([]); self.ax.set_yticks([])
        self.title = self.ax.set_title("", fontsize=9)
        self.panel = self.fig.text(0.04, 0.015, "", family="monospace", fontsize=8.2, va="bottom")
        self.lines = []
        self.drag = None
        self._suppress_view = False
        self.redraw_static()
        self.show_route()
        if interactive:
            c = self.fig.canvas
            c.mpl_connect("button_press_event", self.on_press)
            c.mpl_connect("button_release_event", self.on_release)
            c.mpl_connect("key_press_event", self.on_key)
            self.ax.callbacks.connect("xlim_changed", self.on_view)
            self.timer = c.new_timer(interval=150)
            self.timer.add_callback(self.poll)
            self.timer.start()
            self._seen = P.ctg

    # ------------------------------------------------------------ drawing
    def _threat(self):
        E = self.P.field.E[::self.f, ::self.f]
        m = E.max() or 1.0
        return np.ma.masked_less_equal(E / m, 0.0)

    def redraw_static(self):
        P = self.P
        pts = [P.dem.to_pixel(x, y) for x, y in P.field.sites]
        self.radar_sc.set_offsets(np.array(pts) if pts else np.empty((0, 2)))
        self.start_sc.set_offsets([[P.start[1], P.start[0]]])
        self.goal_sc.set_offsets([[P.goal[1], P.goal[0]]])
        self.threat_img.set_data(self._threat())

    def _xy(self, path):
        rc = np.array([divmod(i, self.P.p.W) for i in path]) if path else np.empty((0, 2))
        return rc[:, 1], rc[:, 0]

    def show_route(self, stage=None):
        P = self.P
        if stage is not None and stage.get("level", 1) > 1:
            self.stage_ln.set_data(*self._xy(stage["path"]))
        else:
            self.stage_ln.set_data([], [])
            self.route_ln.set_data(*self._xy(P.path if getattr(P, "path", None) else None))
        pd = P.detection_probability() if getattr(P, "path", None) else None
        self.title.set_text(f"Track 3 interactive corridor  |  {P.p.H}x{P.p.W} = {P.p.H * P.p.W / 1e6:.0f} M cells  |  "
                            f"alpha = {P.p.alpha:g}  |  {P.mode} model" +
                            (f"  |  P(detect) = {100 * pd:.1f}%" if pd is not None else "") +
                            f"\nroute cost {getattr(P, 'cost', float('nan')) / 1000:.1f} k   " +
                            ("field: ready" if P.ctg is not None else "field: rebuilding..."))

    def note(self, e):
        line = f"{e['action'][:26]:26s} {e['ms']:9.1f} ms  {e['how']}"
        self.lines = (self.lines + [line])[-7:]
        self.panel.set_text("\n".join(self.lines))

    def refresh(self):
        self.fig.canvas.draw_idle()
        if self.interactive:
            self.fig.canvas.flush_events()

    # ------------------------------------------------------------ actions (shared by mouse and demo)
    def act_start(self, r, c):
        e = self.P.set_start((r, c)); self.note(e)
        self.lod_ln.set_data([], [])
        self.redraw_static(); self.show_route(); self.refresh()

    def act_goal(self, r, c, background=True):
        e = self.P.set_goal((r, c), background=background); self.note(e)
        self.redraw_static(); self.show_route(); self.refresh()

    def act_move_radar(self, i, r, c, background=True):
        x, y = self.P.dem.to_world(c, r)
        e = self.P.edit_radar("move", i, x, y, background=background); self.note(e)
        self.redraw_static(); self.show_route(); self.refresh()

    def act_add_radar(self, r, c, background=True):
        x, y = self.P.dem.to_world(c, r)
        e = self.P.edit_radar("add", x=x, y=y, background=background); self.note(e)
        self.redraw_static(); self.show_route(); self.refresh()

    def act_remove_radar(self, i, background=True):
        e = self.P.edit_radar("remove", i, background=background); self.note(e)
        self.redraw_static(); self.show_route(); self.refresh()

    def act_alpha(self, alpha, background=True, frame=None):
        def stage(r):
            import threading
            if threading.current_thread() is not threading.main_thread():
                return                                   # field finished on the worker: poll() redraws
            self.note(self.P.events[-1])
            self.show_route(r); self.refresh()
            if frame:
                frame()
        self.P.set_alpha(alpha, on_route=stage, background=background)
        self.show_route(); self.refresh()

    def act_view(self, r0, r1, c0, c1):
        e = self.P.view(r0, r1, c0, c1); self.note(e)
        lod = self.P.lod
        pts = lod["refined"] or []
        self.lod_ln.set_data([q[1] for q in pts], [q[0] for q in pts])
        self.refresh()

    # ------------------------------------------------------------ GUI events
    def _nearest_radar(self, x, y):
        pts = np.array([self.P.dem.to_pixel(a, b) for a, b in self.P.field.sites])
        if not len(pts):
            return None, math.inf
        d = np.hypot(pts[:, 0] - x, pts[:, 1] - y)
        i = int(np.argmin(d))
        px = d[i] / (self.ax.get_xlim()[1] - self.ax.get_xlim()[0]) * self.ax.bbox.width
        return i, px

    def _cell(self, ev):
        r = int(np.clip(round(ev.ydata), 0, self.P.p.H - 1)); c = int(np.clip(round(ev.xdata), 0, self.P.p.W - 1))
        return r, c

    def on_press(self, ev):
        if ev.inaxes is not self.ax or self.fig.canvas.toolbar is not None and self.fig.canvas.toolbar.mode:
            return
        i, px = self._nearest_radar(ev.xdata, ev.ydata)
        if ev.button == 1 and i is not None and px < self.PICK_PX:
            self.drag = i
            return
        r, c = self._cell(ev)
        if self.P.p.blocked[r, c]:
            self.note({"action": "click ignored", "ms": 0.0, "how": "cell above the 5000 m ceiling"}); self.refresh(); return
        if ev.button == 1:
            self.act_start(r, c)
        elif ev.button == 3:
            self.act_goal(r, c)

    def on_release(self, ev):
        if self.drag is None or ev.inaxes is not self.ax:
            self.drag = None
            return
        i, self.drag = self.drag, None
        self.act_move_radar(i, *self._cell(ev))

    def on_key(self, ev):
        if ev.key in ("+", "="):
            self.act_alpha(self.P.p.alpha * 2)
        elif ev.key == "-":
            self.act_alpha(max(self.P.p.alpha / 2, 0.25))
        elif ev.key == "b" and self.P.mode == "detection":
            rb = self.P.risk_budget(0.5)
            how = (f"LARAC, {rb['solves']} fields, {rb['length_km']:.0f} km, P(detect) {100 * rb['p_detect']:.0f}%, "
                   f"within {rb['gap_pct']:.1f}% of optimal"
                   if rb["found"] else f"no route under 50% exists ({rb['solves']} searches); route unchanged")
            self.note(self.P.log("risk budget 50%", rb["seconds"], how))
            self.show_route(); self.refresh()
        elif ev.key == "r" and ev.inaxes is self.ax:
            self.act_add_radar(*self._cell(ev))
        elif ev.key == "x" and ev.inaxes is self.ax:
            i, _ = self._nearest_radar(ev.xdata, ev.ydata)
            if i is not None:
                self.act_remove_radar(i)

    def on_view(self, ax):
        if self._suppress_view:
            return
        (x0, x1), (y1, y0) = ax.get_xlim(), ax.get_ylim()
        W, H = self.P.p.W, self.P.p.H
        if (x1 - x0) > 0.95 * W:
            self.lod_ln.set_data([], []); return
        self.act_view(int(max(y0, 0)), int(min(y1, H)), int(max(x0, 0)), int(min(x1, W)))

    def poll(self):
        """Timer: notice when a background field rebuild has finished and redraw."""
        ctg = self.P.ctg
        if ctg is not None and ctg is not self._seen:
            self._seen = ctg
            e = self.P.events[-1]
            if e["action"] != "set alpha (exact)":
                self.P.path, self.P.cost = ctg.route(self.P.start)
            self.note(e); self.show_route(); self.refresh()


# ---------------------------------------------------------------- scripted demo (no window)
def demo(out, size=4000, mode="detection"):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from PIL import Image
    P = Planner(size, mode)
    P.precompute(landmarks=False, bank=(2.5, 5, 10, 20, 40, 80))
    P.set_start(P.start)
    V = Viewer(P, interactive=False)
    for e in P.events:
        V.note(e)
    frames, log = [], []

    def frame(caption, hold=1):
        V.fig.suptitle(caption, fontsize=12, y=0.975, color="#1d3557", weight="bold")
        V.fig.canvas.draw()
        img = Image.frombuffer("RGBA", V.fig.canvas.get_width_height(), V.fig.canvas.buffer_rgba()).convert("RGB")
        img = img.resize((img.width * 2 // 3, img.height * 2 // 3), Image.LANCZOS)
        frames.extend([img] * hold)
        log.append({"caption": caption, **(P.events[-1] if P.events else {})})
        print(caption, "|", P.events[-1]["how"], f"{P.events[-1]['ms']:.1f} ms")

    H, W = P.p.H, P.p.W
    frame("Precomputed: cost-to-go field (Level 2), pyramid (Level 3), alpha bank of 6 fields", 3)
    free = np.argwhere(~P.p.blocked)
    rng = np.random.default_rng(3)
    for k in range(3):
        r, c = free[rng.integers(len(free))]
        V.act_start(int(r), int(c))
        frame(f"Click {k + 1}: new start -> route by lookup, no search", 2)
    V.act_start(*P.start)
    i = 2
    x, y = P.field.sites[i]
    cpx, rpx = P.dem.to_pixel(x, y)
    V.act_move_radar(i, int(rpx + 0.04 * H), int(cpx + 0.06 * W), background=False)
    frame("Radar dragged: threat updated for that radar only, field rebuilt on 12 cores (exact)", 3)
    V.act_alpha(P.p.alpha * 4, background=False, frame=lambda: frame(f"alpha x4 -> {P.events[-1]['how']}", 2))
    frame("alpha x4: exact route, field rebuilt (parallel, 12 cores)", 2)
    V.act_alpha(30.0, background=False, frame=lambda: frame(f"alpha 30 (off the ladder) -> {P.events[-1]['how']}", 2))
    rc = np.array([divmod(j, W) for j in P.path])
    cr, cc = rc[len(rc) // 2]
    for view in (W // 2, W // 6):
        r0 = int(np.clip(cr - view // 2, 0, H - view)); c0 = int(np.clip(cc - view // 2, 0, W - view))
        V.ax.set_xlim(c0, c0 + view); V.ax.set_ylim(r0 + view, r0)
        V.act_view(r0, r0 + view, c0, c0 + view)
        frame(f"Zoom to {view} cells: exact route already known from the field - nothing to search", 2)
    V.ax.set_xlim(0, W); V.ax.set_ylim(H, 0); V.lod_ln.set_data([], [])
    V.act_add_radar(int(rc[len(rc) // 3][0]), int(rc[len(rc) // 3][1]), background=False)
    frame("Radar added on the route: field rebuilt, route bends away", 3)
    if P.mode == "detection":
        rb = P.risk_budget(0.5)
        V.note(P.log("risk budget 50%", rb["seconds"], f"LARAC + exact search, {rb['solves']} fields, "
                     f"{rb['length_km']:.0f} km, P(detect) {100 * rb['p_detect']:.0f}%, "
                     f"within {rb['gap_pct']:.1f}% of optimal"))
        V.show_route(); V.refresh()
        frame("Shortest route with P(detect) <= 50% (risk budget)", 3)
    out = str(out)
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=900, loop=0)
    frames[-1].save(out.replace(".gif", "_last.png"))
    import json
    json.dump({"size": size, "mode": mode, "events": P.events}, open(out.replace(".gif", "_log.json"), "w"), indent=1)
    print("wrote", out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=4000)
    ap.add_argument("--mode", default="detection", choices=["exposure", "detection"])
    ap.add_argument("--demo", default=None, help="write a scripted demo GIF instead of opening a window")
    a = ap.parse_args()
    if a.demo:
        return demo(a.demo, a.size, a.mode)
    import matplotlib
    matplotlib.use("QtAgg")
    import matplotlib.pyplot as plt
    P = Planner(a.size, a.mode)
    P.precompute(landmarks=False, bank=(2.5, 5, 10, 20, 40, 80))
    P.set_start(P.start)
    V = Viewer(P)
    for e in P.events:
        V.note(e)
    V.refresh()
    plt.show()


if __name__ == "__main__":
    main()
