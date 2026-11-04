"""
tests/test_scoring.py

Run: pytest tests/test_scoring.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scanner import scoring


def make_result(rule_id, category, label):
    return {"rule_id": rule_id, "category": category, "label": label, "evidence": {}, "notes": None}


def test_all_compliant_scores_100_percent():
    results = [make_result("CK-01", "cookies", "Compliant"), make_result("CK-02", "cookies", "Compliant")]
    score = scoring.score_results(results)
    assert score["overall"]["score"] == 1.0
    assert score["overall"]["compliant"] == 2
    assert score["overall"]["non_compliant"] == 0


def test_all_non_compliant_scores_0_percent():
    results = [make_result("CK-01", "cookies", "Non-Compliant"), make_result("CK-02", "cookies", "Non-Compliant")]
    score = scoring.score_results(results)
    assert score["overall"]["score"] == 0.0


def test_mixed_scores_correctly():
    results = [
        make_result("CK-01", "cookies", "Compliant"),
        make_result("CK-02", "cookies", "Compliant"),
        make_result("CK-03", "cookies", "Non-Compliant"),
    ]
    score = scoring.score_results(results)
    assert score["overall"]["score"] == round(2 / 3, 4)


def test_not_applicable_excluded_from_denominator():
    results = [
        make_result("CK-01", "cookies", "Compliant"),
        make_result("CK-04", "cookies", "Not Applicable"),  # session cookie, e.g. — shouldn't affect score
        make_result("CK-04", "cookies", "Not Applicable"),
    ]
    score = scoring.score_results(results)
    assert score["overall"]["score"] == 1.0  # only 1 scoreable result, and it's compliant
    assert score["overall"]["not_applicable"] == 2


def test_all_not_applicable_gives_none_score():
    results = [make_result("CK-04", "cookies", "Not Applicable")]
    score = scoring.score_results(results)
    assert score["overall"]["score"] is None


def test_unable_to_determine_excluded_from_score_but_tracked_separately():
    results = [
        make_result("CK-01", "cookies", "Compliant"),
        make_result("CK-04", "cookies", "Unable to Determine"),
        make_result("CK-05", "cookies", "Unable to Determine"),
    ]
    score = scoring.score_results(results)
    assert score["overall"]["score"] == 1.0  # only the Compliant result counts
    assert score["overall"]["unable_to_determine"] == 2
    assert score["overall"]["not_applicable"] == 0  # not conflated with NA


def test_empty_results_gives_none_score():
    score = scoring.score_results([])
    assert score["overall"]["score"] is None
    assert score["overall"]["compliant"] == 0


def test_per_category_breakdown():
    results = [
        make_result("CK-01", "cookies", "Compliant"),
        make_result("CN-01", "consent", "Non-Compliant"),
        make_result("CN-02", "consent", "Non-Compliant"),
    ]
    score = scoring.score_results(results)
    assert set(score["by_category"].keys()) == {"cookies", "consent"}
    assert score["by_category"]["cookies"]["score"] == 1.0
    assert score["by_category"]["consent"]["score"] == 0.0


def test_overall_aggregates_across_categories():
    results = [
        make_result("CK-01", "cookies", "Compliant"),
        make_result("CN-01", "consent", "Compliant"),
        make_result("CN-02", "consent", "Non-Compliant"),
    ]
    score = scoring.score_results(results)
    assert score["overall"]["compliant"] == 2
    assert score["overall"]["non_compliant"] == 1
    assert score["overall"]["score"] == round(2 / 3, 4)