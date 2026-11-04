# """
# scanner/consent_capture.py

# Phase 3, Module 3 (capture half) — drives live browser interaction to
# gather the evidence CN-01 to CN-07 need. Unlike cookies.py, these rules
# can't be answered from a static scan_result.json — they need to know
# what's actually on screen and what happens when you click things.

# ** UNTESTED AGAINST A REAL SITE. ** This file could not be run against a
# live browser in the environment it was written in. Banner-detection
# heuristics in particular are a best-effort guess at common CMP markup
# (OneTrust, Cookiebot) plus a generic text-based fallback — expect this to
# need real iteration once you run it against your 30-site dataset. This is
# exactly the module your own plan flags as needing manual checks across
# several different banner vendors before trusting it.

# Produces a ConsentCaptureResult dict, saved alongside scan_result.json and
# merged into it under the "consent_capture" key. scanner/rules/consent.py
# (pure logic, fully unit-tested) turns this into CN-01–07 RuleResults.

# Usage:
#     python -m scanner.consent_capture https://example.com.ng
# """

# import argparse
# import json
# import sys
# import time
# from pathlib import Path

# from scanner.harness import launched_page, EVIDENCE_ROOT, _safe_site_folder_name
# from datetime import datetime, timezone

# # Known CMP container selectors — checked first since they're unambiguous.
# # Extend this list as new vendors are found in the dataset; log the change
# # the same way the Fixed Decisions Register asks for rule changes.
# KNOWN_CMP_SELECTORS = [
#     "#onetrust-banner-sdk",       # OneTrust
#     "#onetrust-consent-sdk",
#     "#CybotCookiebotDialog",      # Cookiebot
#     "div[class*='cookiebot']",
#     "#cookieyes",                 # CookieYes
#     "[data-testid*='cookie-banner']",
# ]

# # Generic fallback: any visible element whose text mentions cookies/consent
# # AND contains a button-like control. Cast wide, then filter, since custom
# # CMPs have no fixed selector.
# GENERIC_BANNER_TEXT_MARKERS = ["cookie", "consent", "privacy preference"]

# ACCEPT_TEXT_MARKERS = ["accept all", "accept", "allow all", "i agree", "agree", "got it"]
# REJECT_TEXT_MARKERS = ["reject all", "reject", "decline", "deny", "necessary only", "manage preferences"]
# WITHDRAWAL_TEXT_MARKERS = ["cookie settings", "privacy settings", "manage cookies", "cookie preferences",
#                             "do not sell", "privacy choices"]

# # Known CMP consent-state storage keys, for CN-06 (consent recorded).
# # Kept in sync with config/essential_cookies.json's cmp_cookies list —
# # those are the cookie-shaped version of this same check.
# CONSENT_STORAGE_KEYS = ["OptanonConsent", "CookieConsent", "cookieyes-consent", "osano_consentmanager"]


# def _find_banner_js():
#     """
#     JS run in-page to locate the consent banner and its buttons.
#     Returns None if nothing found, else a dict with bounding boxes and
#     button info. Written as a single evaluate() call to avoid Python<->JS
#     round-trip timing issues on dynamically-inserted banners.
#     """
#     return """
#     () => {
#         const KNOWN_SELECTORS = %s;
#         const TEXT_MARKERS = %s;

#         function isVisible(el) {
#             const r = el.getBoundingClientRect();
#             const style = window.getComputedStyle(el);
#             return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
#         }

#         function isPlainLike(bgColor) {
#             // Treat transparent AND near-white/no-chroma backgrounds as
#             // "plain" (not a filled/coloured button) — a white button is
#             // visually indistinguishable from "plain text" for CN-04's
#             // purpose, even though it's technically non-transparent.
#             if (!bgColor || bgColor === 'rgba(0, 0, 0, 0)' || bgColor === 'transparent') return true;

#             const rgbMatch = bgColor.match(/rgba?\\(([^)]+)\\)/);
#             if (rgbMatch) {
#                 const parts = rgbMatch[1].split(',').map(s => parseFloat(s.trim()));
#                 const [r, g, b] = parts;
#                 if (r > 240 && g > 240 && b > 240) return true;
#                 return false;
#             }

#             const oklchMatch = bgColor.match(/oklch\\(([^)]+)\\)/);
#             if (oklchMatch) {
#                 const parts = oklchMatch[1].trim().split(/\\s+/).map(parseFloat);
#                 const [l, c] = parts;
#                 if (l > 0.95 && c < 0.02) return true;
#                 return false;
#             }

