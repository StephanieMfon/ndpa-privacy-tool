import pytest

from ndpa.models import Outcome, RuleResult, RunStatus, ScanStatus
from ndpa.remediation.fixes import fix_first
from ndpa.scoring.score import load_rulebook, scan_status, score

RB = load_rulebook()
SCORED = [r["id"] for r in RB["rules"] if r["tier"] != "unscored"]
C, N, A, U = Outcome.COMPLIANT, Outcome.NON_COMPLIANT, Outcome.NOT_APPLICABLE, Outcome.UNABLE_TO_DETERMINE


def results(default=C, **overrides):
    """All 17 scored rules with one outcome, and overrides like CN_01=N."""
    changed = {k.replace("_", "-"): v for k, v in overrides.items()}
    return [RuleResult(rule_id=i, outcome=changed.get(i, default), instances_failed=3 if changed.get(i) == N else 0)
            for i in SCORED]


def test_the_rulebook_has_the_expected_shape():
    rules = {r["id"]: r for r in RB["rules"]}
    assert len(rules) == 18 and len(SCORED) == 17
    assert sum(rules[i]["weight"] for i in SCORED) == RB["scoring"]["expected_total_weight"] == 28
    pairs = {}
    for i in SCORED:
        if rules[i].get("pair"):
            pairs.setdefault(rules[i]["pair"], set()).add(i)
    assert pairs == {"cookie_pair": {"CN-02", "SB-02"}, "tracker_pair": {"SB-01", "SB-03"}}
    assert all(rules[i]["weight"] == 1.5 for ids in pairs.values() for i in ids)
    assert all(rules[i]["remediation"]["fix"] and rules[i]["remediation"]["clause"] for i in SCORED)
    assert {rules[i]["category"] for i in SCORED} == set(RB["scoring"]["category_axes"])


def test_all_compliant_is_100_and_low_risk():
    card = score(results(), RB)
    assert (card.score_weighted, card.score_equal, card.band, card.coverage, card.critical_count) == (100.0, 100.0, "low", 1.0, 0)


def test_a_major_failure_costs_its_weight_and_makes_the_band_moderate():
    card = score(results(CN_01=N), RB)
    assert card.score_weighted == pytest.approx(92.9, abs=0.05) and card.band == "moderate" and card.critical_count == 0


def test_a_minor_failure_keeps_the_band_low():
    card = score(results(CN_04=N), RB)
    assert card.band == "low" and card.score_weighted == pytest.approx(96.4, abs=0.05)


def test_paired_critical_rules_share_one_penalty():
    card = score(results(CN_02=N, SB_02=N), RB)
    assert card.score_weighted == pytest.approx(89.3, abs=0.05)   # lost 3 of 28
    assert card.score_equal == pytest.approx(93.3, abs=0.05)      # lost 1 of 15
    assert card.band == "high" and card.critical_count == 2
    both = score(results(CN_02=N, SB_02=N, SB_01=N, SB_03=N), RB)
    assert both.score_weighted == pytest.approx(78.6, abs=0.05)   # lost 6 of 28, not 12


def test_not_applicable_is_excluded_but_counts_as_determined():
    card = score(results(default=A, CN_01=N), RB)
    assert card.score_weighted == 0.0 and card.coverage == 1.0


def test_undetermined_rules_lower_coverage_and_can_hide_the_score():
    policy_rules = {f"PP_0{i}": U for i in range(1, 7)}
    card = score(results(**policy_rules), RB)
    assert card.coverage == pytest.approx(0.643, abs=0.001) and card.score_weighted is None and "hidden" in card.note
    one = score(results(PP_01=U), RB)
    assert one.coverage == pytest.approx(0.929, abs=0.001) and one.score_weighted == 100.0


def test_nothing_applicable_gives_no_score():
    card = score(results(default=A), RB)
    assert card.score_weighted is None and "nothing to score" in card.note


def test_empty_categories_are_plotted_at_100():
    card = score(results(default=C, CN_01=A, CN_02=A, CN_03=A, CN_04=A, CN_05=A), RB)
    assert "consent" in card.empty_categories and card.category_scores["consent"] == 100.0


def test_category_scores():
    card = score(results(CK_02=N), RB)
    assert card.category_scores["cookies"] == pytest.approx(33.3, abs=0.05) and card.category_scores["consent"] == 100.0


def test_a_blocked_or_failed_scan_has_no_score():
    assert score([], RB, scan_status(RunStatus.BLOCKED)).status == ScanStatus.BLOCKED
    card = score([], RB, scan_status(RunStatus.FAILED))
    assert card.status == ScanStatus.FAILED and card.score_weighted is None and card.band is None


def test_fix_first_orders_by_tier_then_number_affected():
    rows = fix_first(results(CN_04=N, SB_03=N, CN_01=N, PP_05=N), RB)
    assert [r["rule_id"] for r in rows] == ["SB-03", "CN-01", "CN-04", "PP-05"]
    assert rows[0]["tier"] == "critical" and rows[0]["fix"] and rows[0]["clause"]
