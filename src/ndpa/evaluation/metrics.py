"""Plain-Python statistics for the evaluation. No third-party packages, so every number can be checked by hand.

Every function returns None when the number is not defined (for example precision when nothing was predicted),
never 0 or NaN: an undefined number must not look like a result.
"""
import math
from collections import Counter


def safe_div(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


def prf(tp: int, fp: int, fn: int) -> tuple[float | None, float | None, float | None]:
    """Precision, recall and F1 from counts. F1 = 2TP / (2TP + FP + FN), the same as 2PR / (P + R)."""
    return safe_div(tp, tp + fp), safe_div(tp, tp + fn), safe_div(2 * tp, 2 * tp + fp + fn)


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """95% Wilson score interval for a proportion. With 30 sites per rule these intervals are wide, and should be shown."""
    if n == 0:
        return None
    p = successes / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return max(0.0, centre - half), min(1.0, centre + half)


def cohen_kappa(a: list, b: list) -> float | None:
    """Agreement between two raters beyond chance. None when it is undefined (no items, or chance agreement is 100%)."""
    if len(a) != len(b):
        raise ValueError("both raters must label the same items")
    n = len(a)
    if n == 0:
        return None
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    ca, cb = Counter(a), Counter(b)
    expected = sum(ca[label] * cb[label] for label in set(ca) | set(cb)) / (n * n)
    if expected == 1:
        return None
    return (observed - expected) / (1 - expected)


def kappa_band(kappa: float | None) -> str:
    """The Landis and Koch (1977) wording for a kappa value."""
    if kappa is None:
        return "not defined"
    if kappa < 0:
        return "poor"
    for upper, word in ((0.20, "slight"), (0.40, "fair"), (0.60, "moderate"), (0.80, "substantial")):
        if kappa <= upper:
            return word
    return "almost perfect"


def _ranks(values: list[float]) -> list[float]:
    """Ranks starting at 1, tied values share the average of their positions."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def pearson(x: list[float], y: list[float]) -> float | None:
    n = len(x)
    if n < 3 or len(y) != n:
        return None
    mx, my = sum(x) / n, sum(y) / n
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    if sxx == 0 or syy == 0:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(x, y, strict=True)) / math.sqrt(sxx * syy)


def spearman(x: list[float], y: list[float]) -> float | None:
    """Rank correlation: do the two scores put the sites in the same order? Needs at least 3 sites."""
    if len(x) != len(y):
        raise ValueError("both lists must have the same length")
    return pearson(_ranks(x), _ranks(y))


def mean_abs_error(x: list[float], y: list[float]) -> float | None:
    if len(x) != len(y):
        raise ValueError("both lists must have the same length")
    return sum(abs(a - b) for a, b in zip(x, y, strict=True)) / len(x) if x else None