#             return false; // unknown colour format — default to "not plain" rather than silently under-flagging
#         }

#         let banner = null;
#         for (const sel of KNOWN_SELECTORS) {
#             const el = document.querySelector(sel);
#             if (el && isVisible(el)) { banner = el; break; }
#         }

#         if (!banner) {
#             // Generic fallback: scan elements for cookie/consent text with
#             // a fixed/sticky position (a banner that's part of normal page
#             // flow, not fixed, is unlikely to be a consent banner).
#             const candidates = Array.from(document.querySelectorAll('div, section, aside'));
#             for (const el of candidates) {
#                 if (!isVisible(el)) continue;
#                 const style = window.getComputedStyle(el);
#                 if (!['fixed', 'sticky'].includes(style.position)) continue;
#                 const text = (el.innerText || '').toLowerCase();
#                 if (TEXT_MARKERS.some(m => text.includes(m)) && el.querySelectorAll('button, a[role="button"], a').length > 0) {
#                     banner = el;
#                     break;
#                 }
#             }
#         }

#         if (!banner) return null;

#         const rect = banner.getBoundingClientRect();
#         const buttons = Array.from(banner.querySelectorAll('button, a[role="button"], a, input[type="button"]'))
#             .filter(isVisible)
#             .map(btn => {
#                 const r = btn.getBoundingClientRect();
#                 const style = window.getComputedStyle(btn);
#                 return {
#                     text: (btn.innerText || btn.value || '').trim().toLowerCase(),
#                     background_color: style.backgroundColor,
#                     is_filled: !isPlainLike(style.backgroundColor),
#                     x: r.x, y: r.y, width: r.width, height: r.height,
#                 };
#             });

#         return {
#             top: rect.top,
#             left: rect.left,
#             width: rect.width,
#             height: rect.height,
#             viewport_height: window.innerHeight,
#             buttons: buttons,
#         };
#     }
#     """ % (json.dumps(KNOWN_CMP_SELECTORS), json.dumps(GENERIC_BANNER_TEXT_MARKERS))


# def _match_button(buttons: list, markers: list) -> dict | None:
#     for btn in buttons:
#         if any(marker in btn["text"] for marker in markers):
#             return btn
#     return None


# def capture_consent_interaction(url: str, timeout_ms: int = 30000) -> dict:
#     """
#     Load `url`, locate the consent banner, record its position and button
#     styling (without clicking), then click Accept and check what changes.

#     Reject is NOT clicked in this pass — only its presence, text, and
#     styling are recorded. Clicking Accept is the standard evaluation path
#     (matches how a typical visitor interacts with the site); a full
#     reject-path comparison is a documented limitation, not implemented here
#     — see notes in the returned dict.
#     """
#     result = {
#         "banner_detected": False,
#         "banner_position": None,
#         "accept_button": None,
#         "reject_button": None,
#         "granular_toggles_found": [],
#         "cookies_before_consent": [],
#         "consent_click_timestamp": None,
#         "cookies_after_accept": [],
#         "consent_persisted_after_reload": None,
#         "consent_state_storage_found": False,
#         "withdrawal_mechanism_found": False,
#         "withdrawal_mechanism_text": None,
#         "notes": "Reject button presence/styling recorded but not clicked. "
#                  "Full reject-path cookie comparison not implemented in this pass.",
#     }

#     with launched_page(url, timeout_ms=timeout_ms) as (page, context, start_time):
#         cookies_before = context.cookies()
#         result["cookies_before_consent"] = [c["name"] for c in cookies_before]

#         banner_data = page.evaluate(_find_banner_js())

#         if banner_data:
#             result["banner_detected"] = True
#             top_ratio = banner_data["top"] / banner_data["viewport_height"] if banner_data["viewport_height"] else None
#             result["banner_position"] = {
#                 "top": banner_data["top"],
#                 "viewport_height": banner_data["viewport_height"],
#                 "top_ratio": top_ratio,
#             }

#             buttons = banner_data["buttons"]
#             accept_btn = _match_button(buttons, ACCEPT_TEXT_MARKERS)
#             reject_btn = _match_button(buttons, REJECT_TEXT_MARKERS)

