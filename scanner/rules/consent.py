# """
# scanner/rules/consent.py

# Phase 3, Module 3 (rules half) — CN-01 to CN-07.

# Pure decision logic. Takes a ConsentCaptureResult (from consent_capture.py)
# and applies the Fixed Decisions Register / Annotation Rulebook rules.
# Fully unit-testable without a browser — unlike consent_capture.py itself.
# """

# BANNER_BOTTOM_ZONE_RATIO = 0.75  # per Fixed Decisions #4: bottom 25% of viewport


# def check_cn01(capture: dict) -> dict:
#     """Banner presence and conspicuousness. Non-compliant if absent, or top edge in bottom 25% of viewport."""
#     if not capture["banner_detected"]:
#         return _result("CN-01", "Non-Compliant", notes="No consent banner detected on first load.")

#     position = capture.get("banner_position")
#     if not position or position.get("top_ratio") is None:
#         return _result("CN-01", "Non-Compliant", notes="Banner detected but position could not be determined.")

#     if position["top_ratio"] >= BANNER_BOTTOM_ZONE_RATIO:
#         return _result("CN-01", "Non-Compliant", evidence={"top_ratio": position["top_ratio"]},
#                         notes="Banner's top edge sits in the bottom 25% of the viewport.")

#     return _result("CN-01", "Compliant", evidence={"top_ratio": position["top_ratio"]})


# def check_cn02(capture: dict, scan_result: dict) -> dict:
#     """
#     Consent obtained before non-essential cookies are set.
#     Compares cookies present before the Accept click against cookies known
#     to be essential (via cookies.is_essential — imported lazily to avoid a
#     circular import at module load time).
#     """
#     from scanner.rules.cookies import is_essential, _load_essential_config

#     if not capture["banner_detected"]:
#         return _result("CN-02", "Not Applicable", notes="No banner detected — evaluated separately under CN-01.")

#     config = _load_essential_config()
#     cookies_before_names = set(capture["cookies_before_consent"])
#     all_cookies_by_name = {c["name"]: c for c in scan_result.get("cookies", [])}

#     non_essential_before = [
#         name for name in cookies_before_names
#         if name in all_cookies_by_name and not is_essential(all_cookies_by_name[name], config)
#     ]

#     if non_essential_before:
#         return _result("CN-02", "Non-Compliant",
#                         evidence={"non_essential_cookies_before_consent": non_essential_before},
#                         notes="Non-essential cookie(s) present before the Accept click.")

#     return _result("CN-02", "Compliant")


# def check_cn03(capture: dict) -> dict:
#     """Reject option availability. Non-compliant if only Accept exists."""
#     if not capture["banner_detected"]:
#         return _result("CN-03", "Not Applicable", notes="No banner detected.")

#     reject = capture.get("reject_button")
#     if reject and reject.get("found"):
#         return _result("CN-03", "Compliant")

#     return _result("CN-03", "Non-Compliant", notes="No reject/decline control found on the banner.")


# def check_cn04(capture: dict) -> dict:
#     """
#     Reject as easy as Accept. Fixed visual rule (Fixed Decisions #3):
#     Non-compliant if Accept is a filled/coloured button and Reject is plain text.
#     """
#     if not capture["banner_detected"]:
#         return _result("CN-04", "Not Applicable", notes="No banner detected.")

#     accept = capture.get("accept_button")
#     reject = capture.get("reject_button")

#     if not reject or not reject.get("found"):
#         return _result("CN-04", "Not Applicable", notes="No reject control exists — scored separately under CN-03.")

#     if accept and accept.get("is_filled") and not reject.get("is_filled"):
#         return _result("CN-04", "Non-Compliant",
#                         notes="Accept is a filled/coloured button; Reject is plain text.")

#     return _result("CN-04", "Compliant")


# def check_cn05(capture: dict) -> dict:
#     """Granular consent. Not Applicable if fewer than 2 non-essential categories exist to separate."""
#     if not capture["banner_detected"]:
#         return _result("CN-05", "Not Applicable", notes="No banner detected.")

