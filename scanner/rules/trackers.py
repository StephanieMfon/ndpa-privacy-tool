"""
scanner/rules/trackers.py

Phase 3, Module 4 — TR-01 and TR-02.

TR-01 is descriptive detection, not a Compliant/Non-Compliant judgment
(Rulebook, Section C: "this item is descriptive detection... a tracker's
presence is scored for compliance under CN-02 ... and SB-03"). This module
returns it as a single Not Applicable RuleResult carrying the full
detection list as evidence — that list is also exposed via detect() for
reuse by CN-02, SB-03, and TR-02 itself, so detection logic lives in
exactly one place.

TR-02 is the actual scored rule: is each detected tracker named in the
site's disclosures? Same "pending policy cross-reference" pattern as
CK-04/CK-05 — runs standalone now, final label once Module 6 exists.
"""

import json
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "tracker_signatures.json"


def _load_tracker_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def detect_trackers(scan_result: dict) -> list[dict]:
    """
    Match every request in scan_result["network_log"] against the fixed
    vendor signature list. Returns one entry per vendor actually detected
    (deduplicated), with the earliest-seen timestamp and an example URL.

    New/unlisted trackers are, by design, invisible here — this is a stated
    tool-coverage limitation (Rulebook TR-01 edge case), not a bug.
    """
    config = _load_tracker_config()
    network_log = scan_result.get("network_log", [])

    detected_by_vendor = {}
    for vendor in config["vendors"]:
        name = vendor["name"]
        signatures = [s.lower() for s in vendor["signatures"]]
        matches = [
            req for req in network_log
            if any(sig in req["url"].lower() for sig in signatures)
        ]
        if matches:
            earliest = min(matches, key=lambda r: r["timestamp"])
            detected_by_vendor[name] = {
                "vendor": name,
                "matched_url": earliest["url"],
                "first_seen_timestamp": earliest["timestamp"],
                "request_count": len(matches),
            }

    return list(detected_by_vendor.values())


def all_tracker_requests(scan_result: dict) -> list[dict]:
    """
    Every individual request matching a fixed vendor signature — NOT
    deduplicated to one-per-vendor like detect_trackers(). Used by SB-04
    (script_behaviour.py) to check whether ANY tracker request follows a
    fingerprinting API call within the correlation window, not just the
    first one ever seen on the page.
    """
    config = _load_tracker_config()
    network_log = scan_result.get("network_log", [])

    matches = []
    for vendor in config["vendors"]:
        name = vendor["name"]
        signatures = [s.lower() for s in vendor["signatures"]]
        for req in network_log:
            if any(sig in req["url"].lower() for sig in signatures):
                matches.append({"vendor": name, "url": req["url"], "timestamp": req["timestamp"]})

    return matches


def check_tr01(detected: list[dict]) -> dict:
    """Descriptive only — see module docstring. Always Not Applicable."""
    return {
        "rule_id": "TR-01",
        "category": "trackers",
        "label": "Not Applicable",
        "evidence": {"detected_trackers": detected},
        "notes": "Descriptive detection only, per Rulebook Section C — not itself scored. "
                 "Evidence base for CN-02, SB-03, and TR-02.",
    }


def check_tr02(tracker: dict, policy_text: str | None) -> dict:
    """Is this detected tracker named/described anywhere in the site's disclosures?"""
    evidence = {"vendor": tracker["vendor"], "matched_url": tracker["matched_url"]}

    if policy_text is None:
        evidence["pending_policy_crossref"] = True
        return {
            "rule_id": "TR-02", "category": "trackers", "label": "Unable to Determine",
            "evidence": evidence,
            "notes": f"{tracker['vendor']} detected. Disclosure not yet checked — pending Module 6 (privacy_policy), "
                     f"or the policy page could not be reached for this site.",
        }

    disclosed = tracker["vendor"].lower() in policy_text.lower()
    if disclosed:
        return {
            "rule_id": "TR-02", "category": "trackers", "label": "Compliant",
            "evidence": evidence, "notes": f"{tracker['vendor']} named in policy.",
        }
    return {
        "rule_id": "TR-02", "category": "trackers", "label": "Non-Compliant",
        "evidence": evidence, "notes": f"{tracker['vendor']} not named anywhere in policy.",
    }


def evaluate(scan_result: dict, policy_text: str | None = None) -> list[dict]:
    """Run TR-01 (once) and TR-02 (per detected tracker) against one site."""
    detected = detect_trackers(scan_result)
    results = [check_tr01(detected)]
    results.extend(check_tr02(t, policy_text) for t in detected)
    return results