"""
scanner/full_scan.py

Phase 3, Module 5 support infrastructure — unified single-session scan.

harness.scan_site() and consent_capture.capture_consent_interaction() each
launch their OWN browser session. That's fine for CK/CN rules, which only
need timestamps to be internally consistent within their own module. It
breaks down for SB-01–04, which compare script/cookie/network timestamps
against the consent-click timestamp — a comparison that's only meaningful
if both numbers come from the same page load on the same clock.

run_full_scan() does everything in ONE session: navigate, capture passive
evidence (screenshot/DOM/cookies/network_log — same as harness.py), run
the SAME consent-interaction logic as consent_capture.py
(run_consent_interaction, imported not duplicated) against that same live
page, AND run the fingerprinting-API instrumentation
(fingerprint_instrumentation.js) needed for SB-04. One clock, no
approximation, one browser session for the whole site.

harness.py and consent_capture.py are UNCHANGED in their standalone
behavior — both still work exactly as already tested, useful for
debugging either half in isolation. This is the combined path used for
real per-site scans going forward.

Field semantics, preserved for the already-tested rule modules:
  - "cookies" (top-level) = cookie jar at initial settle, BEFORE any click.
    Identical meaning to harness.py's output — cookies.py's CK-01–05
    results are unchanged for sites already validated against it.
  - "consent_capture" (nested) = identical shape to consent_capture.py's
    standalone output — consent.py's CN-01–07 logic needs no changes,
    just pass result["consent_capture"] as its `capture` argument.
  - "network_log" spans the WHOLE session (through the reload check) — a
    superset of what harness.py alone captured, strictly more data. Each
    entry now also carries "post_data" (best-effort, often None for GET
    requests) — new field, additive, doesn't change how trackers.py or
    any already-tested module reads the existing fields.
  - "fingerprint_log" (new) = every logged call to one of the six
    SB-04-indicative APIs, timestamp-calibrated onto the same clock as
    everything else. Empty list if none were called.

Usage:
    python -m scanner.full_scan https://example.com.ng
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from scanner.harness import launched_page, EVIDENCE_ROOT, _safe_site_folder_name
from scanner.consent_capture import run_consent_interaction
from scanner.policy_capture import capture_policy_evidence

FINGERPRINT_JS_PATH = Path(__file__).resolve().parent / "fingerprint_instrumentation.js"


def run_full_scan(url: str, timeout_ms: int = 30000) -> dict:
    scanned_at = datetime.now(timezone.utc).isoformat()
    site_folder = EVIDENCE_ROOT / _safe_site_folder_name(url) / scanned_at.replace(":", "-")
    site_folder.mkdir(parents=True, exist_ok=True)

    har_path = site_folder / "network.har"
    screenshot_path = site_folder / "screenshot.png"
    dom_path = site_folder / "dom_snapshot.html"
    result_path = site_folder / "scan_result.json"

    raw_requests = []

    def _on_request(request):
        try:
            post_data = request.post_data
        except Exception:
            post_data = None
        raw_requests.append((time.monotonic(), request.url, request.resource_type, request.method, post_data))

    fingerprint_script = FINGERPRINT_JS_PATH.read_text(encoding="utf-8")

    with launched_page(url, timeout_ms=timeout_ms, har_path=str(har_path),
                        on_request=_on_request, init_script=fingerprint_script) as (page, context, start_time):
        # --- Passive evidence at first settle — identical to harness.py ---
        page.screenshot(path=str(screenshot_path), full_page=False)
        dom_path.write_text(page.content(), encoding="utf-8")
        cookies_at_settle = context.cookies()

        # --- Consent interaction, SAME session/clock, logic imported not duplicated ---
        consent = run_consent_interaction(page, context, start_time, timeout_ms=timeout_ms)

        # --- Fingerprint log, calibrated onto the Python clock ---
        # Single calibration point: note Python time and JS performance.now()
        # at (as close as possible to) the same instant, then use the
        # offset to convert every logged call's browser-clock timestamp
        # onto "seconds since start_time" — the same scale network_log and
        # consent_click_timestamp already use. Sub-100ms IPC latency here
        # is negligible against the multi-second correlation window used
        # in check_sb04().
        calibration_python_time = time.monotonic()
        try:
            calibration_perf_now_ms = page.evaluate("() => performance.now()")
            clock_offset = calibration_python_time - (calibration_perf_now_ms / 1000.0)

            fp_log_raw = page.evaluate("() => window.__ndpa_fp_log || []")
            fingerprint_log = [
                {
                    "api": entry["api"],
                    "timestamp": round((entry["perf_now"] / 1000.0 + clock_offset) - start_time, 4),
                    "value_excerpt": entry.get("value_excerpt"),
                }
                for entry in fp_log_raw
            ]
        except Exception:
            fingerprint_log = []

        # --- Privacy policy capture, same session, run LAST so it can't
        # interfere with any timing-sensitive SB-rule measurements above ---
        policy_capture = capture_policy_evidence(page, context, timeout_ms=timeout_ms)

    network_log = [
        {"url": u, "timestamp": round(t - start_time, 4), "resource_type": rt, "method": m, "post_data": pd}
        for (t, u, rt, m, pd) in raw_requests
    ]

    result = {
        "url": url,
        "scanned_at": scanned_at,
        "har_path": str(har_path.relative_to(EVIDENCE_ROOT.parent.parent)),
        "screenshot_path": str(screenshot_path.relative_to(EVIDENCE_ROOT.parent.parent)),
        "dom_path": str(dom_path.relative_to(EVIDENCE_ROOT.parent.parent)),
        "cookies": [
            {
                "name": c.get("name"), "domain": c.get("domain"), "path": c.get("path"),
                "secure": c.get("secure"), "httpOnly": c.get("httpOnly"),
                "sameSite": c.get("sameSite"), "expires": c.get("expires"),
            }
            for c in cookies_at_settle
        ],
        "network_log": network_log,
        "consent_capture": consent,
        "fingerprint_log": fingerprint_log,
        "policy_capture": policy_capture,
    }

    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description="Run the unified full scan (harness + consent + fingerprinting) against one site.")
    parser.add_argument("url")
    args = parser.parse_args()

    result = run_full_scan(args.url)

    print(f"\nFull scan complete for {args.url}")
    print(f"  Cookies (pre-click)   : {len(result['cookies'])}")
    print(f"  Requests captured     : {len(result['network_log'])}")
    print(f"  Banner detected       : {result['consent_capture']['banner_detected']}")
    print(f"  Consent click at      : {result['consent_capture']['consent_click_timestamp']}")
    print(f"  Fingerprint API calls : {len(result['fingerprint_log'])}")
    print(f"  Privacy policy found  : {result['policy_capture']['privacy_policy_reachable']}")
    print(f"  Cookie policy found   : {result['policy_capture']['cookie_policy_reachable']}")
    print(f"  HAR file              : {result['har_path']}")
    print(f"  Screenshot            : {result['screenshot_path']}\n")


if __name__ == "__main__":
    sys.exit(main())