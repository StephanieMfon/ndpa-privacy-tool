"""Accept and Reject runs against banner fixtures of known shape. Needs a real browser."""
import pytest

from ndpa.capture.run import BrowserConfig, after_click_activity, capture_run
from ndpa.models import Condition, RunStatus

pytestmark = pytest.mark.browser
CFG = BrowserConfig(channel=None, headless=True)


def run(site, page, condition, tmp_path):
    return capture_run(f"{site}/{page}", tmp_path, condition, observe_s=1, browser_config=CFG)


def of_kind(result, kind):
    return [e for e in result.events if e.kind == kind]


def test_no_action_describes_a_bottom_bar(site, tmp_path):
    r = run(site, "banner_simple.html", Condition.NO_ACTION, tmp_path)
    c = r.consent
    assert c.banner_found and c.banner_via == "generic"
    assert c.banner_geometry["position"] == "bottom" and c.banner_geometry["passes_r4"] is False
    assert c.accept_control["text"] == "Accept all" and c.reject_control["reached_via"] == "banner"
    assert c.action == "none" and c.click_ms is None and of_kind(r, "consent_click") == []
    assert "cookies" in c.banner_text and "_fx_id" in c.pre_click_cookie_names


def test_accept_run_clicks_and_cookies_after_the_click_are_visible(site, tmp_path):
    r = run(site, "banner_simple.html", Condition.ACCEPT, tmp_path)
    c = r.consent
    assert c.action == "accept" and c.click_ms is not None
    click = of_kind(r, "consent_click")[0]
    assert click.t_ms == c.click_ms and click.detail["action"] == "accept"
    assert "_fx_after" not in c.pre_click_cookie_names
    late = [e for e in of_kind(r, "cookie_set_js") if e.detail["name"] == "_fx_after"]
    assert late and late[0].t_ms >= c.click_ms
    assert c.banner_after_reload is False
    assert c.reopen_control == "Cookie settings"
    assert (tmp_path / "after_click.png").exists()


def test_reject_run_on_an_honest_site_sets_only_the_consent_record(site, tmp_path):
    r = run(site, "banner_simple.html", Condition.REJECT, tmp_path)
    assert r.consent.action == "reject"
    assert after_click_activity(r)["cookie_names"] == ["cmp_consent"]


def test_fake_reject_is_caught_by_the_cookie_after_the_click(site, tmp_path):
    r = run(site, "banner_fake_reject.html", Condition.REJECT, tmp_path)
    assert r.consent.action == "reject"
    assert "_late_id" in after_click_activity(r)["cookie_names"]


def test_reject_is_found_inside_the_preferences_panel(site, tmp_path):
    first = run(site, "banner_panel.html", Condition.NO_ACTION, tmp_path / "a").consent
    assert first.reject_control is None and first.settings_control["text"] == "Manage preferences"
    assert first.banner_geometry["position"] == "centre_modal" and first.banner_geometry["passes_r4"] is True
    r = run(site, "banner_panel.html", Condition.REJECT, tmp_path / "b")
    assert r.consent.action == "reject" and r.consent.reject_control["reached_via"] == "panel"
    assert len(of_kind(r, "consent_panel_open")) == 1


def test_shadow_dom_banner_is_found_and_clicked(site, tmp_path):
    r = run(site, "banner_shadow.html", Condition.ACCEPT, tmp_path)
    assert r.consent.banner_found and r.consent.banner_geometry["position"] == "top"
    assert r.consent.action == "accept" and r.consent.banner_after_reload is False


def test_accept_only_banner_has_no_reject_and_no_reopen_control(site, tmp_path):
    first = run(site, "banner_accept_only.html", Condition.NO_ACTION, tmp_path / "a").consent
    assert first.accept_control and first.reject_control is None and first.close_control
    rej = run(site, "banner_accept_only.html", Condition.REJECT, tmp_path / "b")
    assert rej.consent.action == "none" and "no reject control" in rej.consent.note
    acc = run(site, "banner_accept_only.html", Condition.ACCEPT, tmp_path / "c")
    assert acc.consent.action == "accept" and acc.consent.reopen_control is None


def test_close_only_banner_is_closed_in_the_accept_run(site, tmp_path):
    r = run(site, "banner_close_only.html", Condition.ACCEPT, tmp_path)
    assert r.consent.accept_control is None and r.consent.close_control
    assert r.consent.action == "close"


def test_page_without_a_banner(site, tmp_path):
    r = run(site, "plain.html", Condition.ACCEPT, tmp_path)
    assert r.consent.banner_found is False and r.consent.action == "none"
    assert "banner not found" in r.consent.note and of_kind(r, "consent_click") == []


def test_blocked_page_stops_before_any_click(site, tmp_path):
    r = run(site, "blocked.html", Condition.ACCEPT, tmp_path)
    assert r.status == RunStatus.BLOCKED and "http_403" in r.block_reasons
    assert r.consent.action == "none" and of_kind(r, "consent_click") == []


def test_banner_box_is_the_whole_banner_even_when_a_button_says_cookies(site, tmp_path):
    c = run(site, "banner_wrapped_buttons.html", Condition.NO_ACTION, tmp_path).consent
    assert c.accept_control["text"] == "Accept all cookies" and c.reject_control["text"] == "Reject all"
    assert c.banner_geometry["coverage"] > 0.1  # the banner, not just the div around the buttons
    assert "We use cookies" in c.banner_text
