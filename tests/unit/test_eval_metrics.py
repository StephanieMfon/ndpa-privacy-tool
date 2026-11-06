import pytest

from ndpa.evaluation import metrics


def test_precision_recall_and_f1_from_counts():
    p, r, f1 = metrics.prf(8, 2, 1)
    assert round(p, 3) == 0.8 and round(r, 3) == 0.889 and round(f1, 3) == 0.842
    assert metrics.prf(0, 0, 0) == (None, None, None)  # nothing predicted and nothing to find: not a result
    assert metrics.prf(0, 3, 0) == (0.0, None, 0.0)  # only false alarms: precision 0, recall undefined
    assert metrics.prf(0, 0, 4) == (None, 0.0, 0.0)  # everything missed: recall 0, precision undefined


def test_wilson_intervals_match_known_values_and_stay_inside_0_to_1():
    low, high = metrics.wilson(8, 10)
    assert round(low, 3) == 0.490 and round(high, 3) == 0.943
    assert metrics.wilson(0, 10)[0] == 0.0 and metrics.wilson(10, 10)[1] == 1.0
    assert metrics.wilson(0, 0) is None
    narrow, wide = metrics.wilson(50, 100), metrics.wilson(5, 10)
    assert narrow[1] - narrow[0] < wide[1] - wide[0]  # more items, a tighter interval


def test_cohens_kappa():
    assert round(metrics.cohen_kappa(list("AABBAB"), list("AABAAB")), 3) == 0.667
    assert metrics.cohen_kappa(list("ABAB"), list("ABAB")) == 1.0
    assert metrics.cohen_kappa(list("AABB"), list("BBAA")) == -1.0
    assert metrics.cohen_kappa(list("AAAA"), list("AAAA")) is None  # chance agreement is 100%: kappa is undefined
    assert metrics.cohen_kappa([], []) is None
    with pytest.raises(ValueError):
        metrics.cohen_kappa(["A"], ["A", "B"])


def test_kappa_wording():
    words = [metrics.kappa_band(k) for k in (-0.1, 0.1, 0.2, 0.35, 0.5, 0.7, 0.81, 1.0, None)]
    assert words == ["poor", "slight", "slight", "fair", "moderate", "substantial", "almost perfect", "almost perfect", "not defined"]


def test_spearman_rank_correlation_with_ties():
    assert metrics.spearman([1, 2, 3, 4], [1, 3, 2, 4]) == 0.8
    assert metrics.spearman([1, 2, 3], [10, 20, 30]) == 1.0 and metrics.spearman([1, 2, 3], [3, 2, 1]) == -1.0
    assert round(metrics.spearman([1, 2, 2, 4], [1, 2, 3, 4]), 3) == 0.949  # tied values share the average rank
    assert metrics.spearman([5, 5, 5], [1, 2, 3]) is None  # no variation: undefined
    assert metrics.spearman([1, 2], [1, 2]) is None  # fewer than 3 sites


def test_mean_absolute_error():
    assert metrics.mean_abs_error([10, 20, 30], [12, 18, 33]) == (2 + 2 + 3) / 3
    assert metrics.mean_abs_error([], []) is None
