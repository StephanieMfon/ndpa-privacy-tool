"""

Phase 3, Module 2 — Cookie rules (CK-01 to CK-05).

Reads a SiteScanResult (from harness.py) and returns a list of RuleResult
dicts, one set per cookie, per docs/data_format.md.

Two rules (CK-04, CK-05) need the site's Privacy Policy text to reach a
final label — that module doesn't exist yet (Module 6). Both rules run
here regardless and return their best available label:
  - if policy_text is None: label reflects only the observable evidence,
    with evidence["pending_policy_crossref"] = True
  - if policy_text is provided: full decision rule applied

Interpretive choice (state this in the methodology chapter, matches the
CN-04/CN-01 precedent of documenting fixed thresholds):
  CK-01/CK-02 exempt ONLY the CMP cookies (genuine UI-state flags), not the
  session/security cookies. A session/auth cookie is exactly the case these
  two rules exist to check, per the Rulebook's own exemption text
  ("no personal or session-identifying value").
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "essential_cookies.json"
CK04_THRESHOLD_SECONDS = 6 * 30 * 24 * 60 * 60  # 6 months, per Fixed Decisions Register #5


def _load_essential_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def is_cmp_cookie(name: str, config: dict) -> bool:
    """True if this is a consent-management-tool UI-state cookie (always essential, always exempt from CK-01/02)."""
    if name in config["cmp_cookies"]:
        return True
    return any(name.startswith(prefix) for prefix in config["cmp_cookie_prefixes"])


def is_session_security_cookie(name: str, config: dict) -> bool:
    """True if this is a fixed session/security cookie name (essential for CN-02/SB-02, but still scored under CK-01/02)."""
    return name in config["session_security_cookies"]


def is_essential(cookie: dict, config: dict) -> bool:
    """
    Essential = exempt from consent-timing rules (CN-02, SB-02).
    Per Fixed Decisions #1: CMP cookies + session/security cookies are
    essential. Anything else defaults to NOT essential (no manual fallback
    test automated here — "if unsure, don't call it essential" per the
    register, so absence from both fixed lists is the deciding signal).
    """
    name = cookie["name"]
    return is_cmp_cookie(name, config) or is_session_security_cookie(name, config)


def classify_party(cookie: dict, site_url: str) -> str:
    """First-party if the cookie domain matches (or is a subdomain of) the visited site; else third-party."""
    site_host = urlparse(site_url).netloc.lower().lstrip("www.")
    cookie_domain = (cookie.get("domain") or "").lower().lstrip(".").lstrip("www.")
    if cookie_domain == site_host or cookie_domain.endswith("." + site_host) or site_host.endswith("." + cookie_domain):
        return "first-party"
    return "third-party"


def classify_persistence(cookie: dict) -> str:
    expires = cookie.get("expires")
    if expires is None or expires == -1:
        return "session"
    return "persistent"


# --- CK-01: Secure attribute ---------------------------------------------

def check_ck01(cookie: dict, config: dict) -> dict:
    if is_cmp_cookie(cookie["name"], config):
        return _result("CK-01", "Not Applicable", cookie,
                        notes="CMP UI-state cookie — exempt (carries no personal/session value).")

    if cookie.get("secure"):
        return _result("CK-01", "Compliant", cookie)

    return _result("CK-01", "Non-Compliant", cookie,
                    notes="Cookie set without Secure attribute.")


# --- CK-02: HttpOnly attribute --------------------------------------------

def check_ck02(cookie: dict, config: dict) -> dict:
    if is_cmp_cookie(cookie["name"], config):
        return _result("CK-02", "Not Applicable", cookie,
                        notes="CMP UI-state cookie — typically must be readable by client-side JS by design.")

    if cookie.get("httpOnly"):
        return _result("CK-02", "Compliant", cookie)

    return _result("CK-02", "Non-Compliant", cookie,
                    notes="Cookie set without HttpOnly attribute.")


# --- CK-03: SameSite attribute ---------------------------------------------

def check_ck03(cookie: dict, party: str) -> dict:
    same_site = (cookie.get("sameSite") or "").strip()

    if same_site.lower() == "none":
        if not cookie.get("secure"):
            return _result("CK-03", "Non-Compliant", cookie,
                            notes="SameSite=None without Secure attribute.")
        return _result("CK-03", "Compliant", cookie,
                        notes="SameSite=None with Secure — treated as a documented cross-site purpose "
                              "(e.g. embedded payment widget).")

    if not same_site:
        # Rulebook edge case: record as "absent", don't assume browser-default Lax.
        if party == "third-party":
            return _result("CK-03", "Non-Compliant", cookie,
                            notes="SameSite absent on a third-party cookie.")
        return _result("CK-03", "Compliant", cookie,
                        notes="SameSite absent on first-party cookie — browser default applies, not scored as violation.")

    if same_site.lower() in ("lax", "strict"):
        return _result("CK-03", "Compliant", cookie)

    return _result("CK-03", "Non-Compliant", cookie, notes=f"Unrecognised SameSite value: {same_site!r}")


# --- CK-04: Persistent cookie expiration proportionality ------------------

def check_ck04(cookie: dict, scanned_at_epoch: float, policy_text: str | None) -> dict:
    persistence = classify_persistence(cookie)
    if persistence == "session":
        return _result("CK-04", "Not Applicable", cookie, notes="Session cookie.")

    lifespan_seconds = cookie["expires"] - scanned_at_epoch
    exceeds_threshold = lifespan_seconds > CK04_THRESHOLD_SECONDS

    if not exceeds_threshold:
        return _result("CK-04", "Compliant", cookie,
                        notes=f"Expiry within 6-month threshold ({lifespan_seconds / 86400:.0f} days).")

    if policy_text is None:
        return _result("CK-04", "Non-Compliant", cookie,
                        notes=f"Exceeds 6-month threshold ({lifespan_seconds / 86400:.0f} days). "
                              f"Policy justification not yet checked — pending Module 6 (privacy_policy).",
                        pending_policy_crossref=True)

    # Placeholder matching until Module 6 defines the real text-search interface.
    justified = cookie["name"].lower() in policy_text.lower()
    if justified:
        return _result("CK-04", "Compliant", cookie,
                        notes="Exceeds 6-month threshold but policy provides justification.")
    return _result("CK-04", "Non-Compliant", cookie,
                    notes=f"Exceeds 6-month threshold ({lifespan_seconds / 86400:.0f} days), no policy justification found.")


# --- CK-05: Third-party cookie recipient disclosure ------------------------

def check_ck05(cookie: dict, party: str, policy_text: str | None) -> dict:
    if party == "first-party":
        return _result("CK-05", "Not Applicable", cookie, notes="First-party cookie.")

    if policy_text is None:
        return _result("CK-05", "Non-Compliant", cookie,
                        notes="Third-party cookie detected. Disclosure not yet checked — pending Module 6 (privacy_policy).",
                        pending_policy_crossref=True)

    domain = cookie.get("domain", "")
    disclosed = domain.lower() in policy_text.lower()
    if disclosed:
        return _result("CK-05", "Compliant", cookie, notes="Third-party origin named in policy.")
    return _result("CK-05", "Non-Compliant", cookie, notes="Third-party origin not named anywhere in policy.")


# --- glue -------------------------------------------------------------------

def _result(rule_id: str, label: str, cookie: dict, notes: str | None = None, pending_policy_crossref: bool = False) -> dict:
    evidence = {
        "cookie_name": cookie["name"],
        "cookie_domain": cookie.get("domain"),
    }
    if pending_policy_crossref:
        evidence["pending_policy_crossref"] = True
    return {
        "rule_id": rule_id,
        "category": "cookies",
        "label": label,
        "evidence": evidence,
        "notes": notes,
    }


def evaluate(scan_result: dict, policy_text: str | None = None) -> list[dict]:
    """
    Run CK-01 through CK-05 against every cookie in scan_result.

    Returns a flat list of RuleResult dicts (5 per cookie, some
    "Not Applicable" where the rule doesn't apply to that cookie).
    """
    config = _load_essential_config()
    site_url = scan_result["url"]
    scanned_at_epoch = datetime.fromisoformat(scan_result["scanned_at"]).timestamp()

    results = []
    for cookie in scan_result["cookies"]:
        party = classify_party(cookie, site_url)

        results.append(check_ck01(cookie, config))
        results.append(check_ck02(cookie, config))
        results.append(check_ck03(cookie, party))
        results.append(check_ck04(cookie, scanned_at_epoch, policy_text))
        results.append(check_ck05(cookie, party, policy_text))

    return results