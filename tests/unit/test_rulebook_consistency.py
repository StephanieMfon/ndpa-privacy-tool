"""The rulebook file records some numbers that the code also uses. They must say the same thing."""
from ndpa.capture import consent as capture_consent
from ndpa.rules.checks import cookies
from ndpa.scoring.score import load_rulebook

RULES = {r["id"]: r for r in load_rulebook()["rules"]}


def test_the_cookie_lifespan_limit_matches_the_code():
    assert RULES["CK-01"]["thresholds"] == {"max_days": cookies.MAX_DAYS, "register": "R3"}


def test_the_banner_thresholds_belong_to_the_banner_rule_and_match_the_code():
    t = RULES["CN-01"]["thresholds"]
    assert t["register"] == "R4" and "OPEN" not in str(t)
    assert abs(t["min_coverage"] - capture_consent.MIN_COVERAGE) < 0.001 and abs(t["bottom_row_starts_at"] - capture_consent.BOTTOM_ROW_START) < 0.001
    assert "min_coverage" not in RULES["CK-01"]["thresholds"]  # it was once filed under the wrong rule