#             if accept_btn:
#                 result["accept_button"] = {
#                     "found": True, "text": accept_btn["text"],
#                     "is_filled": accept_btn["is_filled"],
#                     "background_color": accept_btn["background_color"],
#                 }
#             if reject_btn:
#                 result["reject_button"] = {
#                     "found": True, "text": reject_btn["text"],
#                     "is_filled": reject_btn["is_filled"],
#                     "background_color": reject_btn["background_color"],
#                     "reached_via": "banner",  # settings-panel discovery not implemented in this pass
#                 }
#             else:
#                 result["reject_button"] = {"found": False}

#             # Granular toggles: look for checkbox/switch inputs with a
#             # nearby label mentioning common category names.
#             try:
#                 toggle_labels = page.evaluate("""
#                     () => Array.from(document.querySelectorAll('input[type=checkbox], [role=switch]'))
#                         .map(el => (el.closest('label')?.innerText || el.getAttribute('aria-label') || '').toLowerCase())
#                         .filter(t => t.length > 0)
#                 """)
#                 categories = ["analytics", "advertising", "marketing", "functional", "performance"]
#                 result["granular_toggles_found"] = sorted(set(
#                     cat for cat in categories for label in toggle_labels if cat in label
#                 ))
#             except Exception:
#                 pass

#             # Click Accept, record timestamp, capture post-click cookies.
#             if accept_btn:
#                 try:
#                     page.evaluate("""
#                         (btnText) => {
#                             const btns = Array.from(document.querySelectorAll('button, a[role="button"], a, input[type="button"]'));
#                             const match = btns.find(b => (b.innerText || b.value || '').trim().toLowerCase() === btnText);
#                             if (match) match.click();
#                         }
#                     """, accept_btn["text"])
#                     result["consent_click_timestamp"] = round(time.monotonic() - start_time, 4)
#                     page.wait_for_timeout(1500)
#                     cookies_after = context.cookies()
#                     result["cookies_after_accept"] = [c["name"] for c in cookies_after]
#                 except Exception as e:
#                     result["notes"] += f" Accept click failed: {e}"

#         # Withdrawal mechanism: search whole page (typically footer) for a
#         # persistent settings link, independent of whether a banner was found.
#         try:
#             withdrawal = page.evaluate("""
#                 (markers) => {
#                     const links = Array.from(document.querySelectorAll('a, button'));
#                     for (const el of links) {
#                         const text = (el.innerText || '').trim().toLowerCase();
#                         if (markers.some(m => text.includes(m))) return text;
#                     }
#                     return null;
#                 }
#             """, WITHDRAWAL_TEXT_MARKERS)
#             if withdrawal:
#                 result["withdrawal_mechanism_found"] = True
#                 result["withdrawal_mechanism_text"] = withdrawal
#         except Exception:
#             pass

#         # Consent-state storage: check cookies + localStorage for known CMP keys.
#         try:
#             cookie_names = {c["name"] for c in context.cookies()}
#             if any(k in cookie_names for k in CONSENT_STORAGE_KEYS):
#                 result["consent_state_storage_found"] = True
#             else:
#                 local_storage_keys = page.evaluate("() => Object.keys(window.localStorage || {})")
#                 if any(k in local_storage_keys for k in CONSENT_STORAGE_KEYS):
#                     result["consent_state_storage_found"] = True
#         except Exception:
#             pass

#         # Reload and check if banner reappears — if it doesn't, consent persisted (CN-06).
#         if result["banner_detected"] and result["consent_click_timestamp"] is not None:
#             try:
#                 page.reload(timeout=timeout_ms, wait_until="networkidle")
#                 page.wait_for_timeout(1500)
#                 banner_on_reload = page.evaluate(_find_banner_js())
#                 result["consent_persisted_after_reload"] = banner_on_reload is None
#             except Exception:
#                 result["consent_persisted_after_reload"] = None

#     return result


# def main():
#     parser = argparse.ArgumentParser(description="Run consent interaction capture against one site.")
#     parser.add_argument("url")
#     args = parser.parse_args()

#     result = capture_consent_interaction(args.url)

#     scanned_at = datetime.now(timezone.utc).isoformat()
#     site_folder = EVIDENCE_ROOT / _safe_site_folder_name(args.url) / f"consent_{scanned_at.replace(':', '-')}"
#     site_folder.mkdir(parents=True, exist_ok=True)
#     out_path = site_folder / "consent_capture.json"
#     out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

