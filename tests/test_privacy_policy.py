"""
tests/test_privacy_policy.py — PP-01 to PP-06.

Traceability: PP-01 -> check_pp01(), PP-02 -> check_pp02(), etc.
Run: pytest tests/test_privacy_policy.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scanner.rules import privacy_policy as pp


def make_scan_result(policy_capture):
    return {"url": "https://example.com.ng", "policy_capture": policy_capture}


# --- PP-01 ---

def test_pp01_reachable_compliant():
    r = pp.check_pp01({"privacy_policy_reachable": True, "privacy_policy_url": "https://example.com.ng/privacy"})
    assert r["label"] == "Compliant"


def test_pp01_not_reachable_non_compliant():
    r = pp.check_pp01({"privacy_policy_reachable": False, "privacy_policy_url": None})
    assert r["label"] == "Non-Compliant"


# --- PP-02 ---

def test_pp02_standalone_compliant():
    r = pp.check_pp02({"cookie_policy_reachable": True, "cookie_policy_url": "https://example.com.ng/cookies"})
    assert r["label"] == "Compliant"
    assert r["evidence"]["standalone"] is True


def test_pp02_embedded_section_compliant():
    text = "We use cookies. Our cookie policy explains cookie types. See our cookie table below."
    r = pp.check_pp02({"cookie_policy_reachable": False, "policy_text": text})
    assert r["label"] == "Compliant"
    assert r["evidence"]["standalone"] is False


def test_pp02_no_cookie_section_non_compliant():
    r = pp.check_pp02({"cookie_policy_reachable": False, "policy_text": "We respect your privacy."})
    assert r["label"] == "Non-Compliant"


# --- PP-03 ---

def test_pp03_email_found_compliant():
    r = pp.check_pp03({"policy_text": "Contact us at privacy@example.com.ng for questions."})
    assert r["label"] == "Compliant"
    assert r["evidence"]["email_found"] is True


def test_pp03_dpo_mentioned_compliant():
    r = pp.check_pp03({"policy_text": "Our Data Protection Officer can be reached via the contact form."})
    assert r["label"] == "Compliant"
    assert r["evidence"]["dpo_mentioned"] is True


def test_pp03_no_contact_non_compliant():
    r = pp.check_pp03({"policy_text": "We collect data for various purposes."})
    assert r["label"] == "Non-Compliant"


def test_pp03_no_text_non_compliant():
    r = pp.check_pp03({"policy_text": None})
    assert r["label"] == "Non-Compliant"


# --- PP-04 ---

def test_pp04_purpose_near_data_category_compliant():
    text = "We use your email address in order to send you order confirmations."
    r = pp.check_pp04({"policy_text": text})
    assert r["label"] == "Compliant"


def test_pp04_no_adjacency_non_compliant():
    text = "We use your data to improve our services generally."  # vague, no named category nearby
    r = pp.check_pp04({"policy_text": text})
    assert r["label"] == "Non-Compliant"


def test_pp04_no_purpose_phrase_non_compliant():
    r = pp.check_pp04({"policy_text": "We collect your name and email."})
    assert r["label"] == "Non-Compliant"


# --- PP-05 ---

def test_pp05_fixed_duration_compliant():
    text = "We retain your data for a period of 12 months after account closure."
    r = pp.check_pp05({"policy_text": text})
    assert r["label"] == "Compliant"
    assert r["evidence"]["has_duration"] is True


def test_pp05_trigger_criterion_compliant():
    text = "We will retain your data until you withdraw consent."
    r = pp.check_pp05({"policy_text": text})
    assert r["label"] == "Compliant"
    assert r["evidence"]["has_trigger_criterion"] is True


def test_pp05_marker_without_duration_or_trigger_non_compliant():
    text = "Our retention practices are designed to be fair."  # marker present, no actual duration/criterion
    r = pp.check_pp05({"policy_text": text})
    assert r["label"] == "Non-Compliant"


def test_pp05_no_marker_non_compliant():
    r = pp.check_pp05({"policy_text": "We collect your email address."})
    assert r["label"] == "Non-Compliant"


# --- PP-06 ---

def test_pp06_all_rights_compliant():
    text = (
        "You have the right to access your personal data, request rectification, "
        "erasure of your data, restrict processing, data portability, and the "
        "right to object. You may also lodge a complaint with the NDPC."
    )
    r = pp.check_pp06({"policy_text": text})
    assert r["label"] == "Compliant"
    assert r["evidence"]["complaint_to_ndpc_disclosed"] is True


def test_pp06_missing_complaint_right_partial_note():
    text = (
        "You have the right to access your personal data, request rectification, "
        "erasure of your data, restrict processing, and data portability."
    )
    r = pp.check_pp06({"policy_text": text})
    assert r["label"] == "Compliant"  # 5/7 meets threshold
    assert r["evidence"]["complaint_to_ndpc_disclosed"] is False
    assert "NDPC" in r["notes"]


def test_pp06_too_few_rights_non_compliant():
    text = "You have the right to access your personal data."
    r = pp.check_pp06({"policy_text": text})
    assert r["label"] == "Non-Compliant"


def test_pp06_no_text_non_compliant():
    r = pp.check_pp06({"policy_text": None})
    assert r["label"] == "Non-Compliant"


# --- evaluate() end-to-end ---

def test_evaluate_returns_six_results():
    sr = make_scan_result({"privacy_policy_reachable": True, "privacy_policy_url": "x", "policy_text": "some text"})
    results = pp.evaluate(sr)
    assert len(results) == 6
    assert {r["rule_id"] for r in results} == {"PP-01", "PP-02", "PP-03", "PP-04", "PP-05", "PP-06"}