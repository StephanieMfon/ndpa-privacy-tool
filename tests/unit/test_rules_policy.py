from builders import NECESSARY, consent, policy, policy_page, run, scan, scan_with_policy
from policy_samples import GOOD, VAGUE

from ndpa.models import Outcome
from ndpa.rules.checks import policy as p
from ndpa.rules.context import build_ctx


def check(fn, ev):
    return fn(ev, build_ctx(ev, NECESSARY))


# PP-01
def test_pp01_by_discovery_status():
    def status(s, pages=()):
        return check(p.pp_01, scan(run(), pol=policy(s, pages)))
    assert status("found_linked", [policy_page()]).outcome == Outcome.COMPLIANT
    assert status("found_unlinked", [policy_page(via="probe", path=())]).outcome == Outcome.NON_COMPLIANT
    assert status("exhaustive_negative").outcome == Outcome.NON_COMPLIANT
    assert status("uncertain").outcome == Outcome.UNABLE_TO_DETERMINE
    assert check(p.pp_01, scan(run())).outcome == Outcome.UNABLE_TO_DETERMINE


# a thorough policy passes every text rule
def test_a_thorough_policy_passes_pp03_to_pp06():
    ev = scan_with_policy(GOOD, headings=["Cookies"])
    for fn in (p.pp_03, p.pp_04, p.pp_05, p.pp_06):
        r = check(fn, ev)
        assert r.outcome == Outcome.COMPLIANT, (fn.__name__, r.note)


def test_a_vague_policy_fails_pp03_to_pp06():
    ev = scan_with_policy(VAGUE)
    for fn in (p.pp_03, p.pp_04, p.pp_05, p.pp_06):
        assert check(fn, ev).outcome == Outcome.NON_COMPLIANT, fn.__name__


# PP-02
def test_pp02_standalone_cookie_page_headed_section_or_banner_text():
    standalone = scan(run(), pol=policy(pages=[policy_page(1), policy_page(2, kinds=("cookie",), privacy=False, chars=900)]),
                      texts={"policy_page_1.txt": VAGUE, "policy_page_2.txt": "x" * 900})
    assert check(p.pp_02, standalone).outcome == Outcome.COMPLIANT
    assert check(p.pp_02, scan_with_policy(GOOD, headings=["Privacy Policy", "Cookies"])).outcome == Outcome.COMPLIANT
    banner = consent(banner_text="We use cookies to provide the necessary site functionality and improve your experience.")
    assert check(p.pp_02, scan_with_policy(VAGUE, no_action=run(cons=banner))).outcome == Outcome.COMPLIANT


def test_pp02_banner_that_only_says_cookies_are_used_does_not_count():
    banner = consent(banner_text="This site uses cookies. Click accept to continue.")
    r = check(p.pp_02, scan_with_policy(VAGUE, no_action=run(cons=banner)))
    assert r.outcome == Outcome.NON_COMPLIANT


def test_pp02_cookie_page_found_only_by_probing_does_not_count():
    ev = scan(run(), pol=policy(pages=[policy_page(1), policy_page(2, kinds=("cookie",), privacy=False, via="probe", path=())]),
              texts={"policy_page_1.txt": VAGUE, "policy_page_2.txt": "x" * 900})
    assert check(p.pp_02, ev).outcome == Outcome.NON_COMPLIANT


# PP-03
def test_pp03_privacy_named_address_or_privacy_wording_nearby_counts_but_a_sales_address_does_not():
    assert check(p.pp_03, scan_with_policy("Write to dpo@shop.example for anything.")).outcome == Outcome.COMPLIANT
    assert check(p.pp_03, scan_with_policy("For questions about your personal data email help@shop.example.")).outcome == Outcome.COMPLIANT
    far = "Orders: sales@shop.example. " + "We sell shoes and bags every day of the week. " * 12 + "We respect your privacy."
    assert check(p.pp_03, scan_with_policy(far)).outcome == Outcome.NON_COMPLIANT


