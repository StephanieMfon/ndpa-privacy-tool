"""The dashboard used the way a person uses it: a real browser, the real server, the real form. Needs a browser."""
import socket
import threading
import time

import pytest
import uvicorn
import web_seed as ws
from playwright.sync_api import sync_playwright

from ndpa.storage import db
from ndpa.web.app import create_app
from ndpa.web.jobs import ScanManager, Settings

pytestmark = pytest.mark.browser


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def serve(tmp_path):
    """serve(runner=None, seed=None, **settings) starts the dashboard on a free port and returns its address.
    seed(conn, settings) can put scans in the database first."""
    servers = []

    def start(runner=None, seed=None, **overrides):
        settings = Settings(db_path=tmp_path / "t.db", evidence_root=tmp_path / "ev", log_dir=tmp_path / "logs", **overrides)
        if seed:
            conn = db.connect(settings.db_path)
            seed(conn, settings)
            conn.close()
        manager = ScanManager(settings, runner=runner)
        port = free_port()
        server = uvicorn.Server(uvicorn.Config(create_app(settings, manager), host="127.0.0.1", port=port, log_level="error"))
        threading.Thread(target=server.run, daemon=True).start()
        end = time.monotonic() + 10
        while not server.started and time.monotonic() < end:
            time.sleep(0.05)
        servers.append(server)
        return f"http://127.0.0.1:{port}"

    yield start
    for server in servers:
        server.should_exit = True


@pytest.fixture
def page():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser.new_page()
        browser.close()


def test_typing_an_address_and_pressing_the_button_starts_a_scan(serve, page):
    base = serve(runner=lambda *a: time.sleep(3))  # a scan that takes a moment and then stops without a result
    page.goto(base + "/")
    page.fill("#url", "93.184.216.34")  # a public address, so no name lookup is needed
    page.click("button[type=submit]")
    page.wait_for_url("**/scans/1")
    assert page.locator("[data-progress]").count() == 1 and "93.184.216.34" in page.locator("h1").inner_text()
    page.wait_for_selector("text=could not be completed", timeout=20000)  # live progress noticed the end and reloaded


def test_the_start_button_is_usable_again_after_going_back(serve, page):
    base = serve(runner=lambda *a: time.sleep(3))
    page.goto(base + "/")
    page.fill("#url", "93.184.216.34")
    page.click("button[type=submit]")
    page.wait_for_url("**/scans/1")
    page.go_back()
    page.wait_for_url(base + "/")
    button = page.locator("[data-scan-form] button[type=submit]")
    assert button.inner_text() == "Scan website" and button.is_enabled()


def test_an_address_that_is_not_allowed_explains_why_and_keeps_what_was_typed(serve, page):
    base = serve()
    page.goto(base + "/")
    page.fill("#url", "localhost:8000")
    page.click("button[type=submit]")
    page.wait_for_selector("[role=alert]")
    assert "private or local" in page.locator("[role=alert]").inner_text()
    assert page.input_value("#url") == "localhost:8000"
    assert page.locator("[data-scan-form] button[type=submit]").is_enabled()


def test_a_whole_scan_from_the_form_to_the_result_page(serve, page, site):
    base = serve(headless=True, bundled_chromium=True, observe_s=1, allow_private_targets=True)
    page.goto(base + "/")
    page.fill("#url", f"{site}/banner_simple.html")
    page.click("button[type=submit]")
    page.wait_for_url("**/scans/1")
    page.wait_for_selector("text=In plain words", timeout=180000)  # the progress page reloads itself into the result
    assert page.locator("text=Fix first").count() + page.locator("text=All 17 checks").count() >= 1
    page.goto(base + "/")  # and the finished scan is listed on the home page and in History
    assert "Recent scans" in page.content() and page.locator("a.row").count() == 1
    page.goto(base + "/history")
    assert page.locator("a.row").count() == 1


def two_scans(conn, settings):
    ws.seed_scan(conn, settings.evidence_root, "shop.ng", "2026-10-28T09:12:44+00:00", ws.problem_site())
    ws.seed_scan(conn, settings.evidence_root, "shop.ng", "2026-11-04T22:06:59+00:00", ws.better_site())


def test_the_filter_buttons_and_fix_first_links_on_a_result_page(serve, page):
    base = serve(seed=two_scans)
    page.goto(base + "/scans/2")
    all_checks = page.locator("details.check")
    assert all_checks.count() == 17
    page.click("[data-filter=bad]")
    visible = page.locator("details.check:visible")
    assert visible.count() == page.locator("details.check[data-tone=bad]").count() > 0
    assert page.locator("details.check[data-tone=ok]:visible").count() == 0
    assert page.locator("[data-group]:visible").count() < page.locator("[data-group]").count()  # empty groups are hidden too
    page.click("[data-filter=all]")
    assert page.locator("details.check:visible").count() == 17
    page.click(".fixes a[href='#sb-03']")  # a Fix first link opens the matching check
    page.wait_for_selector("details#sb-03[open]")


def test_scan_again_from_a_result_page_starts_a_new_scan(serve, page):
    def one_scan(conn, settings):  # a public address as the site, so no name lookup is needed
        ws.seed_scan(conn, settings.evidence_root, "93.184.216.34", "2026-11-04T22:06:59+00:00", ws.better_site())

    base = serve(runner=lambda *a: time.sleep(3), seed=one_scan)
    page.goto(base + "/scans/1")
    page.click("text=Scan again")
    page.wait_for_url("**/scans/2")
    assert page.locator("[data-progress]").count() == 1


def test_ticking_two_scans_enables_compare_and_opens_the_comparison(serve, page):
    base = serve(seed=two_scans)
    page.goto(base + "/history/shop.ng")
    button = page.locator("[data-compare-button]")
    boxes = page.locator("[data-pick]")
    assert boxes.count() == 2 and button.is_disabled()
    boxes.nth(0).check()
    assert button.is_disabled()
    boxes.nth(1).check()
    assert button.is_enabled()
    button.click()
    page.wait_for_url("**/compare?**")
    assert "Did the fixes work?" in page.content() and "fixed" in page.content()
    page.goto(base + "/history/shop.ng")
    page.click("text=Compare latest two")
    assert "Did the fixes work?" in page.content()