#     print(f"\nConsent capture complete for {args.url}")
#     print(json.dumps(result, indent=2))
#     print(f"\nSaved to {out_path}\n")


# if __name__ == "__main__":
#     sys.exit(main())



"""
scanner/consent_capture.py

Phase 3, Module 3 (capture half) — drives live browser interaction to
gather the evidence CN-01 to CN-07 need. Unlike cookies.py, these rules
can't be answered from a static scan_result.json — they need to know
what's actually on screen and what happens when you click things.

** UNTESTED AGAINST A REAL SITE. ** This file could not be run against a
live browser in the environment it was written in. Banner-detection
heuristics in particular are a best-effort guess at common CMP markup
(OneTrust, Cookiebot) plus a generic text-based fallback — expect this to
need real iteration once you run it against your 30-site dataset. This is
exactly the module your own plan flags as needing manual checks across
several different banner vendors before trusting it.

Produces a ConsentCaptureResult dict, saved alongside scan_result.json and
merged into it under the "consent_capture" key. scanner/rules/consent.py
(pure logic, fully unit-tested) turns this into CN-01–07 RuleResults.

Usage:
    python -m scanner.consent_capture https://example.com.ng
"""

import argparse
import json
import sys
import time
from pathlib import Path

from scanner.harness import launched_page, EVIDENCE_ROOT, _safe_site_folder_name
from datetime import datetime, timezone

# Known CMP container selectors — checked first since they're unambiguous.
# Extend this list as new vendors are found in the dataset; log the change
# the same way the Fixed Decisions Register asks for rule changes.
KNOWN_CMP_SELECTORS = [
    "#onetrust-banner-sdk",       # OneTrust
    "#onetrust-consent-sdk",
    "#CybotCookiebotDialog",      # Cookiebot
    "div[class*='cookiebot']",
    "#cookieyes",                 # CookieYes
    "[data-testid*='cookie-banner']",
]

# Generic fallback: any visible element whose text mentions cookies/consent
# AND contains a button-like control. Cast wide, then filter, since custom
# CMPs have no fixed selector.
GENERIC_BANNER_TEXT_MARKERS = ["cookie", "consent", "privacy preference"]

ACCEPT_TEXT_MARKERS = ["accept all", "accept", "allow all", "i agree", "agree", "got it"]
REJECT_TEXT_MARKERS = ["reject all", "reject", "decline", "deny", "necessary only", "manage preferences"]
WITHDRAWAL_TEXT_MARKERS = ["cookie settings", "privacy settings", "manage cookies", "cookie preferences",
                            "do not sell", "privacy choices"]

# Known CMP consent-state storage keys, for CN-06 (consent recorded).
# Kept in sync with config/essential_cookies.json's cmp_cookies list —
# those are the cookie-shaped version of this same check.
CONSENT_STORAGE_KEYS = ["OptanonConsent", "CookieConsent", "cookieyes-consent", "osano_consentmanager"]


