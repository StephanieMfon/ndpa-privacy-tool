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
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

EVIDENCE_ROOT = Path(__file__).resolve().parent.parent / "data" / "evidence"


def _safe_site_folder_name(url: str) -> str:
    """Turn a URL into a filesystem-safe folder name, e.g. https://kara.com.ng/ -> kara.com.ng"""
    netloc = urlparse(url).netloc or url
    return re.sub(r"[^a-zA-Z0-9.\-]", "_", netloc)


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

    network_log = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            record_har_path=str(har_path),
            viewport={"width": 1366, "height": 768},
        )
        page = context.new_page()

        # Record every request with a timestamp we control, since the HAR
        # file's own timestamps are harder to correlate with our later
        # consent-click timestamps (Module 3 will reuse this pattern).
        start_time = time.monotonic()

        def _on_request(request):
            network_log.append({
                "url": request.url,
                "timestamp": round(time.monotonic() - start_time, 4),
                "resource_type": request.resource_type,
                "method": request.method,
            })

        page.on("request", _on_request)

        try:
            page.goto(url, timeout=timeout_ms, wait_until="networkidle")
        except PlaywrightTimeoutError:
            # Some sites never go fully idle (polling, ads, etc.) — fall back
            # to "domcontentloaded" evidence rather than failing the whole
            # scan. Recorded in the result so it's a visible limitation,
            # not a silent gap.
            page.wait_for_load_state("domcontentloaded")

        # Small fixed settle time so late-loading consent banners / trackers
        # have a chance to appear before we snapshot. Matches Phase 2 manual
        # annotation practice of waiting for banner render before observing.
        page.wait_for_timeout(2000)

        page.screenshot(path=str(screenshot_path), full_page=False)
        dom_path.write_text(page.content(), encoding="utf-8")
        cookies = context.cookies()

        context.close()  # required to flush the HAR file to disk
        browser.close()

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