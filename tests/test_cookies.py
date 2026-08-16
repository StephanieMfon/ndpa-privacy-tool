"""
tests/test_cookies.py — CK-01 to CK-05.

Traceability: CK-01 -> check_ck01(), CK-02 -> check_ck02(), etc.
Run: pytest tests/test_cookies.py -v
"""

import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scanner.rules import cookies as ck

NOW = datetime(2026, 8, 16, tzinfo=timezone.utc)
NOW_EPOCH = NOW.timestamp()
SCAN_RESULT_TIMESTAMP = NOW.isoformat()

CONFIG = ck._load_essential_config()


def make_cookie(name="tracker_id", domain="example.com", secure=True, httpOnly=True,
                 sameSite="Lax", expires=-1):
    return {
        "name": name, "domain": domain, "path": "/",
        "secure": secure, "httpOnly": httpOnly, "sameSite": sameSite, "expires": expires,
    }


# --- CK-01: Secure ---

def test_ck01_compliant_when_secure():
    c = make_cookie(secure=True)
    r = ck.check_ck01(c, CONFIG)
    assert r["label"] == "Compliant"


def test_ck01_non_compliant_when_not_secure():
    c = make_cookie(secure=False)
    r = ck.check_ck01(c, CONFIG)
    assert r["label"] == "Non-Compliant"


def test_ck01_not_applicable_for_cmp_cookie():
    c = make_cookie(name="OptanonConsent", secure=False)
    r = ck.check_ck01(c, CONFIG)
    assert r["label"] == "Not Applicable"


def test_ck01_session_cookie_still_scored():
    """Interpretive choice: PHPSESSID etc. are NOT exempt from CK-01, unlike CN-02."""
    c = make_cookie(name="PHPSESSID", secure=False)
    r = ck.check_ck01(c, CONFIG)
    assert r["label"] == "Non-Compliant"


# --- CK-02: HttpOnly ---

def test_ck02_compliant_when_httponly():
    c = make_cookie(httpOnly=True)
    assert ck.check_ck02(c, CONFIG)["label"] == "Compliant"


def test_ck02_non_compliant_when_not_httponly():
    c = make_cookie(httpOnly=False)
    assert ck.check_ck02(c, CONFIG)["label"] == "Non-Compliant"


def test_ck02_not_applicable_for_cmp_cookie():
    c = make_cookie(name="euconsent-v2", httpOnly=False)
    assert ck.check_ck02(c, CONFIG)["label"] == "Not Applicable"


def test_ck02_iabtcf_prefix_matches():
    c = make_cookie(name="IABTCF_gdprApplies", httpOnly=False)
    assert ck.check_ck02(c, CONFIG)["label"] == "Not Applicable"


# --- CK-03: SameSite ---

def test_ck03_none_without_secure_is_non_compliant():
    c = make_cookie(sameSite="None", secure=False)
    r = ck.check_ck03(c, "third-party")
    assert r["label"] == "Non-Compliant"


def test_ck03_none_with_secure_is_compliant():
    c = make_cookie(sameSite="None", secure=True)
    r = ck.check_ck03(c, "third-party")
    assert r["label"] == "Compliant"


def test_ck03_absent_on_third_party_is_non_compliant():
    c = make_cookie(sameSite="", secure=True)
    r = ck.check_ck03(c, "third-party")
    assert r["label"] == "Non-Compliant"


def test_ck03_absent_on_first_party_is_compliant():
    c = make_cookie(sameSite="", secure=True)
    r = ck.check_ck03(c, "first-party")
    assert r["label"] == "Compliant"


def test_ck03_lax_is_compliant():
    c = make_cookie(sameSite="Lax")
    assert ck.check_ck03(c, "first-party")["label"] == "Compliant"


# --- CK-04: Expiry proportionality ---

def test_ck04_session_cookie_not_applicable():
    c = make_cookie(expires=-1)
    r = ck.check_ck04(c, NOW_EPOCH, policy_text=None)
    assert r["label"] == "Not Applicable"


def test_ck04_within_threshold_compliant():
    expires = NOW_EPOCH + (60 * 24 * 60 * 60)  # 60 days out
    c = make_cookie(expires=expires)
    r = ck.check_ck04(c, NOW_EPOCH, policy_text=None)
    assert r["label"] == "Compliant"


def test_ck04_exceeds_threshold_no_policy_flags_pending():
    expires = NOW_EPOCH + (400 * 24 * 60 * 60)  # ~13 months out
    c = make_cookie(expires=expires)
    r = ck.check_ck04(c, NOW_EPOCH, policy_text=None)
    assert r["label"] == "Non-Compliant"
    assert r["evidence"]["pending_policy_crossref"] is True


def test_ck04_exceeds_threshold_with_justification_compliant():
    expires = NOW_EPOCH + (400 * 24 * 60 * 60)
    c = make_cookie(name="loyalty_pref", expires=expires)
    policy_text = "We retain the loyalty_pref cookie for 14 months to remember your preferences."
    r = ck.check_ck04(c, NOW_EPOCH, policy_text=policy_text)
    assert r["label"] == "Compliant"


# --- CK-05: Third-party disclosure ---

def test_ck05_first_party_not_applicable():
    c = make_cookie(domain="example.com")
    r = ck.check_ck05(c, "first-party", policy_text=None)
    assert r["label"] == "Not Applicable"


def test_ck05_third_party_no_policy_flags_pending():
    c = make_cookie(domain="analytics.google.com")
    r = ck.check_ck05(c, "third-party", policy_text=None)
    assert r["label"] == "Non-Compliant"
    assert r["evidence"]["pending_policy_crossref"] is True


def test_ck05_third_party_disclosed_compliant():
    c = make_cookie(domain="analytics.google.com")
    policy_text = "We use Google Analytics (analytics.google.com) to understand site usage."
    r = ck.check_ck05(c, "third-party", policy_text=policy_text)
    assert r["label"] == "Compliant"


# --- classify_party / classify_persistence ---

def test_classify_party_first_party():
    c = make_cookie(domain="kara.com.ng")
    assert ck.classify_party(c, "https://kara.com.ng") == "first-party"


def test_classify_party_third_party():
    c = make_cookie(domain="doubleclick.net")
    assert ck.classify_party(c, "https://kara.com.ng") == "third-party"


def test_classify_persistence_session():
    assert ck.classify_persistence(make_cookie(expires=-1)) == "session"


def test_classify_persistence_persistent():
    assert ck.classify_persistence(make_cookie(expires=NOW_EPOCH + 1000)) == "persistent"


# --- evaluate() end-to-end ---

def test_evaluate_produces_five_results_per_cookie():
    scan_result = {
        "url": "https://kara.com.ng",
        "scanned_at": SCAN_RESULT_TIMESTAMP,
        "cookies": [make_cookie(name="OptanonConsent"), make_cookie(name="_ga", domain="analytics.google.com")],
    }
    results = ck.evaluate(scan_result)
    assert len(results) == 10  # 2 cookies x 5 rules
    assert all(r["category"] == "cookies" for r in results)