# """
# scanner/scoring.py

# Phase 3, Module 7 — Scoring engine.

# Equal weight per rule (locked decision — see docs/data_format.md and
# Phase3_Handoff_Context.md Section 7: equal weight chosen over
# severity-weighting because it doesn't require independently justifying
# why one rule outweighs another in the viva).

# Site score = compliant / (compliant + non_compliant). Not Applicable
# results are excluded from the denominator — a rule that doesn't apply to
# a site shouldn't move that site's score either direction.
# """


# def _score_subset(results: list[dict]) -> dict:
#     compliant = sum(1 for r in results if r["label"] == "Compliant")
#     non_compliant = sum(1 for r in results if r["label"] == "Non-Compliant")
#     not_applicable = sum(1 for r in results if r["label"] == "Not Applicable")
#     denom = compliant + non_compliant
#     score = round(compliant / denom, 4) if denom > 0 else None
#     return {
#         "compliant": compliant,
#         "non_compliant": non_compliant,
#         "not_applicable": not_applicable,
#         "score": score,  # None means every applicable rule was Not Applicable — no basis to score
#     }


# def score_results(rule_results: list[dict]) -> dict:
#     """
#     rule_results: the COMBINED list of RuleResult dicts from every module
#     (cookies, consent, trackers, script_behaviour, privacy_policy) for ONE
#     site — this is a single-site score, not a dataset-wide aggregate.

#     Returns {"overall": {...}, "by_category": {category: {...}, ...}}.
#     """
#     overall = _score_subset(rule_results)

#     categories = sorted(set(r["category"] for r in rule_results))
#     by_category = {cat: _score_subset([r for r in rule_results if r["category"] == cat]) for cat in categories}

#     return {"overall": overall, "by_category": by_category}

"""
scanner/scoring.py

Phase 3, Module 7 — Scoring engine.

Equal weight per rule (locked decision — see docs/data_format.md and
Phase3_Handoff_Context.md Section 7: equal weight chosen over
severity-weighting because it doesn't require independently justifying
why one rule outweighs another in the viva).

Site score = compliant / (compliant + non_compliant). Not Applicable AND
Unable to Determine results are both excluded from the denominator — a
rule that doesn't apply, or one the tool lacked evidence to evaluate,
shouldn't move a site's score either direction. They're tracked as
separate counts, not merged, since they mean different things: Not
Applicable is a rule-level judgment ("this rule doesn't apply here");
Unable to Determine is a tool-execution status ("the tool didn't have
enough evidence to judge this" — e.g. CK-04/CK-05/TR-02 when a site's
privacy policy couldn't be located or fetched). Note this status is
tool-specific, not part of the Annotation Rulebook's 3-label manual
annotation convention (§0.1) — it should be excluded entirely from any
tool-vs-human precision/recall/F1 comparison in Phase 7, since no human
gold label will ever carry it.
"""


def _score_subset(results: list[dict]) -> dict:
    compliant = sum(1 for r in results if r["label"] == "Compliant")
    non_compliant = sum(1 for r in results if r["label"] == "Non-Compliant")
    not_applicable = sum(1 for r in results if r["label"] == "Not Applicable")
    unable_to_determine = sum(1 for r in results if r["label"] == "Unable to Determine")
    denom = compliant + non_compliant
    score = round(compliant / denom, 4) if denom > 0 else None
    return {
        "compliant": compliant,
        "non_compliant": non_compliant,
        "not_applicable": not_applicable,
        "unable_to_determine": unable_to_determine,
        "score": score,  # None means every applicable rule was NA/UTD — no basis to score
    }


def score_results(rule_results: list[dict]) -> dict:
    """
    rule_results: the COMBINED list of RuleResult dicts from every module
    (cookies, consent, trackers, script_behaviour, privacy_policy) for ONE
    site — this is a single-site score, not a dataset-wide aggregate.

    Returns {"overall": {...}, "by_category": {category: {...}, ...}}.
    """
    overall = _score_subset(rule_results)

    categories = sorted(set(r["category"] for r in rule_results))
    by_category = {cat: _score_subset([r for r in rule_results if r["category"] == cat]) for cat in categories}

    return {"overall": overall, "by_category": by_category}