# PP-04
def test_pp04_needs_a_named_data_type_and_a_specific_use():
    ok = "We use your email address to send order confirmations."
    assert check(p.pp_04, scan_with_policy(ok)).outcome == Outcome.COMPLIANT
    for vague in ("We collect your email address to improve our services.",
                  "We use information for business purposes.",
                  "We process data in order to operate."):  # 'in order to' must not be read as the data type 'orders'
        assert check(p.pp_04, scan_with_policy(vague)).outcome == Outcome.NON_COMPLIANT, vague


# PP-05
def test_pp05_duration_trigger_and_vague_phrase():
    assert check(p.pp_05, scan_with_policy("We keep your data for 12 months.")).outcome == Outcome.COMPLIANT
    assert check(p.pp_05, scan_with_policy("We retain your data for six (6) months after closure.")).outcome == Outcome.COMPLIANT
    assert check(p.pp_05, scan_with_policy("We store your data until you withdraw consent.")).outcome == Outcome.COMPLIANT
    assert check(p.pp_05, scan_with_policy("We keep your data for the duration of your account.")).outcome == Outcome.COMPLIANT
    vague = check(p.pp_05, scan_with_policy("We retain your data for as long as necessary."))
    assert vague.outcome == Outcome.NON_COMPLIANT and "as long as necessary" in vague.note
    assert check(p.pp_05, scan_with_policy("Our office hours are 9 months of the year.")).outcome == Outcome.NON_COMPLIANT


# PP-06
def test_pp06_lists_which_rights_are_missing():
    text = ("You have the right to access your data. You may request correction of your data. "
            "You may request deletion of your data.")
    r = check(p.pp_06, scan_with_policy(text))
    assert r.outcome == Outcome.NON_COMPLIANT and r.instances_failed == 4
    assert r.evidence[0]["rights"]["access"] == "disclosed" and r.evidence[0]["rights"]["portability"] == "missing"


def test_pp06_only_the_ndpc_complaint_missing_is_a_labelled_sub_finding():
    text = GOOD.replace("You may lodge a complaint with the Nigeria Data Protection Commission (NDPC).", "")
    r = check(p.pp_06, scan_with_policy(text))
    assert r.outcome == Outcome.NON_COMPLIANT and "sub-finding" in r.note and r.instances_failed == 1


def test_pp06_an_explained_omission_counts():
    text = GOOD.replace("to receive your data in a portable format, ", "") + \
        "\nThe right to data portability does not apply to data we hold on other legal bases."
    r = check(p.pp_06, scan_with_policy(text))
    assert r.outcome == Outcome.COMPLIANT and r.evidence[0]["rights"]["portability"] == "explained"
    assert r.evidence[0]["rights"]["access"] == "disclosed"


def test_pp06_access_to_the_website_is_not_the_right_of_access():
    r = check(p.pp_06, scan_with_policy("You may request access to our website at any time."))
    assert r.evidence[0]["rights"]["access"] == "missing"


# no policy: D-34
def test_no_policy_fails_with_root_cause_and_uncertain_discovery_is_unable_to_determine():
    absent = scan(run(), pol=policy("exhaustive_negative"))
    for fn in (p.pp_03, p.pp_04, p.pp_05, p.pp_06):
        r = check(fn, absent)
        assert r.outcome == Outcome.NON_COMPLIANT and r.root_cause == "PP-01", fn.__name__
    uncertain = scan(run(), pol=policy("uncertain", problems=["timeout"]))
    for fn in (p.pp_03, p.pp_04, p.pp_05, p.pp_06):
        assert check(fn, uncertain).outcome == Outcome.UNABLE_TO_DETERMINE, fn.__name__
    assert check(p.pp_03, scan(run())).outcome == Outcome.UNABLE_TO_DETERMINE  # policy never captured
