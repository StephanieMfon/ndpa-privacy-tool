"""
scanner/harness.py

Phase 3, Module 1 — Browser automation harness.

Responsibility: launch a headless browser against one URL, capture the raw
evidence every downstream rule module needs, and save it to disk. This
module does NOT judge compliance — it only observes and records.

Produces a SiteScanResult (see docs/data_format.md) as a JSON file, plus
the raw evidence files (HAR, screenshot, DOM snapshot) it references.

Usage:
    python -m scanner.harness https://example.com.ng
"""

import argparse
import json
import re
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

EVIDENCE_ROOT = Path(__file__).resolve().parent.parent / "data" / "evidence"


def _safe_site_folder_name(url: str) -> str:
    """Turn a URL into a filesystem-safe folder name, e.g. https://kara.com.ng/ -> kara.com.ng"""
    netloc = urlparse(url).netloc or url
    return re.sub(r"[^a-zA-Z0-9.\-]", "_", netloc)


@contextmanager
def launched_page(url: str, timeout_ms: int = 30000, har_path: str | None = None,
                   settle_ms: int = 2000, on_request=None, init_script: str | None = None):
    """
    Shared browser-launch + navigate logic, used by harness.py, consent_capture.py,
    and full_scan.py, so none of them drift out of sync on viewport, timeout,
    or settle behaviour.

    `on_request`, if given, is attached BEFORE navigation starts (critical —
    attaching after goto() misses every request made during initial load).

    `init_script`, if given, is injected via context.add_init_script() BEFORE
    navigation — runs before any of the page's own scripts, so it can safely
    monkey-patch browser APIs (used by full_scan.py for SB-04 fingerprinting
    detection). None by default; existing callers are unaffected.

    Yields (page, context, start_time). start_time is a time.monotonic()
    reference so callers can timestamp events (clicks, cookie changes)
    consistently with any network_log timestamps recorded via on_request.
    """
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"URL must include scheme (http:// or https://): {url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context_kwargs = {"viewport": {"width": 1366, "height": 768}}
        if har_path:
            context_kwargs["record_har_path"] = har_path
        context = browser.new_context(**context_kwargs)

        if init_script:
            context.add_init_script(init_script)

        page = context.new_page()
        start_time = time.monotonic()

        if on_request:
            page.on("request", on_request)

        try:
            page.goto(url, timeout=timeout_ms, wait_until="networkidle")
        except PlaywrightTimeoutError:
            page.wait_for_load_state("domcontentloaded")

        page.wait_for_timeout(settle_ms)

        try:
            yield page, context, start_time
        finally:
            context.close()
            browser.close()


def scan_site(url: str, timeout_ms: int = 30000) -> dict:
    """
    Launch headless Chromium, load `url`, capture evidence.

    Returns a SiteScanResult dict (also written to disk as scan_result.json
    inside the site's evidence folder).
    """
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"URL must include scheme (http:// or https://): {url}")

    scanned_at = datetime.now(timezone.utc).isoformat()
    site_folder = EVIDENCE_ROOT / _safe_site_folder_name(url) / scanned_at.replace(":", "-")
    site_folder.mkdir(parents=True, exist_ok=True)

    har_path = site_folder / "network.har"
    screenshot_path = site_folder / "screenshot.png"
    dom_path = site_folder / "dom_snapshot.html"
    result_path = site_folder / "scan_result.json"

    # Record raw monotonic time per request (single listener, attached
    # before navigation starts so early requests aren't missed). Normalized
    # to "seconds since start_time" once start_time is available below.
    raw_requests = []

    def _on_request(request):
        raw_requests.append((time.monotonic(), request.url, request.resource_type, request.method))

    with launched_page(url, timeout_ms=timeout_ms, har_path=str(har_path),
                        on_request=_on_request) as (page, context, start_time):
        page.screenshot(path=str(screenshot_path), full_page=False)
        dom_path.write_text(page.content(), encoding="utf-8")
        cookies = context.cookies()

    network_log = [
        {"url": u, "timestamp": round(t - start_time, 4), "resource_type": rt, "method": m}
        for (t, u, rt, m) in raw_requests
    ]

    result = {
        "url": url,
        "scanned_at": scanned_at,
        "har_path": str(har_path.relative_to(EVIDENCE_ROOT.parent.parent)),
        "screenshot_path": str(screenshot_path.relative_to(EVIDENCE_ROOT.parent.parent)),
        "dom_path": str(dom_path.relative_to(EVIDENCE_ROOT.parent.parent)),
        "cookies": [
            {
                "name": c.get("name"),
                "domain": c.get("domain"),
                "path": c.get("path"),
                "secure": c.get("secure"),
                "httpOnly": c.get("httpOnly"),
                "sameSite": c.get("sameSite"),
                "expires": c.get("expires"),  # -1 means session cookie
            }
            for c in cookies
        ],
        "network_log": network_log,
        "consent_events": {
            "accept_clicked_at": None,
            "reject_clicked_at": None,
        },
    }

    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description="Run the NDPA harness against one site.")
    parser.add_argument("url", help="Full URL including scheme, e.g. https://example.com.ng")
    args = parser.parse_args()

    result = scan_site(args.url)

    print(f"\nScan complete for {args.url}")
    print(f"  Cookies captured : {len(result['cookies'])}")
    print(f"  Requests captured: {len(result['network_log'])}")
    print(f"  HAR file         : {result['har_path']}")
    print(f"  Screenshot       : {result['screenshot_path']}")
    print(f"  DOM snapshot     : {result['dom_path']}")
    print(f"  Full result JSON : {result['url']} -> see scan_result.json in the evidence folder\n")


if __name__ == "__main__":
    sys.exit(main())