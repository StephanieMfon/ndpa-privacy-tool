"""
tests/test_trackers.py — TR-01 and TR-02.

Traceability: TR-01 -> check_tr01() / detect_trackers(), TR-02 -> check_tr02().
Run: pytest tests/test_trackers.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scanner.rules import trackers as tr


def make_scan_result(urls_with_timestamps):
    return {
        "url": "https://example.com.ng",
        "network_log": [
            {"url": u, "timestamp": t, "resource_type": "script", "method": "GET"}
            for (u, t) in urls_with_timestamps
        ],
    }


# --- detect_trackers ---

def test_detect_google_analytics():
    sr = make_scan_result([("https://www.google-analytics.com/g/collect", 1.2)])
    detected = tr.detect_trackers(sr)
    assert len(detected) == 1
    assert detected[0]["vendor"] == "Google Analytics"


def test_detect_multiple_vendors():
    sr = make_scan_result([
        ("https://www.googletagmanager.com/gtm.js", 0.5),
        ("https://connect.facebook.net/en_US/fbevents.js", 0.8),
        ("https://static.hotjar.com/c/hotjar-123.js", 1.1),
    ])
    detected = tr.detect_trackers(sr)
    vendors = {d["vendor"] for d in detected}
    assert vendors == {"Google Tag Manager", "Meta Pixel", "Hotjar"}


def test_detect_none_present():
    sr = make_scan_result([("https://example.com.ng/style.css", 0.1)])
    assert tr.detect_trackers(sr) == []


def test_detect_dedupes_and_keeps_earliest_timestamp():
    sr = make_scan_result([
        ("https://www.google-analytics.com/g/collect?e=1", 3.0),
        ("https://www.google-analytics.com/g/collect?e=2", 1.0),
        ("https://www.google-analytics.com/g/collect?e=3", 5.0),
    ])
    detected = tr.detect_trackers(sr)
    assert len(detected) == 1
    assert detected[0]["first_seen_timestamp"] == 1.0
    assert detected[0]["request_count"] == 3


def test_detect_unlisted_tracker_not_found():
    """Stated tool-coverage limitation: only fixed 10 vendors are checked."""
    sr = make_scan_result([("https://stats.g.doubleclick.net/hit", 1.0)])
    # doubleclick.net IS in the list, so this one should actually be found —
    # testing a genuinely unlisted vendor instead:
    sr2 = make_scan_result([("https://track.someobscuretracker.io/pixel", 1.0)])
    assert len(tr.detect_trackers(sr2)) == 0


# --- TR-01 ---

def test_tr01_always_not_applicable():
    r = tr.check_tr01([{"vendor": "Google Analytics", "matched_url": "x", "first_seen_timestamp": 1.0, "request_count": 1}])
    assert r["label"] == "Not Applicable"
    assert r["rule_id"] == "TR-01"
    assert len(r["evidence"]["detected_trackers"]) == 1


# --- TR-02 ---

def test_tr02_no_policy_flags_pending_unable_to_determine():
    t = {"vendor": "Google Analytics", "matched_url": "x", "first_seen_timestamp": 1.0, "request_count": 1}
    r = tr.check_tr02(t, policy_text=None)
    assert r["label"] == "Unable to Determine"
    assert r["evidence"]["pending_policy_crossref"] is True


def test_tr02_disclosed_compliant():
    t = {"vendor": "Google Analytics", "matched_url": "x", "first_seen_timestamp": 1.0, "request_count": 1}
    policy = "We use Google Analytics to understand how visitors use our site."
    r = tr.check_tr02(t, policy_text=policy)
    assert r["label"] == "Compliant"


def test_tr02_not_disclosed_non_compliant():
    t = {"vendor": "Mixpanel", "matched_url": "x", "first_seen_timestamp": 1.0, "request_count": 1}
    policy = "We use cookies for essential site functions."
    r = tr.check_tr02(t, policy_text=policy)
    assert r["label"] == "Non-Compliant"


# --- evaluate() end-to-end ---

def test_evaluate_returns_tr01_plus_one_tr02_per_tracker():
    sr = make_scan_result([
        ("https://www.google-analytics.com/g/collect", 1.0),
        ("https://static.hotjar.com/c/hotjar-1.js", 2.0),
    ])
    results = tr.evaluate(sr)
    assert len(results) == 3  # 1 TR-01 + 2 TR-02
    assert results[0]["rule_id"] == "TR-01"
    assert {r["rule_id"] for r in results[1:]} == {"TR-02"}


def test_evaluate_no_trackers_returns_only_tr01():
    sr = make_scan_result([("https://example.com.ng/style.css", 0.1)])
    results = tr.evaluate(sr)
    assert len(results) == 1
    assert results[0]["rule_id"] == "TR-01"