#     toggles = capture.get("granular_toggles_found", [])
#     if len(toggles) >= 2:
#         return _result("CN-05", "Compliant", evidence={"categories_found": toggles})

#     if len(toggles) == 1:
#         return _result("CN-05", "Not Applicable",
#                         evidence={"categories_found": toggles},
#                         notes="Only one non-essential category in use — structurally cannot offer granular choice.")

#     return _result("CN-05", "Non-Compliant", notes="All non-essential cookies bundled into a single accept/reject choice.")


# def check_cn06(capture: dict) -> dict:
#     """Consent recorded. Non-compliant if no persistence mechanism observed."""
#     if not capture["banner_detected"]:
#         return _result("CN-06", "Not Applicable", notes="No banner detected.")

#     if capture.get("consent_state_storage_found") or capture.get("consent_persisted_after_reload"):
#         return _result("CN-06", "Compliant")

#     return _result("CN-06", "Non-Compliant",
#                     notes="No observable consent-state storage, and banner reappeared after reload (or reload check inconclusive).")


# def check_cn07(capture: dict) -> dict:
#     """Consent withdrawal mechanism. Non-compliant if no in-site control exists to revisit choice."""
#     if capture.get("withdrawal_mechanism_found"):
#         return _result("CN-07", "Compliant", evidence={"mechanism_text": capture.get("withdrawal_mechanism_text")})

#     return _result("CN-07", "Non-Compliant", notes="No footer/settings control found to revisit consent choice.")


# def _result(rule_id: str, label: str, evidence: dict | None = None, notes: str | None = None) -> dict:
#     return {
#         "rule_id": rule_id,
#         "category": "consent",
#         "label": label,
#         "evidence": evidence or {},
#         "notes": notes,
#     }


# def evaluate(capture: dict, scan_result: dict) -> list[dict]:
#     """Run CN-01 through CN-07 against one site's consent capture data."""
#     return [
#         check_cn01(capture),
#         check_cn02(capture, scan_result),
#         check_cn03(capture),
#         check_cn04(capture),
#         check_cn05(capture),
#         check_cn06(capture),
#         check_cn07(capture),
#     ]

"""
scanner/rules/consent.py

Phase 3, Module 3 (rules half) — CN-01 to CN-07.

Pure decision logic. Takes a ConsentCaptureResult (from consent_capture.py)
and applies the Fixed Decisions Register / Annotation Rulebook rules.
Fully unit-testable without a browser — unlike consent_capture.py itself.
"""

BANNER_BOTTOM_ZONE_RATIO = 0.75  # per Fixed Decisions #4: bottom 25% of viewport


def check_cn01(capture: dict) -> dict:
    """Banner presence and conspicuousness. Non-compliant if absent, or top edge in bottom 25% of viewport."""
    if not capture["banner_detected"]:
        return _result("CN-01", "Non-Compliant", notes="No consent banner detected on first load.")

    position = capture.get("banner_position")
    if not position or position.get("top_ratio") is None:
        return _result("CN-01", "Non-Compliant", notes="Banner detected but position could not be determined.")

    if position["top_ratio"] >= BANNER_BOTTOM_ZONE_RATIO:
        return _result("CN-01", "Non-Compliant", evidence={"top_ratio": position["top_ratio"]},
                        notes="Banner's top edge sits in the bottom 25% of the viewport.")

    return _result("CN-01", "Compliant", evidence={"top_ratio": position["top_ratio"]})


def _non_essential_cookies_before_consent(capture: dict, scan_result: dict) -> list[str]:
    """
    Shared by CN-02 and SB-02 (script_behaviour.py) — both rules ask the
    same underlying question ("was a non-essential cookie present before
    the Accept click?"), just from different legal angles. Single source
    of truth so the two never drift out of sync.
    """
    from scanner.rules.cookies import is_essential, _load_essential_config

    config = _load_essential_config()
    cookies_before_names = set(capture["cookies_before_consent"])
    all_cookies_by_name = {c["name"]: c for c in scan_result.get("cookies", [])}

    return [
        name for name in cookies_before_names
        if name in all_cookies_by_name and not is_essential(all_cookies_by_name[name], config)
    ]