def _find_banner_js():
    """
    JS run in-page to locate the consent banner and its buttons.
    Returns None if nothing found, else a dict with bounding boxes and
    button info. Written as a single evaluate() call to avoid Python<->JS
    round-trip timing issues on dynamically-inserted banners.
    """
    return """
    () => {
        const KNOWN_SELECTORS = %s;
        const TEXT_MARKERS = %s;

        function isVisible(el) {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
        }

        function isPlainLike(bgColor) {
            // Treat transparent AND near-white/no-chroma backgrounds as
            // "plain" (not a filled/coloured button) — a white button is
            // visually indistinguishable from "plain text" for CN-04's
            // purpose, even though it's technically non-transparent.
            if (!bgColor || bgColor === 'rgba(0, 0, 0, 0)' || bgColor === 'transparent') return true;

            const rgbMatch = bgColor.match(/rgba?\\(([^)]+)\\)/);
            if (rgbMatch) {
                const parts = rgbMatch[1].split(',').map(s => parseFloat(s.trim()));
                const [r, g, b] = parts;
                if (r > 240 && g > 240 && b > 240) return true;
                return false;
            }

            const oklchMatch = bgColor.match(/oklch\\(([^)]+)\\)/);
            if (oklchMatch) {
                const parts = oklchMatch[1].trim().split(/\\s+/).map(parseFloat);
                const [l, c] = parts;
                if (l > 0.95 && c < 0.02) return true;
                return false;
            }

            return false; // unknown colour format — default to "not plain" rather than silently under-flagging
        }

        let banner = null;
        for (const sel of KNOWN_SELECTORS) {
            const el = document.querySelector(sel);
            if (el && isVisible(el)) { banner = el; break; }
        }

        if (!banner) {
            // Generic fallback: scan elements for cookie/consent text with
            // a fixed/sticky position (a banner that's part of normal page
            // flow, not fixed, is unlikely to be a consent banner).
            const candidates = Array.from(document.querySelectorAll('div, section, aside'));
            for (const el of candidates) {
                if (!isVisible(el)) continue;
                const style = window.getComputedStyle(el);
                if (!['fixed', 'sticky'].includes(style.position)) continue;
                const text = (el.innerText || '').toLowerCase();
                if (TEXT_MARKERS.some(m => text.includes(m)) && el.querySelectorAll('button, a[role="button"], a').length > 0) {
                    banner = el;
                    break;
                }
            }
        }

        if (!banner) return null;

        const rect = banner.getBoundingClientRect();
        const buttons = Array.from(banner.querySelectorAll('button, a[role="button"], a, input[type="button"]'))
            .filter(isVisible)
            .map(btn => {
                const r = btn.getBoundingClientRect();
                const style = window.getComputedStyle(btn);
                return {
                    text: (btn.innerText || btn.value || '').trim().toLowerCase(),
                    background_color: style.backgroundColor,
                    is_filled: !isPlainLike(style.backgroundColor),
                    x: r.x, y: r.y, width: r.width, height: r.height,
                };
            });

        return {
            top: rect.top,
            left: rect.left,
            width: rect.width,
            height: rect.height,
            viewport_height: window.innerHeight,
            buttons: buttons,
        };
    }
    """ % (json.dumps(KNOWN_CMP_SELECTORS), json.dumps(GENERIC_BANNER_TEXT_MARKERS))


def _match_button(buttons: list, markers: list) -> dict | None:
    for btn in buttons:
        if any(marker in btn["text"] for marker in markers):
            return btn
    return None


