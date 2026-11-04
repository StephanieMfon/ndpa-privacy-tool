"""
scanner/rules/script_behaviour.py

Phase 3, Module 5 — SB-01 to SB-04.

Pure decision logic. SB-01/02/03 reuse evidence already captured by
full_scan.py's passive/consent-interaction layers — no new browser
instrumentation needed for those three:

  - SB-01 (scripts executing before consent) and SB-03 (third-party
    communication before consent) both reuse trackers.detect_trackers()'s
    earliest-seen-timestamp evidence. The Rulebook distinguishes "script
    execution" from "outbound communication" conceptually, but a tracker
    script has to load before it can make further calls, so in practice
    both resolve to the same first-observed-request timestamp here.
    Documented simplification, not a bug — see check_sb01/check_sb03.

  - SB-02 (scripts creating cookies before consent) reuses the SAME
    "non-essential cookie present before consent" evidence as CN-02
    (consent.py's _non_essential_cookies_before_consent — single source
    of truth, not duplicated). The Rulebook frames SB-02 as isolating the
    CAUSAL SCRIPT rather than just the cookie timestamp; true
    script-to-cookie attribution isn't implemented (would need
    Chrome DevTools Protocol-level instrumentation beyond what Playwright's
    cookie API exposes) — this is a documented proxy using the same timing
    evidence, without attribution to which script set which cookie.

If no consent action was ever recorded (no banner, or Accept click never
fired), every detected tracker is treated as occurring "before consent" —
consent that never happens can't have preceded anything, so nothing was
ever gated. This matters for sites like the no-banner case you already
found: every tracker present is scored Non-Compliant under SB-01/SB-03,
which is the substantively correct read even though it wasn't reached via
an explicit before/after comparison.

SB-04 (fingerprinting) needs the fingerprint_instrumentation.js call log
plus network_log/tracker-request data — see check_sb04() below for the
full explanation of its confidence-tiered transmission check.
"""

from urllib.parse import unquote

from scanner.rules.trackers import detect_trackers, all_tracker_requests
from scanner.rules.consent import _non_essential_cookies_before_consent

MEASURE_TEXT_REPEAT_THRESHOLD = 3  # Rulebook: "repeated measureText() calls" — a single call alone isn't indicative
TRANSMISSION_WINDOW_SECONDS = 3.0  # correlation window for SB-04's weaker (timing) transmission signal
VALUE_MATCH_PREFIX_LENGTH = 24  # only compare a leading slice of the captured value, not the whole thing —
                                  # trackers commonly truncate or hash a value before sending it, so requiring
                                  # the ENTIRE captured excerpt to appear verbatim would miss a genuine partial
                                  # transmission. Caught via a real browser test: the captured value was 64
                                  # characters, the transmitted value was only 40 — a full-string match failed
                                  # even though it was the same data, just truncated by the sender before sending.
                                  # Known trade-off: canvas data URLs share a generic header
                                  # ("data:image/png;base64,") across ALL canvas output, not just fingerprinting
                                  # calls — a 24-character prefix mostly overlaps this generic header, so a
                                  # "strong" match here is still correlational, not proof the SAME derived value
                                  # was sent, for canvas specifically. Manual verification remains warranted.


def _occurred_before_consent(event_timestamp: float, consent_click_timestamp: float | None) -> bool:
    if consent_click_timestamp is None:
        return True  # consent never happened — nothing was ever gated
    return event_timestamp < consent_click_timestamp


def check_sb01(scan_result: dict) -> list[dict]:
    """Scripts (tracker vendors) executing before consent. One result per detected tracker."""
    detected = detect_trackers(scan_result)
    consent_click_ts = scan_result.get("consent_capture", {}).get("consent_click_timestamp")

    results = []
    for tracker in detected:
        before = _occurred_before_consent(tracker["first_seen_timestamp"], consent_click_ts)
        label = "Non-Compliant" if before else "Compliant"
        results.append({
            "rule_id": "SB-01", "category": "script_behaviour", "label": label,
            "evidence": {"vendor": tracker["vendor"], "first_seen_timestamp": tracker["first_seen_timestamp"],
                         "consent_click_timestamp": consent_click_ts},
            "notes": f"{tracker['vendor']} script first observed "
                     f"{'before' if before else 'after'} the Accept click.",
        })
    return results


