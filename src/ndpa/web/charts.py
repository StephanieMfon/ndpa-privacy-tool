"""Charts drawn on the server as inline SVG: they print crisply, follow the page colours and need no JavaScript.

Colours come from CSS classes, never from inline styles, so the page can keep a strict Content-Security-Policy.
Every piece of text goes through escape().
"""
import math

from markupsafe import Markup, escape

BAND_CLASS = {"high": "high", "moderate": "moderate", "low": "low"}


def _num(x: float) -> str:
    return f"{x:.1f}"


def gauge_svg(score: float | None, band: str | None) -> Markup:
    """A ring showing the score out of 100."""
    radius, stroke = 62, 12
    circumference = 2 * math.pi * radius
    cls = BAND_CLASS.get(band or "", "none")
    shown = "—" if score is None else f"{score:g}"
    arc = ""
    if score is not None:
        arc = (f'<circle class="gauge-arc gauge-{cls}" cx="80" cy="80" r="{radius}" fill="none" stroke-width="{stroke}" '
               f'stroke-linecap="round" stroke-dasharray="{circumference * score / 100:.2f} {circumference:.2f}" '
               f'transform="rotate(-90 80 80)"/>')
    label = "No score" if score is None else f"Score {score:g} out of 100"
    return Markup(
        f'<svg class="gauge" viewBox="0 0 160 160" role="img" aria-label="{escape(label)}">'
        f'<circle class="gauge-track" cx="80" cy="80" r="{radius}" fill="none" stroke-width="{stroke}"/>{arc}'
        f'<text class="gauge-number" x="80" y="84" text-anchor="middle">{escape(shown)}</text>'
        f'<text class="gauge-of" x="80" y="106" text-anchor="middle">{"out of 100" if score is not None else "no score"}</text>'
        f'</svg>')


def bar_svg(value: float, previous: float | None = None, label: str = "") -> Markup:
    """A thin horizontal bar, 0 to 100, with an optional marker for an earlier value."""
    mark = f'<line class="bar-prev" x1="{_num(previous)}" x2="{_num(previous)}" y1="0" y2="10"/>' if previous is not None else ""
    return Markup(
        f'<svg class="bar" viewBox="0 0 100 10" preserveAspectRatio="none" role="img" aria-label="{escape(label or f"{value:g} out of 100")}">'
        f'<rect class="bar-track" x="0" y="0" width="100" height="10"/>'
        f'<rect class="bar-fill" x="0" y="0" width="{_num(max(0, min(100, value)))}" height="10"/>{mark}</svg>')


def radar_svg(axes: list[dict], previous: dict[str, float] | None = None) -> Markup:
    """axes: [{key, label, value, empty}]. Values are printed beside every axis because a radar is poor for exact reading."""
    cx, cy, radius = 210, 180, 112
    n = len(axes)
    angles = [-math.pi / 2 + 2 * math.pi * i / n for i in range(n)]

    def point(i: int, value: float, extra: float = 0.0) -> tuple[float, float]:
        r = radius * max(0.0, min(100.0, value)) / 100 + extra
        return cx + r * math.cos(angles[i]), cy + r * math.sin(angles[i])

    def polygon(values: list[float]) -> str:
        return " ".join("{:.1f},{:.1f}".format(*point(i, v)) for i, v in enumerate(values))

    parts = []
    for ring in (25, 50, 75, 100):
        parts.append(f'<polygon class="radar-ring" points="{polygon([ring] * n)}"/>')
    for i in range(n):
        x, y = point(i, 100)
        parts.append(f'<line class="radar-axis" x1="{cx}" y1="{cy}" x2="{x:.1f}" y2="{y:.1f}"/>')
    if previous:
        parts.append(f'<polygon class="radar-prev" points="{polygon([previous.get(a["key"], 0) for a in axes])}"/>')
    parts.append(f'<polygon class="radar-area" points="{polygon([a["value"] for a in axes])}"/>')
    for i, a in enumerate(axes):
        x, y = point(i, a["value"])
        cls = "radar-dot-empty" if a["empty"] else "radar-dot"
        parts.append(f'<circle class="{cls}" cx="{x:.1f}" cy="{y:.1f}" r="{4.5 if not a["empty"] else 5.5}"/>')
        lx, ly = point(i, 100, 20)
        cos = math.cos(angles[i])
        anchor = "start" if cos > 0.3 else "end" if cos < -0.3 else "middle"
        value_text = "Nothing to assess" if a["empty"] else f"{a['value']:g}%"
        parts.append(
            f'<text class="radar-label" x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}">'
            f'<tspan x="{lx:.1f}">{escape(a["label"])}</tspan>'
            f'<tspan class="radar-value{" radar-empty" if a["empty"] else ""}" x="{lx:.1f}" dy="1.25em">{escape(value_text)}</tspan></text>')
    summary = ", ".join(f'{a["label"]} {"nothing to assess" if a["empty"] else str(a["value"]) + " percent"}' for a in axes)
    return Markup(f'<svg class="radar" viewBox="-24 0 468 380" role="img" aria-label="{escape("Scores by area: " + summary)}">'
                  + "".join(parts) + "</svg>")


