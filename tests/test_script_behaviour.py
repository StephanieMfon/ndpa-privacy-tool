"""
tests/test_script_behaviour.py — SB-01 to SB-03.

Traceability: SB-01 -> check_sb01(), SB-02 -> check_sb02(), SB-03 -> check_sb03().
Run: pytest tests/test_script_behaviour.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scanner.rules import script_behaviour as sb


def make_scan_result(network_log=None, cookies=None, consent_capture=None):
    return {
        "url": "https://example.com.ng",
        "network_log": network_log or [],
        "cookies": cookies or [],
        "consent_capture": consent_capture or {
            "banner_detected": True,
            "cookies_before_consent": [],
            "consent_click_timestamp": 5.0,
        },
    }


# --- SB-01 ---

def test_sb01_tracker_before_consent_non_compliant():
    sr = make_scan_result(
        network_log=[{"url": "https://www.google-analytics.com/g/collect", "timestamp": 1.0,
                       "resource_type": "script", "method": "GET"}],
        consent_capture={"banner_detected": True, "cookies_before_consent": [], "consent_click_timestamp": 5.0},
    )
    results = sb.check_sb01(sr)
    assert len(results) == 1
    assert results[0]["label"] == "Non-Compliant"


def test_sb01_tracker_after_consent_compliant():
    sr = make_scan_result(
        network_log=[{"url": "https://www.google-analytics.com/g/collect", "timestamp": 8.0,
                       "resource_type": "script", "method": "GET"}],
        consent_capture={"banner_detected": True, "cookies_before_consent": [], "consent_click_timestamp": 5.0},
    )
    results = sb.check_sb01(sr)
    assert results[0]["label"] == "Compliant"


def test_sb01_no_consent_click_all_non_compliant():
    """No banner/no click recorded — consent was never obtainable, so every tracker is 'before consent'."""
    sr = make_scan_result(
        network_log=[{"url": "https://static.hotjar.com/c/hotjar-1.js", "timestamp": 2.0,
                       "resource_type": "script", "method": "GET"}],
        consent_capture={"banner_detected": False, "cookies_before_consent": [], "consent_click_timestamp": None},
    )
    results = sb.check_sb01(sr)
    assert results[0]["label"] == "Non-Compliant"


def test_sb01_no_trackers_empty_results():
    sr = make_scan_result(network_log=[])
    assert sb.check_sb01(sr) == []


# --- SB-02 ---

def test_sb02_no_banner_not_applicable():
    sr = make_scan_result(consent_capture={"banner_detected": False, "cookies_before_consent": [], "consent_click_timestamp": None})
    assert sb.check_sb02(sr)["label"] == "Not Applicable"


def test_sb02_non_essential_cookie_before_non_compliant():
    sr = make_scan_result(
        cookies=[{"name": "_ga", "domain": "example.com.ng"}],
        consent_capture={"banner_detected": True, "cookies_before_consent": ["_ga"], "consent_click_timestamp": 5.0},
    )
    r = sb.check_sb02(sr)
    assert r["label"] == "Non-Compliant"
    assert "_ga" in r["evidence"]["non_essential_cookies_before_consent"]


def test_sb02_only_essential_cookies_compliant():
    sr = make_scan_result(
        cookies=[{"name": "OptanonAlertBoxClosed", "domain": "example.com.ng"}],
        consent_capture={"banner_detected": True, "cookies_before_consent": ["OptanonAlertBoxClosed"], "consent_click_timestamp": 5.0},
    )
    assert sb.check_sb02(sr)["label"] == "Compliant"


def test_sb02_matches_cn02_result():
    """SB-02 and CN-02 share the same underlying evidence — confirm they agree."""
    from scanner.rules.consent import check_cn02

    sr = make_scan_result(
        cookies=[{"name": "_ga", "domain": "example.com.ng"}],
        consent_capture={"banner_detected": True, "cookies_before_consent": ["_ga"], "consent_click_timestamp": 5.0},
    )
    sb_result = sb.check_sb02(sr)
    cn_result = check_cn02(sr["consent_capture"], sr)
    assert sb_result["label"] == cn_result["label"]


# --- SB-03 ---

def test_sb03_third_party_before_consent_non_compliant():
    sr = make_scan_result(
        network_log=[{"url": "https://connect.facebook.net/fbevents.js", "timestamp": 1.5,
                       "resource_type": "script", "method": "GET"}],
        consent_capture={"banner_detected": True, "cookies_before_consent": [], "consent_click_timestamp": 5.0},
    )
    results = sb.check_sb03(sr)
    assert results[0]["label"] == "Non-Compliant"
    assert results[0]["evidence"]["vendor"] == "Meta Pixel"


def test_sb03_after_consent_compliant():
    sr = make_scan_result(
        network_log=[{"url": "https://connect.facebook.net/fbevents.js", "timestamp": 9.0,
                       "resource_type": "script", "method": "GET"}],
        consent_capture={"banner_detected": True, "cookies_before_consent": [], "consent_click_timestamp": 5.0},
    )
    assert sb.check_sb03(sr)[0]["label"] == "Compliant"


# --- SB-04 ---

def test_sb04_no_calls_not_applicable():
    sr = make_scan_result()
    sr["fingerprint_log"] = []
    results = sb.check_sb04(sr)
    assert len(results) == 1
    assert results[0]["label"] == "Not Applicable"


def test_sb04_call_no_transmission_not_applicable():
    sr = make_scan_result(network_log=[])
    sr["fingerprint_log"] = [{"api": "WebGLRenderingContext.getParameter", "timestamp": 1.0, "value_excerpt": "Intel Inc."}]
    results = sb.check_sb04(sr)
    assert len(results) == 1
    assert results[0]["label"] == "Not Applicable"


def test_sb04_call_with_value_match_strong_non_compliant():
    """Strong signal: the captured canvas value itself appears in a later request."""
    sr = make_scan_result(network_log=[
        {"url": "https://track.example.com/beacon?d=abcd1234xyz", "timestamp": 2.0,
         "resource_type": "xhr", "method": "GET", "post_data": None},
    ])
    sr["fingerprint_log"] = [{"api": "canvas.toDataURL", "timestamp": 1.0, "value_excerpt": "abcd1234xyz"}]
    results = sb.check_sb04(sr)
    assert results[0]["label"] == "Non-Compliant"
    assert results[0]["evidence"]["confidence"] == "strong"


def test_sb04_call_with_url_encoded_value_still_matches_strong():
    """
    Regression test: real trackers URL-encode values before sending them
    (e.g. encodeURIComponent in a query string). A raw substring comparison
    would miss this — the value must be found even when the transmission
    percent-encodes special characters. Caught via a real browser test
    against a canvas data URL, which is full of characters (: ; , +) that
    get encoded.
    """
    raw_value = "data:image/png;base64,iVBORw0KGgo"
    encoded_value = "data%3Aimage%2Fpng%3Bbase64%2CiVBORw0KGgo"
    sr = make_scan_result(network_log=[
        {"url": f"https://track.example.com/beacon?v={encoded_value}", "timestamp": 1.5,
         "resource_type": "xhr", "method": "GET", "post_data": None},
    ])
    sr["fingerprint_log"] = [{"api": "canvas.toDataURL", "timestamp": 1.0, "value_excerpt": raw_value}]
    results = sb.check_sb04(sr)
    assert results[0]["label"] == "Non-Compliant"
    assert results[0]["evidence"]["confidence"] == "strong"


def test_sb04_transmitted_value_shorter_than_captured_excerpt_still_matches():
    """
    Regression test for a SECOND real bug found via a live browser test:
    the captured value_excerpt (64 chars) was longer than what the site
    actually transmitted (a 40-char truncated slice of the same string).
    A full-string match structurally can't succeed when the needle is
    longer than anything the haystack could ever contain — matching must
    use a bounded prefix, not the entire captured excerpt.
    """
    full_value = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAADIAAAAyCAYAAAA"  # 64 chars, as actually captured
    truncated_transmitted = full_value[:40]  # what the site actually sent — shorter than the captured excerpt
    sr = make_scan_result(network_log=[
        {"url": f"https://track.example.com/beacon?v={truncated_transmitted}", "timestamp": 1.5,
         "resource_type": "xhr", "method": "GET", "post_data": None},
    ])
    sr["fingerprint_log"] = [{"api": "canvas.toDataURL", "timestamp": 1.0, "value_excerpt": full_value}]
    results = sb.check_sb04(sr)
    assert results[0]["label"] == "Non-Compliant"
    assert results[0]["evidence"]["confidence"] == "strong"


def test_sb04_call_with_tracker_correlation_weak_non_compliant():
    """Weak signal: no value match, but a known-tracker request follows within the window."""
    sr = make_scan_result(network_log=[
        {"url": "https://www.google-analytics.com/g/collect", "timestamp": 2.0,
         "resource_type": "xhr", "method": "GET", "post_data": None},
    ])
    sr["fingerprint_log"] = [{"api": "AudioContext", "timestamp": 1.0, "value_excerpt": None}]
    results = sb.check_sb04(sr)
    assert results[0]["label"] == "Non-Compliant"
    assert results[0]["evidence"]["confidence"] == "weak"
    assert "manual verification" in results[0]["notes"].lower()


def test_sb04_correlation_outside_window_not_flagged():
    sr = make_scan_result(network_log=[
        {"url": "https://www.google-analytics.com/g/collect", "timestamp": 10.0,  # 9s after the call, outside 3s window
         "resource_type": "xhr", "method": "GET", "post_data": None},
    ])
    sr["fingerprint_log"] = [{"api": "AudioContext", "timestamp": 1.0, "value_excerpt": None}]
    results = sb.check_sb04(sr)
    assert results[0]["label"] == "Not Applicable"


def test_sb04_measuretext_below_threshold_not_applicable():
    sr = make_scan_result(network_log=[])
    sr["fingerprint_log"] = [
        {"api": "measureText", "timestamp": 1.0, "value_excerpt": "abc"},
        {"api": "measureText", "timestamp": 1.1, "value_excerpt": "def"},
    ]
    results = sb.check_sb04(sr)
    assert len(results) == 1
    assert results[0]["label"] == "Not Applicable"
    assert "below the" in results[0]["notes"]


def test_sb04_measuretext_repeated_with_correlation_non_compliant():
    sr = make_scan_result(network_log=[
        {"url": "https://static.hotjar.com/c/hotjar-1.js", "timestamp": 2.5,
         "resource_type": "xhr", "method": "GET", "post_data": None},
    ])
    sr["fingerprint_log"] = [
        {"api": "measureText", "timestamp": 1.0, "value_excerpt": "abc"},
        {"api": "measureText", "timestamp": 1.1, "value_excerpt": "def"},
        {"api": "measureText", "timestamp": 1.2, "value_excerpt": "ghi"},
    ]
    results = sb.check_sb04(sr)
    assert results[0]["label"] == "Non-Compliant"
    assert results[0]["evidence"]["call_count"] == 3


def test_sb04_multiple_apis_each_scored_independently():
    sr = make_scan_result(network_log=[])
    sr["fingerprint_log"] = [
        {"api": "canvas.toDataURL", "timestamp": 1.0, "value_excerpt": "xyz"},
        {"api": "navigator.plugins", "timestamp": 2.0, "value_excerpt": None},
    ]
    results = sb.check_sb04(sr)
    assert len(results) == 2  # both Not Applicable (no transmission), but scored separately
    apis = {r["evidence"]["api"] for r in results}
    assert apis == {"canvas.toDataURL", "navigator.plugins"}


# --- evaluate() end-to-end ---

def test_evaluate_combines_all_four_rules():
    sr = make_scan_result(
        network_log=[{"url": "https://www.google-analytics.com/g/collect", "timestamp": 1.0,
                       "resource_type": "script", "method": "GET", "post_data": None}],
        cookies=[{"name": "_ga", "domain": "example.com.ng"}],
        consent_capture={"banner_detected": True, "cookies_before_consent": ["_ga"], "consent_click_timestamp": 5.0},
    )
    sr["fingerprint_log"] = []
    results = sb.evaluate(sr)
    rule_ids = [r["rule_id"] for r in results]
    assert rule_ids.count("SB-01") == 1
    assert rule_ids.count("SB-02") == 1
    assert rule_ids.count("SB-03") == 1
    assert rule_ids.count("SB-04") == 1