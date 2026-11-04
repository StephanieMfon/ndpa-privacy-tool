from builders import (NECESSARY, consent, js_cookie, run, scan, server_cookie, storage_set, tracker_request)

from ndpa.models import Condition, Outcome
from ndpa.rules.checks import script as s
from ndpa.rules.context import build_ctx

R = Condition.REJECT


def check(fn, ev):
    return fn(ev, build_ctx(ev, NECESSARY))


def reject_run(events, click_ms=5000, cookies=()):
    return run(R, consent(reject="banner", action="reject", click_ms=click_ms), events=events, cookies=cookies)


def test_not_applicable_without_a_trigger():
    ev = scan(run(cookies=["JSESSIONID"]))
    assert all(check(fn, ev).outcome == Outcome.NOT_APPLICABLE for fn in (s.sb_01, s.sb_02, s.sb_03))


# SB-03: any request to a tracker
def test_sb03_tracker_request_before_consent_fails_with_one_row_per_vendor():
    ev = scan(run(events=[tracker_request(100, "A"), tracker_request(200, "A", "script"), tracker_request(300, "B")]))
    r = check(s.sb_03, ev)
    assert r.outcome == Outcome.NON_COMPLIANT and r.instances_failed == 2
    assert {row["vendor"]: row["requests"] for row in r.evidence} == {"A": 2, "B": 1}


def test_sb03_after_reject_counts_but_before_the_click_in_that_run_does_not():
    ev = scan(run(cookies=["_ga"]), reject=reject_run([tracker_request(900), tracker_request(5100, "Late")]))
    r = check(s.sb_03, ev)
    assert r.outcome == Outcome.NON_COMPLIANT and [row["vendor"] for row in r.evidence] == ["Late"]


def test_sb03_accept_run_requests_are_allowed():
    accept = run(Condition.ACCEPT, consent(accept=True, action="accept", click_ms=5000), events=[tracker_request(6000)])
    r = check(s.sb_03, scan(run(cookies=["_ga"]), accept=accept))
    assert r.outcome == Outcome.COMPLIANT


# SB-01: active, not merely loaded
def test_sb01_script_load_only_is_dormant_not_applicable():
    r = check(s.sb_01, scan(run(events=[tracker_request(100, rtype="script")])))
    assert r.outcome == Outcome.NOT_APPLICABLE and "dormant" in r.note


def test_sb01_beacon_storage_write_or_non_necessary_cookie_make_it_active():
    assert check(s.sb_01, scan(run(events=[tracker_request(100, rtype="image")]))).outcome == Outcome.NON_COMPLIANT
    assert check(s.sb_01, scan(run(events=[tracker_request(100, rtype="script"),
                                           storage_set(200, "k", vendor="V")]))).outcome == Outcome.NON_COMPLIANT
    assert check(s.sb_01, scan(run(events=[js_cookie(100, "_ga")]))).outcome == Outcome.NON_COMPLIANT


def test_sb01_necessary_cookie_written_by_a_script_is_not_active():
    r = check(s.sb_01, scan(run(events=[js_cookie(100, "cmp_consent")], cookies=["cmp_consent", "_x"])))
    assert r.outcome == Outcome.COMPLIANT


# SB-02
def test_sb02_script_cookie_fails_and_names_the_script():
    r = check(s.sb_02, scan(run(events=[js_cookie(100, "_ga", script="https://t.example/ga.js")], cookies=["_ga"])))
    assert r.outcome == Outcome.NON_COMPLIANT and r.evidence[0]["cookie"] == "_ga"


def test_sb02_third_party_response_cookie_fails_but_first_party_server_cookie_does_not():
    third = check(s.sb_02, scan(run(events=[server_cookie(100, "id", third_party=True, domain="ads.example")], cookies=["id"])))
    assert third.outcome == Outcome.NON_COMPLIANT
    own = check(s.sb_02, scan(run(events=[server_cookie(100, "lang")], cookies=["lang"])))
    assert own.outcome == Outcome.COMPLIANT


def test_sb02_cookies_with_unobserved_setter_are_unable_to_determine():
    assert check(s.sb_02, scan(run(cookies=["mystery"]))).outcome == Outcome.UNABLE_TO_DETERMINE


def test_sb02_only_necessary_cookies_is_not_applicable():
    ev = scan(run(events=[tracker_request(100, rtype="image")], cookies=["JSESSIONID"]))
    assert check(s.sb_02, ev).outcome == Outcome.NOT_APPLICABLE


def test_sb02_after_reject():
    ev = scan(run(cookies=["JSESSIONID", "_ga"], events=[tracker_request(1)]),
              reject=reject_run([js_cookie(5100, "_late")], cookies=["_late"]))
    r = check(s.sb_02, ev)
    assert r.outcome == Outcome.NON_COMPLIANT and r.evidence[0]["run"] == "reject"
