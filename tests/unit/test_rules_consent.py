from builders import NECESSARY, consent, geometry, js_cookie, run, scan, server_cookie, tracker_request

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


# CN-02 and the Close button (register R5: strict reading decides, implied reading is reported alongside)
def close_scan(*events, jar=None, geo=None, action="close"):
    """A banner with only a Close control: the Accept run clicks it at 5 s, and `events` happen after that."""
    first = run(cons=consent(geo=geo), events=[tracker_request(400)])  # a tracker makes this a consent site; no cookie before consent
    accepted = run(A, cons=consent(action=action, click_ms=5000), events=list(events), jar=jar)
    return scan(first, accept=accepted)


def close_rows(r):
    return [e for e in r.evidence if e["run"] == "close"]


def test_a_cookie_set_after_close_counts_under_the_strict_reading_but_the_implied_reading_excuses_a_first_party_one():
    r = check(c.cn_02, close_scan(server_cookie(6000, "prefs")))  # the site's own server, a conspicuous banner
    assert r.outcome == Outcome.NON_COMPLIANT and r.instances_failed == 1  # Close is not consent
    row = close_rows(r)[0]
    assert row["cookie"] == "prefs" and row["excused_if_implied"] is True and row["implied_outcome"] == "compliant"
    assert "after a Close click" in r.note and "implied reading (R5) this rule would be compliant" in r.note


def test_the_implied_reading_never_excuses_a_third_party_or_tracker_cookie():
    for event in (server_cookie(6000, "uid", third_party=True, domain="ads.example"), js_cookie(6000, "_ga", vendor="Google Analytics"), js_cookie(6000, "x")):
        r = check(c.cn_02, close_scan(event))
        row = close_rows(r)[0]
        assert r.outcome == Outcome.NON_COMPLIANT and row["excused_if_implied"] is False and row["implied_outcome"] == "non_compliant"


def test_the_implied_reading_needs_a_banner_that_passed_the_obstruction_test():
    strip = geometry(position="bottom", coverage=0.03, bottom_row_only=True, passes=False)
    r = check(c.cn_02, close_scan(server_cookie(6000, "prefs"), geo=strip))
    assert close_rows(r)[0]["excused_if_implied"] is False and close_rows(r)[0]["implied_outcome"] == "non_compliant"


def test_a_cookie_of_unknown_origin_is_not_excused():
    r = check(c.cn_02, close_scan(jar=[{"name": "mystery", "domain": "shop.example", "expires": -1}]))  # in the jar, no event says who set it
    assert close_rows(r)[0]["how"] == ["jar_only"] and close_rows(r)[0]["excused_if_implied"] is False


def test_the_strict_outcome_stays_compliant_when_nothing_is_set_after_close():
    r = check(c.cn_02, close_scan())
    assert r.outcome == Outcome.COMPLIANT and not close_rows(r)


def test_an_accept_click_is_consent_so_cookies_after_it_are_fine_and_nothing_about_close_is_added():
    r = check(c.cn_02, close_scan(server_cookie(6000, "prefs"), action="accept"))
    assert r.outcome == Outcome.COMPLIANT and "Close" not in r.note and not any("run" in e and e["run"] == "close" for e in r.evidence)


def test_cookies_before_consent_still_decide_even_when_close_cookies_are_excused():
    first = run(cons=consent(), cookies=["_ga"])  # a real violation before any click
    accepted = run(A, cons=consent(action="close", click_ms=5000), events=[server_cookie(6000, "prefs")])
    r = check(c.cn_02, scan(first, accept=accepted))
    assert r.outcome == Outcome.NON_COMPLIANT and close_rows(r)[0]["excused_if_implied"] is True and close_rows(r)[0]["implied_outcome"] == "non_compliant"
