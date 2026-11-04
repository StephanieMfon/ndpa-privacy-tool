"""Scoring (decisions D-02 to D-06): weighted score, equal-weight score, risk band, coverage, category scores.

Weights come from the rulebook YAML and are fixed in advance, never tuned. Rules that overlap by design are paired:
CN-02 and SB-02 share 3 points, SB-01 and SB-03 share 3 points.
"""
from pathlib import Path

import yaml

from ndpa.models import Outcome, RuleResult, RunStatus, ScanStatus, ScoreCard

RULEBOOK_PATH = Path("rulebook/rules.v2.yaml")
DETERMINED = {Outcome.COMPLIANT, Outcome.NON_COMPLIANT, Outcome.NOT_APPLICABLE}
SCORED = {Outcome.COMPLIANT, Outcome.NON_COMPLIANT}


def load_rulebook(path: Path = RULEBOOK_PATH) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def scan_status(no_action_status: RunStatus) -> ScanStatus:
    return {RunStatus.OK: ScanStatus.DONE, RunStatus.BLOCKED: ScanStatus.BLOCKED}.get(no_action_status, ScanStatus.FAILED)


def _percent(compliant_weight: float, total_weight: float) -> float:
    return round(100 * compliant_weight / total_weight, 1)


def score(results: list[RuleResult], rulebook: dict, status: ScanStatus = ScanStatus.DONE) -> ScoreCard:
    if status in (ScanStatus.BLOCKED, ScanStatus.FAILED):
        return ScoreCard(status=status, note=f"the scan was {status.value}: nothing could be assessed, so there is no score")
    rules = {r["id"]: r for r in rulebook["rules"] if r.get("tier") != "unscored"}
    total_weight = sum(r["weight"] for r in rules.values())
    by_id = {r.rule_id: r for r in results if r.rule_id in rules}

    determined_weight = sum(rules[i]["weight"] for i, r in by_id.items() if r.outcome in DETERMINED)
    coverage = round(determined_weight / total_weight, 3)

    def equal(rule_id: str) -> float:
        return 0.5 if rules[rule_id].get("pair") else 1.0

    scored = {i: r for i, r in by_id.items() if r.outcome in SCORED}
    ok = {i for i, r in scored.items() if r.outcome == Outcome.COMPLIANT}
    weighted = _percent(sum(rules[i]["weight"] for i in ok), sum(rules[i]["weight"] for i in scored)) if scored else None
    equal_score = _percent(sum(equal(i) for i in ok), sum(equal(i) for i in scored)) if scored else None

    failed = [i for i, r in scored.items() if r.outcome == Outcome.NON_COMPLIANT]
    critical_count = sum(1 for i in failed if rules[i]["tier"] == "critical")
    if critical_count:
        band = "high"
    elif any(rules[i]["tier"] == "major" for i in failed):
        band = "moderate"
    else:
        band = "low"

    categories: dict[str, float] = {}
    empty: list[str] = []
    for category in rulebook["scoring"]["category_axes"]:
        members = [i for i in scored if rules[i]["category"] == category]
        if not members:
            categories[category] = 100.0
            empty.append(category)
        else:
            categories[category] = _percent(sum(rules[i]["weight"] for i in members if i in ok),
                                            sum(rules[i]["weight"] for i in members))

    card = ScoreCard(status=status, score_weighted=weighted, score_equal=equal_score, band=band,
                     critical_count=critical_count, coverage=coverage, category_scores=categories, empty_categories=empty)
    if not scored:
        card.note = "no rule was applicable, so there is nothing to score"
    hide_below = rulebook["scoring"]["coverage"]["hide_score_below"]
    if coverage < hide_below:
        card.score_weighted = card.score_equal = None
        card.note = f"score hidden: only {coverage:.0%} of the rule weight could be determined (minimum {hide_below:.0%})"
    return card
