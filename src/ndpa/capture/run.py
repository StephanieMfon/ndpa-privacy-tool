"""One capture run: a fresh browser context, one clock, one condition (decisions D-08, D-30).

Usage:
    python -m ndpa.capture.run https://example.com.ng [--conditions no_action,accept,reject]
                               [--observe 10] [--headless] [--bundled-chromium]
"""
import argparse
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

from ndpa.analyse.trackers import SNAPSHOT, TrackerList
from ndpa.capture.blocked import detect_block
from ndpa.capture.consent import act, describe_first_layer, watch_banner
from ndpa.capture.events import EventLog, value_hash
from ndpa.capture.recorder import Recorder
from ndpa.models import Condition, RunResult, RunStatus

HOOKS_JS = Path(__file__).with_name("hooks.js").read_text(encoding="utf-8")


@dataclass
class BrowserConfig:
    channel: str | None = "chrome"  # the real Chrome the annotators use (register R6)
    headless: bool = False
    viewport: tuple[int, int] = (1366, 768)
    locale: str = "en-NG"
    timezone_id: str = "Africa/Lagos"


def _evaluate_list(page, expression: str) -> list[str]:
    try:
        return sorted(page.evaluate(expression))
    except Exception:  # noqa: BLE001
        return []


def capture_run(url: str, out_dir: Path, condition: Condition = Condition.NO_ACTION,
                observe_s: float = 10.0, browser_config: BrowserConfig | None = None,
                trackers: TrackerList | None = None, load_timeout_s: float = 30.0) -> RunResult:
    cfg = browser_config or BrowserConfig()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    log = EventLog()
    recorder = Recorder(url, log, trackers)
    result = RunResult(url=url, condition=condition, status=RunStatus.OK, observe_s=observe_s)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel=cfg.channel, headless=cfg.headless)
        context = browser.new_context(
            viewport={"width": cfg.viewport[0], "height": cfg.viewport[1]},
            locale=cfg.locale, timezone_id=cfg.timezone_id,
            record_har_path=str(out_dir / "network.har"), record_har_content="omit",
        )
        context.expose_function("__ndpa_log", recorder.on_js)
        context.add_init_script(HOOKS_JS)
        page = context.new_page()
        recorder.main_frame = page.main_frame
        page.on("request", recorder.on_request)
        page.on("response", recorder.on_response)

        log.start()  # navigation start: t_ms = 0
        try:
            page.goto(url, timeout=load_timeout_s * 1000, wait_until="load")
        except PlaywrightTimeout:
            result.load_timeout = True  # keep going: whatever loaded is still evidence
        except Exception as exc:  # noqa: BLE001  (DNS failure, connection refused, ...)
            result.status = RunStatus.FAILED
            result.error = (str(exc).splitlines() or [type(exc).__name__])[0][:300]

        if result.status != RunStatus.FAILED:
            # Window 1 (register R7): observe with no interaction, watching for the banner.
            banner, first_seen = watch_banner(page, log, observe_s)
            result.consent = describe_first_layer(banner, first_seen)
            result.consent.pre_click_cookie_names = sorted({c["name"] for c in context.cookies()})
            result.consent.pre_click_local_storage_keys = _evaluate_list(
                page, "() => Object.keys(window.localStorage)")
            dom = page.content()
            (out_dir / "dom_snapshot.html").write_text(dom, encoding="utf-8")
            page.screenshot(path=str(out_dir / "screenshot.png"), full_page=False)
            verdict = detect_block(recorder.main_status, recorder.main_headers, dom)
            if verdict.blocked:
                result.status = RunStatus.BLOCKED
                result.block_reasons = verdict.reasons
            elif condition != Condition.NO_ACTION:
                act(page, log, condition, observe_s, result.consent, out_dir / "after_click.png")

            recorder.resolve_set_cookies()
            result.cookies = [
                {"name": c["name"], "domain": c["domain"], "path": c["path"],
                 "secure": c["secure"], "httpOnly": c["httpOnly"],
                 "sameSite": c.get("sameSite"), "expires": c["expires"],
                 "value_hash": value_hash(c["value"])}
                for c in context.cookies()
            ]
            result.local_storage_keys = _evaluate_list(page, "() => Object.keys(window.localStorage)")
            result.session_storage_keys = _evaluate_list(page, "() => Object.keys(window.sessionStorage)")
            result.indexeddb_names = _evaluate_list(
                page, "() => indexedDB.databases ? indexedDB.databases().then(d => d.map(x => x.name)) : []")

        context.close()  # flushes the HAR file
        browser.close()

    result.events = log.events
    result.files = {f.stem: f.name for f in sorted(out_dir.iterdir()) if f.name != "run.json"}
    (out_dir / "run.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return result


def after_click_activity(r: RunResult) -> dict:
    """What happened after the consent click: tracker requests and cookie sets (rulebook CN-02(b), SB-01 to SB-03)."""
    if r.consent.click_ms is None:
        return {"tracker_requests": 0, "tracker_vendors": [], "cookie_names": []}
    later = [e for e in r.events if e.t_ms >= r.consent.click_ms]
    trackers = [e for e in later if e.kind == "request" and e.detail.get("tracker")]
    names = {e.detail["name"] for e in later if e.kind == "cookie_set_js"}
    for e in later:
        names.update(e.detail.get("set_cookie_names", []))
    return {"tracker_requests": len(trackers),
            "tracker_vendors": sorted({e.vendor for e in trackers if e.vendor}),
            "cookie_names": sorted(names)}


def summary(r: RunResult) -> str:
    requests = [e for e in r.events if e.kind == "request"]
    tracker_requests = [e for e in requests if e.detail.get("tracker")]

    def kinds(kind: str) -> list:
        return [e for e in r.events if e.kind == kind]

    c = r.consent
    geo = c.banner_geometry or {}
    lines = [
        f"status            : {r.status.value} {', '.join(r.block_reasons)}".rstrip(),
        f"error             : {r.error}" if r.error else "error             : none",
        f"requests          : {len(requests)} ({sum(1 for e in requests if e.third_party)} third-party)",
        f"tracker requests  : {len(tracker_requests)} from "
        f"{sorted({e.vendor for e in tracker_requests if e.vendor})}",
        f"cookies in jar    : {len(r.cookies)}, script cookie sets: {len(kinds('cookie_set_js'))} "
        f"({sum(1 for e in kinds('cookie_set_js') if not e.detail.get('attributed'))} unattributed), "
        f"storage sets: {len(kinds('storage_set'))}",
        f"banner            : {'found via ' + str(c.banner_via) if c.banner_found else 'not found'}"
        + (f", {geo.get('position')}, covers {geo.get('coverage')}, passes R4: {geo.get('passes_r4')}, "
           f"first seen {c.banner_first_seen_ms} ms" if c.banner_found else ""),
        f"controls          : accept={c.accept_control}, reject={c.reject_control}, "
        f"settings={c.settings_control}, close={c.close_control}",
    ]
    if r.condition != Condition.NO_ACTION:
        after = after_click_activity(r)
        lines += [
            f"consent action    : {c.action} at {c.click_ms} ms {('(' + c.note + ')') if c.note else ''}".rstrip(),
            f"after the click   : {after['tracker_requests']} tracker requests {after['tracker_vendors']}; "
            f"cookie names set: {after['cookie_names']}",
            f"after reload      : banner again: {c.banner_after_reload}, re-open control: {c.reopen_control!r}",
        ]
    lines.append(f"capture errors    : {len(kinds('capture_error'))}")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Capture runs (no_action, accept, reject) against one site.")
    ap.add_argument("url")
    ap.add_argument("--conditions", default="no_action,accept,reject")
    ap.add_argument("--observe", type=float, default=10.0, help="seconds to wait after load and after the click (R7)")
    ap.add_argument("--headless", action="store_true", help="no visible window")
    ap.add_argument("--bundled-chromium", action="store_true", help="use Playwright's Chromium, not Chrome")
    args = ap.parse_args()

    host = re.sub(r"[^a-zA-Z0-9.\-]", "_", urlparse(args.url).netloc)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    cfg = BrowserConfig(channel=None if args.bundled_chromium else "chrome", headless=args.headless)
    trackers = TrackerList() if SNAPSHOT.exists() else None
    for name in args.conditions.split(","):
        condition = Condition(name.strip())
        out_dir = Path("data/evidence") / host / stamp / condition.value
        print(f"=== {args.url} [{condition.value}]")
        try:
            result = capture_run(args.url, out_dir, condition, args.observe, cfg, trackers)
        except Exception as exc:
            if "chrome" in str(exc).lower() and "not found" in str(exc).lower():
                print("Chrome was not found. Install it, or add --bundled-chromium.")
            raise
        print(summary(result))
        print(f"evidence: {out_dir}\n")
        if result.status != RunStatus.OK:
            print("Stopping: the site could not be captured, so the other runs are skipped.")
            break


if __name__ == "__main__":
    main()
