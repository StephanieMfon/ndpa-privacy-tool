# Shared Data Format — Phase 3

Every module reads/writes plain dicts serialized to JSON. No ORM, no classes.
This file is the single source of truth for the shape — if a module needs a
new field, add it here first, then update the module and this doc together.

## SiteScanResult
Produced by `scanner/harness.py`, one per site per scan. Consumed by every
rule module.

```python
{
    "url": str,
    "scanned_at": str,              # ISO 8601 UTC timestamp
    "har_path": str,                # path relative to repo root
    "screenshot_path": str,
    "dom_path": str,
    "cookies": [
        {
            "name": str, "domain": str, "path": str,
            "secure": bool, "httpOnly": bool, "sameSite": str,
            "expires": float        # -1 = session cookie
        }
    ],
    "network_log": [
        {"url": str, "timestamp": float, "resource_type": str, "method": str}
        # timestamp is seconds since navigation start (monotonic clock),
        # NOT wall-clock time — used to compare against consent_events
    ],
    "consent_events": {
        "accept_clicked_at": float or None,   # same monotonic clock as network_log
        "reject_clicked_at": float or None
    }
}
```

`consent_events` is populated by the consent module (Module 3), not the
harness. Harness always writes it as `{None, None}`.

## RuleResult
Produced by every `scanner/rules/*.py` module. One list of these per site.

```python
{
    "rule_id": str,      # e.g. "CK-01", matches Annotation Rulebook exactly
    "category": str,     # "cookies" | "consent" | "trackers" | "script_behaviour" | "privacy_policy"
    "label": str,        # "Compliant" | "Non-Compliant" | "Not Applicable" | "Unable to Determine"
    "evidence": dict,    # rule-specific — cookie name, screenshot ref, quoted policy text ref, etc.
    "notes": str or None
}
```

`label` is one of these four values exactly. The first three match the
Annotation Rulebook's Section 0.1 (no fourth "unclear" category for
*manual annotation*). "Unable to Determine" is a tool-specific fourth
status, distinct from that convention — it means the tool lacked enough
evidence to evaluate a rule (currently: CK-04, CK-05, TR-02 when a site's
privacy policy couldn't be located or fetched), not an interpretive
judgment on complete evidence. It is excluded from the compliance score
the same way Not Applicable is, but tracked as a separate count, and MUST
be excluded from any tool-vs-human precision/recall/F1 comparison in
Phase 7 — no human annotator ever produces this label, so it isn't
comparable to a gold label.

## Scoring convention (locked)
Equal weight per rule. Site compliance score = (Compliant count) /
(Compliant + Non-Compliant count), excluding Not Applicable from the
denominator. Documented as a methodological choice, not a statutory
requirement — matches CK-04/CN-04's own precedent of stating chosen
thresholds explicitly.