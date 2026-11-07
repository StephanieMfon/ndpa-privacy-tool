import pytest

from ndpa.rules.context import NecessaryCookies

NECESSARY = NecessaryCookies.load()


@pytest.mark.parametrize("name", [
    "OptanonConsent", "CookieConsent", "euconsent-v2", "wpca_consent", "customerConsentPolicy", "cmp_consent",
    "sb-closed", "wpca_cc", "JSESSIONID", "PHPSESSID", "SOLSESSID", "mtn_ng_broker_session",
    "TS2a0f174f027", "__cf_bm", "AWSALB",
])
def test_known_necessary_cookies(name):
    assert NECESSARY.is_necessary(name)


@pytest.mark.parametrize("name", [
    "_ga", "_ga_YWQ5FX4GZX", "_gid", "_gcl_au", "_fbp", "IDE", "test_cookie", "fr", "_ttp", "ttcsid", "cto_bundle",
    "criteo_write_test", "bcookie", "li_sugr", "UserMatchHistory", "MUID", "_clck", "uid", "id5", "tsession_replay",
])
def test_trackers_are_not_swallowed_by_the_patterns(name):
    assert not NECESSARY.is_necessary(name)


def test_consent_state_group():
    assert NECESSARY.is_consent_state("wpca_consent") and not NECESSARY.is_consent_state("JSESSIONID")


def test_the_google_consent_platform_record_is_necessary_but_its_other_cookie_is_not_assumed_to_be():
    assert NECESSARY.is_necessary("FCCDCF") and NECESSARY.is_consent_state("FCCDCF")  # it stores the visitor's consent choice
    assert not NECESSARY.is_necessary("FCNEC")  # what it stores is unclear, so it stays non-necessary until the pilot decides