def sparkline_svg(values: list[float | None]) -> Markup:
    """Scores over time, oldest first. Scans without a score leave a gap."""
    w, h, pad = 240, 64, 8
    points = [(i, v) for i, v in enumerate(values) if v is not None]
    if not points:
        return Markup("")
    span = max(len(values) - 1, 1)

    def xy(i: int, v: float) -> tuple[float, float]:
        return pad + (w - 2 * pad) * i / span, h - pad - (h - 2 * pad) * v / 100

    line = " ".join("{:.1f},{:.1f}".format(*xy(i, v)) for i, v in points)
    dots = "".join('<circle class="spark-dot" cx="{:.1f}" cy="{:.1f}" r="3.5"><title>{:g}</title></circle>'.format(*xy(i, v), v)
                   for i, v in points)
    return Markup(f'<svg class="spark" viewBox="0 0 {w} {h}" role="img" aria-label="Score history, oldest to newest">'
                  f'<line class="spark-base" x1="{pad}" x2="{w - pad}" y1="{h - pad}" y2="{h - pad}"/>'
                  f'<polyline class="spark-line" fill="none" points="{line}"/>{dots}</svg>')


LANES = [("tracker", "Tracker requests"), ("script_cookie", "Cookies set by scripts"),
         ("server_cookie", "Cookies set by servers"), ("storage", "Storage writes")]


def _ticks(t_max_ms: float) -> list[int]:
    for step in (1, 2, 5, 10, 15, 20, 30, 60):
        if t_max_ms / 1000 / step <= 10:
            return list(range(0, int(t_max_ms // 1000) + 1, step))
    return [0]


def timeline_svg(marks: list[dict], t_max_ms: int, click_ms: int | None, click_label: str, load_ms: int | None) -> Markup:
    """One run on a time axis. marks: [{lane, t_ms, label, flag}], flag True for a non-necessary cookie or a tracker."""
    left, right, top, lane_h = 196, 20, 34, 38
    width = 1010
    plot_w = width - left - right
    t_max = max(t_max_ms, 1000)
    height = top + lane_h * len(LANES) + 26

    def x(t: float) -> float:
        return left + plot_w * min(max(t, 0), t_max) / t_max

    parts = []
    split = x(click_ms) if click_ms is not None else left + plot_w
    parts.append(f'<rect class="tl-before" x="{left}" y="{top}" width="{split - left:.1f}" height="{lane_h * len(LANES)}"/>')
    for i, (_key, label) in enumerate(LANES):
        y = top + i * lane_h
        parts.append(f'<line class="tl-lane" x1="{left}" x2="{left + plot_w}" y1="{y + lane_h}" y2="{y + lane_h}"/>')
        parts.append(f'<text class="tl-lane-label" x="{left - 12}" y="{y + lane_h / 2 + 4}" text-anchor="end">{escape(label)}</text>')
    for s in _ticks(t_max):
        tx = x(s * 1000)
        parts.append(f'<line class="tl-tick" x1="{tx:.1f}" x2="{tx:.1f}" y1="{top - 6}" y2="{top}"/>')
        parts.append(f'<text class="tl-tick-label" x="{tx:.1f}" y="{top - 12}" text-anchor="middle">{s} s</text>')
    if load_ms is not None and load_ms < t_max:
        lx = x(load_ms)
        parts.append(f'<line class="tl-load" x1="{lx:.1f}" x2="{lx:.1f}" y1="{top}" y2="{top + lane_h * len(LANES)}"/>'
                     f'<text class="tl-load-label" x="{lx + 4:.1f}" y="{top + lane_h * len(LANES) + 16}">page loaded</text>')
    lane_index = {key: i for i, (key, _) in enumerate(LANES)}
    for m in marks:
        i = lane_index[m["lane"]]
        cy = top + i * lane_h + lane_h / 2
        mx = x(m["t_ms"])
        tip = f"{m['t_ms'] / 1000:.1f} s: {m['label']}"
        flag = "tl-flag" if m["flag"] else "tl-calm"
        if m["lane"] == "tracker":
            shape = f'<line class="tl-mark {flag}" x1="{mx:.1f}" x2="{mx:.1f}" y1="{cy - 9:.1f}" y2="{cy + 9:.1f}"/>'
        elif m["lane"] == "storage":
            shape = f'<rect class="tl-mark {flag}" x="{mx - 3.5:.1f}" y="{cy - 3.5:.1f}" width="7" height="7"/>'
        else:
            shape = f'<circle class="tl-mark {flag}" cx="{mx:.1f}" cy="{cy:.1f}" r="4.2"/>'
        parts.append(f"<g><title>{escape(tip)}</title>{shape}</g>")
    if click_ms is not None:
        cx_ = x(click_ms)
        parts.append(f'<line class="tl-click" x1="{cx_:.1f}" x2="{cx_:.1f}" y1="{top - 2}" y2="{top + lane_h * len(LANES)}"/>'
                     f'<text class="tl-click-label" x="{cx_ + 6:.1f}" y="{top + lane_h * len(LANES) + 16}">{escape(click_label)}</text>')
    counts = {k: sum(1 for m in marks if m["lane"] == k) for k, _ in LANES}
    desc = "; ".join(f"{label}: {counts[key]}" for key, label in LANES)
    return Markup(f'<svg class="timeline" viewBox="0 0 {width} {height}" role="img" aria-label="{escape("Timeline. " + desc)}">'
                  + "".join(parts) + "</svg>")
