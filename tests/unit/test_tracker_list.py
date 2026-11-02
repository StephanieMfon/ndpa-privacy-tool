import json

import pytest

from ndpa.analyse.trackers import TrackerList, is_third_party

SNAPSHOT = {"trackers": {
    "tracker.example": {"owner": {"displayName": "Tracker Inc"}, "default": "block",
                        "categories": ["Analytics"], "rules": []},
    "bigco.example": {"owner": {"name": "BigCo"}, "default": "ignore",
                      "categories": ["Advertising"], "rules": [{"rule": r"bigco\.example\/collect"}]},
    "mixed.example": {"owner": {"name": "Mixed"}, "default": "block", "categories": [],
                      "rules": [{"rule": r"mixed\.example\/static", "action": "ignore"}]},
}}


@pytest.fixture
def tl(tmp_path):
    p = tmp_path / "snap.json"
    p.write_text(json.dumps(SNAPSHOT))
    return TrackerList(p)


def test_default_block(tl):
    m = tl.match("https://tracker.example/x.js")
    assert m and m.owner == "Tracker Inc" and m.reason == "default: block"


def test_subdomain_matches(tl):
    assert tl.match("https://cdn.tracker.example/x.js") is not None


def test_ignore_domain_without_rule_is_not_tracker(tl):
    assert tl.match("https://bigco.example/maps") is None


def test_ignore_domain_with_matching_rule_is_tracker(tl):
    m = tl.match("https://bigco.example/collect?id=1")
    assert m and m.reason.startswith("url rule")


def test_rule_can_ignore(tl):
    assert tl.match("https://mixed.example/static/a.js") is None
    assert tl.match("https://mixed.example/pixel.gif") is not None


def test_unknown_domain(tl):
    assert tl.match("https://unknown.example/a.js") is None


@pytest.mark.parametrize("url,expected", [
    ("https://static.shop.com.ng/a.js", False),
    ("https://www.tracker.example/p", True),
])
def test_is_third_party(url, expected):
    assert is_third_party(url, "https://www.shop.com.ng/") is expected