def check_sb02(scan_result: dict) -> dict:
    """Scripts creating cookies before consent. Single result (site-level), proxy via cookie timing — see module docstring."""
    capture = scan_result.get("consent_capture", {})

    if not capture.get("banner_detected"):
        return {"rule_id": "SB-02", "category": "script_behaviour", "label": "Not Applicable",
                "evidence": {}, "notes": "No banner detected — evaluated separately under CN-01."}

    non_essential_before = _non_essential_cookies_before_consent(capture, scan_result)

    if non_essential_before:
        return {"rule_id": "SB-02", "category": "script_behaviour", "label": "Non-Compliant",
                "evidence": {"non_essential_cookies_before_consent": non_essential_before,
                             "note": "Script-to-cookie attribution not implemented — timing proxy only."},
                "notes": "Non-essential cookie(s) present before consent (causal script not individually identified)."}

    return {"rule_id": "SB-02", "category": "script_behaviour", "label": "Compliant", "evidence": {}, "notes": None}


def check_sb03(scan_result: dict) -> list[dict]:
    """Third-party server communication before consent. One result per detected tracker."""
    detected = detect_trackers(scan_result)
    consent_click_ts = scan_result.get("consent_capture", {}).get("consent_click_timestamp")

    results = []
    for tracker in detected:
        before = _occurred_before_consent(tracker["first_seen_timestamp"], consent_click_ts)
        label = "Non-Compliant" if before else "Compliant"
        results.append({
            "rule_id": "SB-03", "category": "script_behaviour", "label": label,
            "evidence": {"vendor": tracker["vendor"], "matched_url": tracker["matched_url"],
                         "first_seen_timestamp": tracker["first_seen_timestamp"],
                         "consent_click_timestamp": consent_click_ts},
            "notes": f"Request to {tracker['vendor']} occurred "
                     f"{'before' if before else 'after'} the Accept click.",
        })
    return results


def _find_transmission(call_ts: float, value_excerpt: str | None, network_log: list[dict],
                        tracker_requests: list[dict]) -> tuple[str | None, str | None]:
    """
    Look for evidence a fingerprinting call's result left the browser,
    within TRANSMISSION_WINDOW_SECONDS after the call:
      - "strong": the captured value excerpt appears in a later request's
        URL or POST body — real evidence, only possible when a value was
        captured (canvas.toDataURL/toBlob; other APIs carry no excerpt).
      - "weak": no value match, but a request to a KNOWN tracker domain
        (same fixed list as TR-01) occurred in the window — correlation,
        not proof. Flagged as needing manual verification wherever used.
      - None: nothing observed following the call.
    """
    if value_excerpt:
        needle = value_excerpt.lower()[:VALUE_MATCH_PREFIX_LENGTH]
        for req in network_log:
            if req["timestamp"] < call_ts or req["timestamp"] - call_ts > TRANSMISSION_WINDOW_SECONDS:
                continue
            raw_haystack = req.get("url", "") + " " + (req.get("post_data") or "")
            # Real trackers routinely percent-encode values before sending
            # (e.g. encodeURIComponent in a query string) — a canvas data
            # URL is full of characters (: ; , + /) that get encoded, so
            # comparing only against the raw haystack would miss the exact
            # same data the moment it's URL-encoded, which is the NORMAL
            # case for query-string transmission, not an edge case.
            decoded_haystack = unquote(raw_haystack)
            haystack = (raw_haystack + " " + decoded_haystack).lower()
            if needle in haystack:
                return "strong", req["url"]

    for tr in tracker_requests:
        if tr["timestamp"] < call_ts or tr["timestamp"] - call_ts > TRANSMISSION_WINDOW_SECONDS:
            continue
        return "weak", tr["url"]

    return None, None


