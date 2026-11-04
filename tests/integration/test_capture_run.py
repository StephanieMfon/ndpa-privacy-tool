"""Needs a real browser (Playwright's bundled Chromium). Run: python -m pytest tests/integration -q"""
import pytest

from ndpa.capture.run import BrowserConfig, capture_run
from ndpa.models import RunStatus

pytestmark = pytest.mark.browser
CFG = BrowserConfig(channel=None, headless=True)


def run(site, page, tmp_path):
    return capture_run(f"{site}/{page}", tmp_path, observe_s=1, browser_config=CFG)


def of_kind(result, kind):
    return [e for e in result.events if e.kind == kind]


def test_plain_page_has_nothing_to_report(site, tmp_path):
    r = run(site, "plain.html", tmp_path)
    assert r.status == RunStatus.OK
    assert r.cookies == []
    assert of_kind(r, "cookie_set_js") == [] and of_kind(r, "storage_set") == []
    assert of_kind(r, "capture_error") == []


def test_script_cookie_and_storage_are_attributed_to_the_script(site, tmp_path):
    r = run(site, "tracker_page.html", tmp_path)
    cookie_sets = of_kind(r, "cookie_set_js")
    assert len(cookie_sets) == 1
    assert cookie_sets[0].detail["name"] == "_fx_id"
    assert cookie_sets[0].detail["script"].endswith("/static/tracker.js")
    storage_sets = of_kind(r, "storage_set")
    assert [(e.detail["area"], e.detail["key"]) for e in storage_sets] == [("localStorage", "fx_state")]
    assert any(c["name"] == "_fx_id" for c in r.cookies)
    assert r.local_storage_keys == ["fx_state"]
    assert of_kind(r, "capture_error") == []


def test_values_are_never_stored(site, tmp_path):
    r = run(site, "tracker_page.html", tmp_path)
    text = r.model_dump_json()
    assert "abc123" not in text and "secret123" not in text
    pixel = [e for e in of_kind(r, "request") if e.detail["url"].endswith("/pixel.gif")]
    assert pixel and pixel[0].detail["query_keys"] == ["page", "uid"]


def test_server_set_cookie_is_read_from_the_response(site, tmp_path):
    r = run(site, "server_cookie.html", tmp_path)
    with_cookie = [e for e in of_kind(r, "response") if "srv_id" in e.detail.get("set_cookie_names", [])]
    assert with_cookie
    assert any(c["name"] == "srv_id" for c in r.cookies)


def test_one_clock_and_all_files_written(site, tmp_path):
    r = run(site, "tracker_page.html", tmp_path)
    times = [e.t_ms for e in r.events]
    assert times == sorted(times) and times[0] >= 0
    for name in ("network.har", "dom_snapshot.html", "screenshot.png", "run.json"):
        assert (tmp_path / name).exists()


def test_unreachable_site_fails_cleanly(tmp_path):
    r = capture_run("http://127.0.0.1:9/", tmp_path, observe_s=1, browser_config=CFG)
    assert r.status == RunStatus.FAILED and r.error