def run_consent_interaction(page, context, start_time: float, timeout_ms: int = 30000) -> dict:
    """
    The reusable core: given an ALREADY-OPEN page/context (caller has
    already navigated and settled), locate the banner, record button
    styling, click Accept, check what persists. Does not launch or
    navigate anything itself — that's the caller's job, so this same logic
    can run either as its own session (capture_consent_interaction, below)
    or inside a larger single-session scan (scanner/full_scan.py) sharing
    one clock with the rest of that scan's evidence.

    Reject is NOT clicked — only its presence, text, and styling are
    recorded. Clicking Accept is the standard evaluation path; a full
    reject-path cookie comparison is a documented limitation, not
    implemented here — see notes in the returned dict.
    """
    result = {
        "banner_detected": False,
        "banner_position": None,
        "accept_button": None,
        "reject_button": None,
        "granular_toggles_found": [],
        "cookies_before_consent": [],
        "consent_click_timestamp": None,
        "cookies_after_accept": [],
        "consent_persisted_after_reload": None,
        "consent_state_storage_found": False,
        "withdrawal_mechanism_found": False,
        "withdrawal_mechanism_text": None,
        "notes": "Reject button presence/styling recorded but not clicked. "
                 "Full reject-path cookie comparison not implemented in this pass.",
    }

    cookies_before = context.cookies()
    result["cookies_before_consent"] = [c["name"] for c in cookies_before]

    banner_data = page.evaluate(_find_banner_js())

    if banner_data:
        result["banner_detected"] = True
        top_ratio = banner_data["top"] / banner_data["viewport_height"] if banner_data["viewport_height"] else None
        result["banner_position"] = {
            "top": banner_data["top"],
            "viewport_height": banner_data["viewport_height"],
            "top_ratio": top_ratio,
        }

        buttons = banner_data["buttons"]
        accept_btn = _match_button(buttons, ACCEPT_TEXT_MARKERS)
        reject_btn = _match_button(buttons, REJECT_TEXT_MARKERS)

        if accept_btn:
            result["accept_button"] = {
                "found": True, "text": accept_btn["text"],
                "is_filled": accept_btn["is_filled"],
                "background_color": accept_btn["background_color"],
            }
        if reject_btn:
            result["reject_button"] = {
                "found": True, "text": reject_btn["text"],
                "is_filled": reject_btn["is_filled"],
                "background_color": reject_btn["background_color"],
                "reached_via": "banner",  # settings-panel discovery not implemented in this pass
            }
        else:
            result["reject_button"] = {"found": False}

        # Granular toggles: look for checkbox/switch inputs with a
        # nearby label mentioning common category names.
        try:
            toggle_labels = page.evaluate("""
                () => Array.from(document.querySelectorAll('input[type=checkbox], [role=switch]'))
                    .map(el => (el.closest('label')?.innerText || el.getAttribute('aria-label') || '').toLowerCase())
                    .filter(t => t.length > 0)
            """)
            categories = ["analytics", "advertising", "marketing", "functional", "performance"]
            result["granular_toggles_found"] = sorted(set(
                cat for cat in categories for label in toggle_labels if cat in label
            ))
        except Exception:
            pass

        # Click Accept, record timestamp, capture post-click cookies.
        if accept_btn:
            try:
                page.evaluate("""
                    (btnText) => {
                        const btns = Array.from(document.querySelectorAll('button, a[role="button"], a, input[type="button"]'));
                        const match = btns.find(b => (b.innerText || b.value || '').trim().toLowerCase() === btnText);
                        if (match) match.click();
                    }
                """, accept_btn["text"])
                result["consent_click_timestamp"] = round(time.monotonic() - start_time, 4)
                page.wait_for_timeout(1500)
                cookies_after = context.cookies()
                result["cookies_after_accept"] = [c["name"] for c in cookies_after]
            except Exception as e:
                result["notes"] += f" Accept click failed: {e}"

    # Withdrawal mechanism: search whole page (typically footer) for a
    # persistent settings link, independent of whether a banner was found.
    try:
        withdrawal = page.evaluate("""
            (markers) => {
                const links = Array.from(document.querySelectorAll('a, button'));
                for (const el of links) {
                    const text = (el.innerText || '').trim().toLowerCase();
                    if (markers.some(m => text.includes(m))) return text;
                }
                return null;
            }
        """, WITHDRAWAL_TEXT_MARKERS)
        if withdrawal:
            result["withdrawal_mechanism_found"] = True
            result["withdrawal_mechanism_text"] = withdrawal
    except Exception:
        pass

    # Consent-state storage: check cookies + localStorage for known CMP keys.
    try:
        cookie_names = {c["name"] for c in context.cookies()}
        if any(k in cookie_names for k in CONSENT_STORAGE_KEYS):
            result["consent_state_storage_found"] = True
        else:
            local_storage_keys = page.evaluate("() => Object.keys(window.localStorage || {})")
            if any(k in local_storage_keys for k in CONSENT_STORAGE_KEYS):
                result["consent_state_storage_found"] = True
    except Exception:
        pass

    # Reload and check if banner reappears — if it doesn't, consent persisted (CN-06).
    if result["banner_detected"] and result["consent_click_timestamp"] is not None:
        try:
            page.reload(timeout=timeout_ms, wait_until="networkidle")
            page.wait_for_timeout(1500)
            banner_on_reload = page.evaluate(_find_banner_js())
            result["consent_persisted_after_reload"] = banner_on_reload is None
        except Exception:
            result["consent_persisted_after_reload"] = None

    return result


def capture_consent_interaction(url: str, timeout_ms: int = 30000) -> dict:
    """
    Standalone entry point — launches its own single-page session and runs
    run_consent_interaction() against it. UNCHANGED behavior/output shape
    from the original version of this function; only the internals were
    reorganized so the interaction logic could be reused by
    scanner/full_scan.py without duplicating it.
    """
    with launched_page(url, timeout_ms=timeout_ms) as (page, context, start_time):
        return run_consent_interaction(page, context, start_time, timeout_ms=timeout_ms)


def main():
    parser = argparse.ArgumentParser(description="Run consent interaction capture against one site.")
    parser.add_argument("url")
    args = parser.parse_args()

    result = capture_consent_interaction(args.url)

    scanned_at = datetime.now(timezone.utc).isoformat()
    site_folder = EVIDENCE_ROOT / _safe_site_folder_name(args.url) / f"consent_{scanned_at.replace(':', '-')}"
    site_folder.mkdir(parents=True, exist_ok=True)
    out_path = site_folder / "consent_capture.json"
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(f"\nConsent capture complete for {args.url}")
    print(json.dumps(result, indent=2))
    print(f"\nSaved to {out_path}\n")


if __name__ == "__main__":
    sys.exit(main())