def check_sb04(scan_result: dict) -> list[dict]:
    """
    Fingerprinting-style behaviour.

    INTERPRETIVE EXTENSION beyond the Rulebook's literal text — flag this
    explicitly in the methodology chapter, same as CN-04/CN-05's own
    already-documented extensions. The Rulebook requires proving the
    SPECIFIC derived value was transmitted; reliably proving that in
    general isn't achievable with browser-level instrumentation alone
    (values are routinely hashed or minified before sending), which is a
    recognised limitation in fingerprinting-detection research generally,
    not something specific to this tool. This function uses the strongest
    achievable proxy instead — see _find_transmission() for the two
    confidence tiers. Every "weak"-confidence Non-Compliant result should
    be manually verified before being reported as a dataset finding.
    """
    fingerprint_log = scan_result.get("fingerprint_log", [])

    if not fingerprint_log:
        return [{
            "rule_id": "SB-04", "category": "script_behaviour", "label": "Not Applicable",
            "evidence": {}, "notes": "None of the six fixed fingerprinting-indicative APIs were called.",
        }]

    network_log = scan_result.get("network_log", [])
    tracker_requests = all_tracker_requests(scan_result)

    results = []
    measure_text_calls = [e for e in fingerprint_log if e["api"] == "measureText"]
    other_calls = [e for e in fingerprint_log if e["api"] != "measureText"]

    for call in other_calls:
        confidence, matched_url = _find_transmission(call["timestamp"], call.get("value_excerpt"),
                                                       network_log, tracker_requests)
        if confidence:
            results.append({
                "rule_id": "SB-04", "category": "script_behaviour", "label": "Non-Compliant",
                "evidence": {"api": call["api"], "call_timestamp": call["timestamp"],
                             "matched_request": matched_url, "confidence": confidence},
                "notes": (f"{call['api']} called, followed by "
                          f"{'a value-matched' if confidence == 'strong' else 'a correlated tracker'} "
                          f"request within {TRANSMISSION_WINDOW_SECONDS}s."
                          + ("" if confidence == "strong" else " Manual verification recommended — timing correlation only.")),
            })
        else:
            results.append({
                "rule_id": "SB-04", "category": "script_behaviour", "label": "Not Applicable",
                "evidence": {"api": call["api"], "call_timestamp": call["timestamp"]},
                "notes": f"{call['api']} called; no correlated outbound transmission observed.",
            })

    if len(measure_text_calls) >= MEASURE_TEXT_REPEAT_THRESHOLD:
        last_call = measure_text_calls[-1]
        confidence, matched_url = _find_transmission(last_call["timestamp"], None, network_log, tracker_requests)
        if confidence:
            results.append({
                "rule_id": "SB-04", "category": "script_behaviour", "label": "Non-Compliant",
                "evidence": {"api": "measureText", "call_count": len(measure_text_calls),
                             "matched_request": matched_url, "confidence": confidence},
                "notes": f"measureText called {len(measure_text_calls)} times (font-fingerprinting pattern), "
                         f"followed by a correlated tracker request. Manual verification recommended.",
            })
        else:
            results.append({
                "rule_id": "SB-04", "category": "script_behaviour", "label": "Not Applicable",
                "evidence": {"api": "measureText", "call_count": len(measure_text_calls)},
                "notes": f"measureText called {len(measure_text_calls)} times; no correlated transmission observed.",
            })
    elif measure_text_calls:
        results.append({
            "rule_id": "SB-04", "category": "script_behaviour", "label": "Not Applicable",
            "evidence": {"api": "measureText", "call_count": len(measure_text_calls)},
            "notes": f"measureText called {len(measure_text_calls)} time(s) — below the "
                     f"{MEASURE_TEXT_REPEAT_THRESHOLD}-call repetition threshold used to treat it as "
                     f"font-fingerprinting-indicative (Rulebook: 'repeated measureText() calls').",
        })

    return results


def evaluate(scan_result: dict) -> list[dict]:
    """Run SB-01 through SB-04 against one site."""
    results = []
    results.extend(check_sb01(scan_result))
    results.append(check_sb02(scan_result))
    results.extend(check_sb03(scan_result))
    results.extend(check_sb04(scan_result))
    return results