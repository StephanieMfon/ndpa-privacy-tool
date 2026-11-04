from builders import (NECESSARY, consent, geometry, js_cookie, run, scan, server_cookie, tracker_request)

from ndpa.models import Condition, Outcome
from ndpa.rules.checks import consent as c
from ndpa.rules.context import build_ctx

A, R = Condition.ACCEPT, Condition.REJECT


def check(fn, ev):
    return fn(ev, build_ctx(ev, NECESSARY))


def test_everything_is_not_applicable_without_cookies_or_trackers():
    ev = scan(run(cons=consent(found=False)))
    for fn in (c.cn_01, c.cn_02, c.cn_03, c.cn_04, c.cn_05):
        assert check(fn, ev).outcome == Outcome.NOT_APPLICABLE


def test_necessary_cookies_alone_are_not_a_trigger():
    ev = scan(run(cookies=["JSESSIONID", "OptanonConsent"]))
    assert check(c.cn_01, ev).outcome == Outcome.NOT_APPLICABLE


# CN-01
def test_cn01_no_banner_with_a_trigger_is_non_compliant():
    ev = scan(run(cookies=["_ga"], cons=consent(found=False)))
    assert check(c.cn_01, ev).outcome == Outcome.NON_COMPLIANT


def test_cn01_bottom_bar_fails_and_modal_passes():
    bottom = consent(geo=geometry("bottom", 0.07, True, False))
    assert check(c.cn_01, scan(run(cookies=["_ga"], cons=bottom))).outcome == Outcome.NON_COMPLIANT
    assert check(c.cn_01, scan(run(cookies=["_ga"], cons=consent()))).outcome == Outcome.COMPLIANT


def test_cn01_small_non_bottom_banner_fails_on_coverage():
    small = consent(geo=geometry("top", 0.06, False, False))
    r = check(c.cn_01, scan(run(cookies=["_ga"], cons=small)))
    assert r.outcome == Outcome.NON_COMPLIANT and "covers only" in r.note


# CN-02
def test_cn02_cookie_before_consent_fails():
    ev = scan(run(events=[js_cookie(500, "_ga")], cookies=["_ga"], cons=consent()))
    r = check(c.cn_02, ev)
    assert r.outcome == Outcome.NON_COMPLIANT and r.instances_failed == 1 and r.evidence[0]["cookie"] == "_ga"


def test_cn02_necessary_and_consent_cookies_are_ignored():
    ev = scan(run(events=[server_cookie(100, "JSESSIONID")], cookies=["JSESSIONID"], cons=consent()),
              accept=run(A, consent(action="accept", click_ms=5000), cookies=["JSESSIONID", "OptanonConsent", "_ga"]))
    r = check(c.cn_02, ev)  # _ga only appears after Accept, which is allowed; the trigger comes from that run
    assert r.outcome == Outcome.COMPLIANT


def test_cn02_cookie_after_reject_fails_even_if_none_before():
    reject = run(R, consent(reject="banner", action="reject", click_ms=5000, pre_cookies=["JSESSIONID"]),
                 events=[js_cookie(5200, "_late")], cookies=["JSESSIONID", "_late"])
    r = check(c.cn_02, scan(run(cons=consent(reject="banner"), cookies=["JSESSIONID"]), reject=reject))
    assert r.outcome == Outcome.NON_COMPLIANT and r.evidence[0]["run"] == "reject"


def test_cn02_cookie_before_the_reject_click_is_not_counted_twice():
    reject = run(R, consent(reject="banner", action="reject", click_ms=5000, pre_cookies=["_early"]),
                 events=[js_cookie(900, "_early")], cookies=["_early"])
    r = check(c.cn_02, scan(run(cons=consent(reject="banner"), cookies=["JSESSIONID"]), reject=reject))
    assert r.outcome == Outcome.COMPLIANT


def test_cn02_cookie_found_only_in_the_jar_still_counts():
    r = check(c.cn_02, scan(run(cookies=["mystery"], cons=consent())))
    assert r.outcome == Outcome.NON_COMPLIANT and r.evidence[0]["how"] == ["jar_only"]


def test_cn02_trigger_by_trackers_only_and_no_cookies_is_compliant():
    r = check(c.cn_02, scan(run(events=[tracker_request(400)], cons=consent())))
    assert r.outcome == Outcome.COMPLIANT


# CN-03
def test_cn03_variants():
    assert check(c.cn_03, scan(run(cookies=["_ga"], cons=consent(reject="banner")))).outcome == Outcome.COMPLIANT
    assert check(c.cn_03, scan(run(cookies=["_ga"], cons=consent(accept=True)))).outcome == Outcome.NON_COMPLIANT
    panel = run(R, consent(reject="panel", action="reject", click_ms=1))
    assert check(c.cn_03, scan(run(cookies=["_ga"], cons=consent(settings=True)), reject=panel)).outcome == Outcome.COMPLIANT


def test_cn03_no_mechanism_is_non_compliant_with_root_cause():
    r = check(c.cn_03, scan(run(cookies=["_ga"], cons=consent(found=False))))
    assert r.outcome == Outcome.NON_COMPLIANT and r.root_cause == "CN-01"


# CN-04 and CN-05
def accept_run(**kw):
    return run(A, consent(accept=True, action="accept", click_ms=5000, **kw), cookies=["_ga", "cmp_consent"])


def test_cn04_and_cn05_not_applicable_without_a_mechanism():
    ev = scan(run(cookies=["_ga"], cons=consent(found=False)))
    assert check(c.cn_04, ev).outcome == Outcome.NOT_APPLICABLE and check(c.cn_05, ev).outcome == Outcome.NOT_APPLICABLE


def test_cn04_persisted_choice_is_compliant_and_lists_consent_state_items():
    ev = scan(run(cookies=["_ga"], cons=consent()), accept=accept_run(after_reload=False, reopen="Cookie settings"))
    r = check(c.cn_04, ev)
    assert r.outcome == Outcome.COMPLIANT and r.evidence[0]["consent_state_items"] == ["cmp_consent"]


def test_cn04_banner_back_after_reload_is_non_compliant():
    ev = scan(run(cookies=["_ga"], cons=consent()), accept=accept_run(after_reload=True))
    assert check(c.cn_04, ev).outcome == Outcome.NON_COMPLIANT


def test_cn04_without_an_accept_run_is_unable_to_determine():
    assert check(c.cn_04, scan(run(cookies=["_ga"], cons=consent()))).outcome == Outcome.UNABLE_TO_DETERMINE


def test_cn05_reopen_control():
    base = run(cookies=["_ga"], cons=consent())
    assert check(c.cn_05, scan(base, accept=accept_run(after_reload=False, reopen="Cookie Preferences"))).outcome == Outcome.COMPLIANT
    assert check(c.cn_05, scan(base, accept=accept_run(after_reload=False))).outcome == Outcome.NON_COMPLIANT


def test_no_mechanism_convention_cn01_and_cn03_fail_cn04_cn05_not_applicable_cn02_from_timeline():
    ev = scan(run(events=[js_cookie(300, "_ga")], cookies=["_ga"], cons=consent(found=False)))
    got = {fn.__name__: check(fn, ev).outcome for fn in (c.cn_01, c.cn_02, c.cn_03, c.cn_04, c.cn_05)}
    assert got == {"cn_01": Outcome.NON_COMPLIANT, "cn_02": Outcome.NON_COMPLIANT, "cn_03": Outcome.NON_COMPLIANT,
                   "cn_04": Outcome.NOT_APPLICABLE, "cn_05": Outcome.NOT_APPLICABLE}
