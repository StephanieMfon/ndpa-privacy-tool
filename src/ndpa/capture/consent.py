"""Consent banner: find it, classify its controls, click Accept or Reject (rulebook 0.4, runs 2 and 3)."""
import re
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeout

from ndpa.capture.events import EventLog
from ndpa.models import Condition, ConsentObservation

CONSENT_JS = Path(__file__).with_name("consent.js").read_text(encoding="utf-8")

MIN_COVERAGE = 1 / 9       # register R4: banner box covers at least 1 of 9 grid cells
BOTTOM_ROW_START = 2 / 3   # register R4: the bottom grid row starts here
REOPEN_LEXICON = ("cookie settings", "cookie preferences", "manage cookies", "privacy settings",
                  "consent settings", "manage consent", "your privacy choices")
REOPEN_WIDGETS = ("#ot-sdk-btn-floating", "#ot-sdk-btn", ".cky-btn-revisit-wrapper", "#CookiebotWidget")

_CLOSE = re.compile(r"^(×|✕|✖|x|close|dismiss)$", re.I)
_REJECT = re.compile(
    r"\b(reject|decline|deny|refuse|disagree)\b|necessary only|only necessary|essential only|"
    r"only essential|do not accept|don't accept|do not allow|necessary cookies only|use necessary", re.I)
_SETTINGS = re.compile(r"\b(manage|preferences?|settings|customi[sz]e|options|choices)\b", re.I)
_ACCEPT = re.compile(r"\b(accept|agree|allow|ok|okay|got it|i understand|understood|continue)\b", re.I)


def classify_control(text: str, aria: str = "") -> str | None:
    """accept / reject / settings / close, or None. Rulebook CN-03: 'OK' and 'Got it' are Accept; x is Close."""
    text, aria = (text or "").strip(), (aria or "").strip()
    if _CLOSE.match(text) or (not text and _CLOSE.search(aria)):
        return "close"
    label = text or aria
    if _REJECT.search(label):
        return "reject"
    if _SETTINGS.search(label):
        return "settings"
    if _ACCEPT.search(label):
        return "accept"
    return None


def classify_geometry(bbox: dict, viewport: dict) -> dict:
    """Banner position and the R4 grid test, from the banner box and the viewport size."""
    vw, vh = viewport["width"], viewport["height"]
    x0, y0 = max(bbox["x"], 0), max(bbox["y"], 0)
    x1, y1 = min(bbox["x"] + bbox["width"], vw), min(bbox["y"] + bbox["height"], vh)
    w, h = max(x1 - x0, 0), max(y1 - y0, 0)
    coverage = (w * h) / (vw * vh)
    bottom_only = y0 >= vh * BOTTOM_ROW_START - 1
    top_only = y1 <= vh / 3 + 1
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    if w >= 0.95 * vw and h >= 0.95 * vh:
        position = "full_screen"
    elif bottom_only:
        position = "bottom"
    elif top_only:
        position = "top"
    elif vw / 3 <= cx <= 2 * vw / 3 and vh / 3 <= cy <= 2 * vh / 3:
        position = "centre_modal"
    elif cx < vw / 3:
        position = "left"
    elif cx > 2 * vw / 3:
        position = "right"
    elif cy > 2 * vh / 3:
        position = "bottom"
    elif cy < vh / 3:
        position = "top"
    else:
        position = "other"
    return {"position": position, "coverage": round(coverage, 4), "bottom_row_only": bottom_only,
            "passes_r4": coverage >= MIN_COVERAGE and not bottom_only}


def roles(controls: list[dict]) -> dict[str, dict]:
    """First control of each role, e.g. {'accept': {...}, 'reject': {...}}."""
    found: dict[str, dict] = {}
    for c in controls:
        role = classify_control(c["text"], c["aria"])
        if role and role not in found:
            found[role] = c
    return found


def _info(control: dict, reached_via: str) -> dict:
    return {"text": control["text"] or control["aria"], "reached_via": reached_via}


