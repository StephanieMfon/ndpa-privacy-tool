"""
tests/test_consent.py — CN-01 to CN-07.

Traceability: CN-01 -> check_cn01(), CN-02 -> check_cn02(), etc.
Run: pytest tests/test_consent.py -v

Note: these test the pure rule logic against synthetic capture dicts, NOT
the live consent_capture.py browser interaction (untestable in this
environment — needs real-site verification, see consent_capture.py notes).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scanner.rules import consent as cn


def base_capture(**overrides):
    capture = {
        "banner_detected": True,
        "banner_position": {"top": 100, "viewport_height": 768, "top_ratio": 100 / 768},
        "accept_button": {"found": True, "text": "accept all", "is_filled": True, "background_color": "rgb(0,0,0)"},
        "reject_button": {"found": True, "text": "reject all", "is_filled": True, "background_color": "rgb(255,255,255)"},
        "granular_toggles_found": [],
        "cookies_before_consent": ["OptanonAlertBoxClosed"],
        "consent_click_timestamp": 1.2,
        "cookies_after_accept": ["OptanonAlertBoxClosed", "_ga"],
        "consent_persisted_after_reload": True,
        "consent_state_storage_found": True,
        "withdrawal_mechanism_found": True,
        "withdrawal_mechanism_text": "cookie settings",
    }
    capture.update(overrides)
    return capture


def base_scan_result(cookies=None):
    return {
        "url": "https://example.com.ng",
        "cookies": cookies or [
            {"name": "OptanonAlertBoxClosed", "domain": "example.com.ng"},
            {"name": "_ga", "domain": "example.com.ng"},
        ],
    }


# --- CN-01: banner position ---

def test_cn01_no_banner_non_compliant():
    c = base_capture(banner_detected=False, banner_position=None)
    assert cn.check_cn01(c)["label"] == "Non-Compliant"


def test_cn01_banner_top_zone_compliant():
    c = base_capture(banner_position={"top": 100, "viewport_height": 768, "top_ratio": 100 / 768})
    assert cn.check_cn01(c)["label"] == "Compliant"


def test_cn01_banner_bottom_zone_non_compliant():
    c = base_capture(banner_position={"top": 700, "viewport_height": 768, "top_ratio": 700 / 768})
    assert cn.check_cn01(c)["label"] == "Non-Compliant"


def test_cn01_exactly_at_threshold_non_compliant():
    """Fixed Decisions #4: top edge in bottom 25% -> non-compliant. Boundary case."""
    c = base_capture(banner_position={"top": 576, "viewport_height": 768, "top_ratio": 576 / 768})  # exactly 0.75
    assert cn.check_cn01(c)["label"] == "Non-Compliant"


# --- CN-02: consent before non-essential cookies ---

def test_cn02_no_non_essential_before_compliant():
    c = base_capture(cookies_before_consent=["OptanonAlertBoxClosed"])
    sr = base_scan_result()
    assert cn.check_cn02(c, sr)["label"] == "Compliant"


def test_cn02_non_essential_before_non_compliant():
    c = base_capture(cookies_before_consent=["OptanonAlertBoxClosed", "_ga"])
    sr = base_scan_result()
    r = cn.check_cn02(c, sr)
    assert r["label"] == "Non-Compliant"
    assert "_ga" in r["evidence"]["non_essential_cookies_before_consent"]


def test_cn02_no_banner_not_applicable():
    c = base_capture(banner_detected=False)
    sr = base_scan_result()
    assert cn.check_cn02(c, sr)["label"] == "Not Applicable"


# --- CN-03: reject option ---

def test_cn03_reject_found_compliant():
    c = base_capture(reject_button={"found": True, "text": "reject"})
    assert cn.check_cn03(c)["label"] == "Compliant"


def test_cn03_reject_missing_non_compliant():
    c = base_capture(reject_button={"found": False})
    assert cn.check_cn03(c)["label"] == "Non-Compliant"


# --- CN-04: reject as easy as accept ---

def test_cn04_both_filled_compliant():
    c = base_capture(
        accept_button={"found": True, "text": "accept", "is_filled": True},
        reject_button={"found": True, "text": "reject", "is_filled": True},
    )
    assert cn.check_cn04(c)["label"] == "Compliant"


def test_cn04_accept_filled_reject_text_non_compliant():
    c = base_capture(
        accept_button={"found": True, "text": "accept", "is_filled": True},
        reject_button={"found": True, "text": "reject", "is_filled": False},
    )
    assert cn.check_cn04(c)["label"] == "Non-Compliant"


def test_cn04_no_reject_not_applicable():
    c = base_capture(reject_button={"found": False})
    assert cn.check_cn04(c)["label"] == "Not Applicable"


# --- CN-05: granular consent ---

def test_cn05_two_categories_compliant():
    c = base_capture(granular_toggles_found=["analytics", "advertising"])
    assert cn.check_cn05(c)["label"] == "Compliant"


def test_cn05_one_category_not_applicable():
    c = base_capture(granular_toggles_found=["analytics"])
    assert cn.check_cn05(c)["label"] == "Not Applicable"


def test_cn05_zero_categories_non_compliant():
    c = base_capture(granular_toggles_found=[])
    assert cn.check_cn05(c)["label"] == "Non-Compliant"


# --- CN-06: consent recorded ---

def test_cn06_storage_found_compliant():
    c = base_capture(consent_state_storage_found=True, consent_persisted_after_reload=False)
    assert cn.check_cn06(c)["label"] == "Compliant"


def test_cn06_neither_non_compliant():
    c = base_capture(consent_state_storage_found=False, consent_persisted_after_reload=False)
    assert cn.check_cn06(c)["label"] == "Non-Compliant"


# --- CN-07: withdrawal ---

def test_cn07_mechanism_found_compliant():
    c = base_capture(withdrawal_mechanism_found=True)
    assert cn.check_cn07(c)["label"] == "Compliant"


def test_cn07_no_mechanism_non_compliant():
    c = base_capture(withdrawal_mechanism_found=False)
    assert cn.check_cn07(c)["label"] == "Non-Compliant"


# --- evaluate() end-to-end ---

def test_evaluate_returns_seven_results():
    results = cn.evaluate(base_capture(), base_scan_result())
    assert len(results) == 7
    assert {r["rule_id"] for r in results} == {"CN-01", "CN-02", "CN-03", "CN-04", "CN-05", "CN-06", "CN-07"}