def check_cn02(capture: dict, scan_result: dict) -> dict:
    """
    Consent obtained before non-essential cookies are set.
    """
    if not capture["banner_detected"]:
        return _result("CN-02", "Not Applicable", notes="No banner detected — evaluated separately under CN-01.")

    non_essential_before = _non_essential_cookies_before_consent(capture, scan_result)

    if non_essential_before:
        return _result("CN-02", "Non-Compliant",
                        evidence={"non_essential_cookies_before_consent": non_essential_before},
                        notes="Non-essential cookie(s) present before the Accept click.")

    return _result("CN-02", "Compliant")


def check_cn03(capture: dict) -> dict:
    """Reject option availability. Non-compliant if only Accept exists."""
    if not capture["banner_detected"]:
        return _result("CN-03", "Not Applicable", notes="No banner detected.")

    reject = capture.get("reject_button")
    if reject and reject.get("found"):
        return _result("CN-03", "Compliant")

    return _result("CN-03", "Non-Compliant", notes="No reject/decline control found on the banner.")


def check_cn04(capture: dict) -> dict:
    """
    Reject as easy as Accept. Fixed visual rule (Fixed Decisions #3):
    Non-compliant if Accept is a filled/coloured button and Reject is plain text.
    """
    if not capture["banner_detected"]:
        return _result("CN-04", "Not Applicable", notes="No banner detected.")

    accept = capture.get("accept_button")
    reject = capture.get("reject_button")

    if not reject or not reject.get("found"):
        return _result("CN-04", "Not Applicable", notes="No reject control exists — scored separately under CN-03.")

    if accept and accept.get("is_filled") and not reject.get("is_filled"):
        return _result("CN-04", "Non-Compliant",
                        notes="Accept is a filled/coloured button; Reject is plain text.")

    return _result("CN-04", "Compliant")


def check_cn05(capture: dict) -> dict:
    """Granular consent. Not Applicable if fewer than 2 non-essential categories exist to separate."""
    if not capture["banner_detected"]:
        return _result("CN-05", "Not Applicable", notes="No banner detected.")

    toggles = capture.get("granular_toggles_found", [])
    if len(toggles) >= 2:
        return _result("CN-05", "Compliant", evidence={"categories_found": toggles})

    if len(toggles) == 1:
        return _result("CN-05", "Not Applicable",
                        evidence={"categories_found": toggles},
                        notes="Only one non-essential category in use — structurally cannot offer granular choice.")

    return _result("CN-05", "Non-Compliant", notes="All non-essential cookies bundled into a single accept/reject choice.")


def check_cn06(capture: dict) -> dict:
    """Consent recorded. Non-compliant if no persistence mechanism observed."""
    if not capture["banner_detected"]:
        return _result("CN-06", "Not Applicable", notes="No banner detected.")

    if capture.get("consent_state_storage_found") or capture.get("consent_persisted_after_reload"):
        return _result("CN-06", "Compliant")

    return _result("CN-06", "Non-Compliant",
                    notes="No observable consent-state storage, and banner reappeared after reload (or reload check inconclusive).")


def check_cn07(capture: dict) -> dict:
    """Consent withdrawal mechanism. Non-compliant if no in-site control exists to revisit choice."""
    if capture.get("withdrawal_mechanism_found"):
        return _result("CN-07", "Compliant", evidence={"mechanism_text": capture.get("withdrawal_mechanism_text")})

    return _result("CN-07", "Non-Compliant", notes="No footer/settings control found to revisit consent choice.")


def _result(rule_id: str, label: str, evidence: dict | None = None, notes: str | None = None) -> dict:
    return {
        "rule_id": rule_id,
        "category": "consent",
        "label": label,
        "evidence": evidence or {},
        "notes": notes,
    }


def evaluate(capture: dict, scan_result: dict) -> list[dict]:
    """Run CN-01 through CN-07 against one site's consent capture data."""
    return [
        check_cn01(capture),
        check_cn02(capture, scan_result),
        check_cn03(capture),
        check_cn04(capture),
        check_cn05(capture),
        check_cn06(capture),
        check_cn07(capture),
    ]