def describe_first_layer(banner: dict | None, first_seen_ms: int | None) -> ConsentObservation:
    obs = ConsentObservation()
    if not banner:
        return obs
    obs.banner_found = True
    obs.banner_first_seen_ms = first_seen_ms
    obs.banner_via = banner["via"]
    obs.banner_bbox = banner["bbox"]
    obs.banner_geometry = classify_geometry(banner["bbox"], banner["viewport"])
    obs.banner_text = banner["text"]
    found = roles(banner["controls"])
    obs.accept_control = _info(found["accept"], "banner") if "accept" in found else None
    obs.reject_control = _info(found["reject"], "banner") if "reject" in found else None
    obs.settings_control = _info(found["settings"], "banner") if "settings" in found else None
    obs.close_control = _info(found["close"], "banner") if "close" in found else None
    return obs


def _find(page, mark: bool = False, token: str = "m0") -> dict | None:
    try:
        return page.evaluate(CONSENT_JS, {"fn": "banner", "mark": mark, "token": token})
    except Exception:  # noqa: BLE001  (page was navigating)
        return None


def watch_banner(page, log: EventLog, seconds: float, poll_s: float = 0.5) -> tuple[dict | None, int | None]:
    """Observe with no interaction. Returns the banner as last seen and when it was first seen (ms)."""
    banner, first_seen = None, None
    waited = 0.0
    while True:
        found = _find(page)
        if found:
            banner = found
            if first_seen is None:
                first_seen = log.now_ms()
        if waited >= seconds:
            return banner, first_seen
        step = min(poll_s, seconds - waited)
        page.wait_for_timeout(step * 1000)
        waited += step


def _click(page, control: dict) -> None:
    page.locator(f'[data-ndpa-i="{control["key"]}"]').first.click(timeout=5000)


def act(page, log: EventLog, condition: Condition, observe_s: float, obs: ConsentObservation,
        after_click_png: Path | None = None) -> None:
    """Click Accept or Reject (stamped on the run clock), observe, reload, check the banner and re-open control."""
    role = "accept" if condition == Condition.ACCEPT else "reject"
    live = _find(page, mark=True, token=f"m{log.now_ms()}")
    if live is None:
        obs.note = "banner not found when the click was due"
        return
    found = roles(live["controls"])
    target, reached_via = found.get(role), "banner"
    if target is None and role == "reject" and "settings" in found:
        log.add("consent_panel_open", label=found["settings"]["text"])
        _click(page, found["settings"])
        page.wait_for_timeout(1500)
        live = _find(page, mark=True, token=f"m{log.now_ms()}")
        target, reached_via = (roles(live["controls"]).get("reject") if live else None), "panel"
        if live:
            obs.panel_text = live["text"]
        if target:
            obs.reject_control = _info(target, "panel")
    if target is None and role == "accept" and "close" in found:
        target, role = found["close"], "close"  # a banner with no Accept: closing is the only consent action
    if target is None:
        obs.note = f"no {role} control found"
        return
    event = log.add("consent_click", action=role, label=target["text"] or target["aria"], reached_via=reached_via)
    try:
        _click(page, target)
    except Exception as exc:  # noqa: BLE001
        event.kind = "consent_click_failed"
        obs.note = f"click failed: {type(exc).__name__}"
        return
    obs.action, obs.click_ms = role, event.t_ms
    page.wait_for_timeout(observe_s * 1000)
    if after_click_png:
        page.screenshot(path=str(after_click_png), full_page=False)
    try:
        page.reload(wait_until="load", timeout=30000)
    except PlaywrightTimeout:
        pass
    page.wait_for_timeout(observe_s * 1000)
    obs.banner_after_reload = _find(page) is not None
    try:
        obs.reopen_control = page.evaluate(
            CONSENT_JS, {"fn": "reopen", "lexicon": list(REOPEN_LEXICON), "widgets": list(REOPEN_WIDGETS)})
    except Exception:  # noqa: BLE001
        obs.reopen_control = None
