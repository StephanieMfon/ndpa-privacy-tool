import json

from builders import NECESSARY, consent, policy, run, scan, scan_with_policy, tracker_request
from policy_samples import GOOD, VAGUE

from ndpa.analyse.trackers import TrackerList
from ndpa.models import Outcome
from ndpa.rules.checks import cookies as ck
from ndpa.rules.checks import trackers as tr
from ndpa.rules.context import build_ctx

DAY = 86400
START = 1_700_000_000.0


def cookie(name, days, domain="shop.example"):
    return {"name": name, "domain": domain, "expires": START + days * DAY}


def check(fn, ev, trackers=None):
    return fn(ev, build_ctx(ev, NECESSARY, trackers))


# CK-01
def test_ck01_session_cookies_only_is_not_applicable():
    assert check(ck.ck_01, scan(run(cookies=["a"]))).outcome == Outcome.NOT_APPLICABLE


def test_ck01_within_twelve_months_is_compliant():
    assert check(ck.ck_01, scan(run(jar=[cookie("a", 300)]))).outcome == Outcome.COMPLIANT


def test_ck01_over_twelve_months_without_justification_fails_and_reports_lifespan():
    r = check(ck.ck_01, scan_with_policy(VAGUE, no_action=run(jar=[cookie("_ga", 730)])))
    assert r.outcome == Outcome.NON_COMPLIANT and r.evidence[0]["lifespan_days"] == 730 and not r.evidence[0]["justified"]


def test_ck01_justified_when_the_policy_names_the_cookie_with_a_duration():
    text = "The _ga cookie is kept for 24 months to measure visits."
    r = check(ck.ck_01, scan_with_policy(text, no_action=run(jar=[cookie("_ga", 730)])))
    assert r.outcome == Outcome.COMPLIANT


def test_ck01_a_twelve_month_cookie_set_seconds_into_the_run_is_not_flagged():
    ev = scan(run(jar=[{"name": "cmp", "domain": "shop.example", "expires": START + 365 * DAY - 30}]))
    assert check(ck.ck_01, ev).outcome == Outcome.COMPLIANT


def test_ck01_without_the_read_time_it_cannot_be_computed():
    ev = scan(run(jar=[cookie("a", 730)], captured_at=None))
    assert check(ck.ck_01, ev).outcome == Outcome.UNABLE_TO_DETERMINE


def test_ck01_no_policy_gives_root_cause():
    ev = scan(run(jar=[cookie("a", 730)]), pol=policy("exhaustive_negative"))
    r = check(ck.ck_01, ev)
    assert r.outcome == Outcome.NON_COMPLIANT and r.root_cause == "PP-01"


# CK-02 and TR-02
SNAPSHOT = {"trackers": {
    "doubleclick.net": {"owner": {"displayName": "Google Ads (Google)"}, "default": "block", "categories": [], "rules": []},
    "obscure-ads.example": {"owner": {"displayName": "Obscure Ads Ltd"}, "default": "block", "categories": [], "rules": []},
}}


def tracker_list(tmp_path):
    path = tmp_path / "snap.json"
    path.write_text(json.dumps(SNAPSHOT))
    return TrackerList(path)


def test_ck02_not_applicable_without_third_party_cookies():
    assert check(ck.ck_02, scan(run(cookies=["a"]))).outcome == Outcome.NOT_APPLICABLE


def test_ck02_owner_named_by_its_parent_name_or_not_named(tmp_path):
    tl = tracker_list(tmp_path)
    ads = run(jar=[{"name": "IDE", "domain": ".doubleclick.net", "expires": -1}])
    named = scan_with_policy("Google Analytics is operated by Google.", no_action=ads)
    assert check(ck.ck_02, named, tl).outcome == Outcome.COMPLIANT      # 'Google' is the parent in 'Google Ads (Google)'
    unnamed = scan_with_policy(VAGUE, no_action=ads)
    r = check(ck.ck_02, unnamed, tl)
    assert r.outcome == Outcome.NON_COMPLIANT and r.evidence[0]["owner"] == "Google Ads (Google)"


def test_ck02_domain_without_a_known_owner_is_matched_by_its_domain_name():
    jar = run(jar=[{"name": "x", "domain": ".casalemedia.com", "expires": -1}])
    assert check(ck.ck_02, scan_with_policy("We work with casalemedia.com.", no_action=jar)).outcome == Outcome.COMPLIANT
    assert check(ck.ck_02, scan_with_policy(VAGUE, no_action=jar)).outcome == Outcome.NON_COMPLIANT


def test_tr02_named_unnamed_and_not_applicable():
    assert check(tr.tr_02, scan(run())).outcome == Outcome.NOT_APPLICABLE
    ev = run(events=[tracker_request(100, "Google Analytics (Google)", domain="google-analytics.com"),
                     tracker_request(200, "Obscure Ads Ltd", domain="obscure-ads.example")])
    r = check(tr.tr_02, scan_with_policy(GOOD, no_action=ev))
    assert r.outcome == Outcome.NON_COMPLIANT and r.instances_failed == 1 and r.instances_total == 2
    assert [row["vendor"] for row in r.evidence] == ["Obscure Ads Ltd"]
    ok = scan_with_policy(GOOD + "\nWe also use Obscure Ads Ltd for advertising.", no_action=ev)
    assert check(tr.tr_02, ok).outcome == Outcome.COMPLIANT


def test_tr02_a_generic_category_statement_does_not_name_a_vendor():
    ev = run(events=[tracker_request(100, "Obscure Ads Ltd", domain="obscure-ads.example")])
    r = check(tr.tr_02, scan_with_policy("We use analytics and advertising services.", no_action=ev))
    assert r.outcome == Outcome.NON_COMPLIANT


def test_tr02_banner_text_counts_as_a_disclosure():
    ev = run(events=[tracker_request(100, "Obscure Ads Ltd", domain="obscure-ads.example")],
             cons=consent(banner_text="We share data with Obscure Ads Ltd."))
    assert check(tr.tr_02, scan_with_policy(VAGUE, no_action=ev)).outcome == Outcome.COMPLIANT


def test_tr02_no_policy_and_uncertain_discovery():
    ev = run(events=[tracker_request(100, "Obscure Ads Ltd")])
    assert check(tr.tr_02, scan(ev, pol=policy("exhaustive_negative"))).root_cause == "PP-01"
    assert check(tr.tr_02, scan(ev, pol=policy("uncertain"))).outcome == Outcome.UNABLE_TO_DETERMINE
