"""Policy discovery against small generated sites. Needs a real browser."""
import pytest

from ndpa.capture.policy import capture_policy
from ndpa.capture.run import BrowserConfig

pytestmark = pytest.mark.browser
CFG = BrowserConfig(channel=None, headless=True)


def doc(title, body):
    return f"<!doctype html><html><head><title>{title}</title></head><body>{body}</body></html>"


HOME = ("<h1>Example Ltd</h1><p>Welcome to the Example company website, where we sell useful things "
        "such as shoes, bags and belts, delivered across the country.</p>")
POLICY = doc("Privacy", "<h1>Privacy Policy</h1><p>"
             + "We collect personal data to provide our services and we respect your privacy. " * 10 + "</p>")
COOKIES = doc("Cookies", "<h1>Cookie Policy</h1><p>" + "We use cookies to remember your choices. " * 10 + "</p>")


def run(make_site, files, tmp_path, **kw):
    base = make_site(files, **kw)
    return capture_policy(base + "/", tmp_path, CFG)


def test_policy_linked_from_the_homepage_footer(make_site, tmp_path):
    files = {"index.html": doc("Home", HOME + '<a href="/privacy/">Privacy Policy</a> '
                               '<a href="/cookie-policy/">Cookie Policy</a>'),
             "privacy/index.html": POLICY, "cookie-policy/index.html": COOKIES}
    pc = run(make_site, files, tmp_path)
    assert pc.discovery_status == "found_linked" and pc.problems == []
    privacy = [p for p in pc.pages if "privacy" in p.kinds][0]
    assert privacy.is_privacy_policy and privacy.via == "link" and privacy.click_path == ["Privacy Policy"]
    assert (tmp_path / privacy.text_file).exists() and (tmp_path / "policy.json").exists()
    cookie = [p for p in pc.pages if p.kinds == ["cookie"]][0]
    assert cookie.text_chars > 200 and not cookie.is_privacy_policy


def test_policy_two_clicks_away(make_site, tmp_path):
    files = {"index.html": doc("Home", HOME + '<a href="/legal/">Legal</a>'),
             "legal/index.html": doc("Legal", "<h1>Legal</h1><p>Our legal documents are listed here for you to read.</p>"
                                     '<a href="/privacy-notice/">Privacy Notice</a>'),
             "privacy-notice/index.html": POLICY}
    pc = run(make_site, files, tmp_path)
    assert pc.discovery_status == "found_linked"
    privacy = [p for p in pc.pages if p.is_privacy_policy][0]
    assert privacy.click_path == ["Legal", "Privacy Notice"]


def test_policy_found_only_by_common_path(make_site, tmp_path):
    files = {"index.html": doc("Home", HOME), "privacy-policy/index.html": POLICY}
    pc = run(make_site, files, tmp_path)
    assert pc.discovery_status == "found_unlinked"
    assert [p.via for p in pc.pages if p.is_privacy_policy] == ["probe"]


def test_no_policy_anywhere_is_an_exhaustive_negative(make_site, tmp_path):
    pc = run(make_site, {"index.html": doc("Home", HOME)}, tmp_path)
    assert pc.discovery_status == "exhaustive_negative" and pc.pages == [] and pc.problems == []


def test_privacy_section_inside_the_terms_page_counts(make_site, tmp_path):
    terms = doc("Terms", "<h1>Terms of Use</h1><h2>Acceptance of terms</h2><p>" + "You agree to these terms. " * 10
                + "</p><h2>Privacy and personal data</h2><p>" + "We collect personal data and protect your privacy. " * 10
                + "</p>")
    files = {"index.html": doc("Home", HOME + '<a href="/terms/">Terms of Use</a>'), "terms/index.html": terms}
    pc = run(make_site, files, tmp_path)
    assert pc.discovery_status == "found_linked"
    page = [p for p in pc.pages if p.is_privacy_policy][0]
    assert page.embedded and "privacy" in page.kinds


def test_short_placeholder_policy_is_not_a_policy_but_is_a_clear_negative(make_site, tmp_path):
    placeholder = doc("Privacy", "<h1>Privacy Policy</h1><p>This page is under construction. "
                      "Please check back later for our full privacy policy and details.</p>")
    files = {"index.html": doc("Home", HOME + '<a href="/privacy/">Privacy Policy</a>'),
             "privacy/index.html": placeholder}
    pc = run(make_site, files, tmp_path)
    assert pc.discovery_status == "exhaustive_negative"
    assert [p.is_privacy_policy for p in pc.pages] == [False]


def test_page_that_renders_nothing_is_uncertain(make_site, tmp_path):
    files = {"index.html": doc("Home", HOME + '<a href="/privacy/">Privacy Policy</a>'),
             "privacy/index.html": doc("Privacy", '<div id="app"></div>')}
    pc = run(make_site, files, tmp_path)
    assert pc.discovery_status == "uncertain"
    assert any("not rendered" in p for p in pc.problems)


def test_blocked_homepage_is_uncertain(make_site, tmp_path):
    pc = run(make_site, {}, tmp_path, block=True)
    assert pc.discovery_status == "uncertain" and "blocked" in pc.problems[0]


def test_policy_inside_an_embedded_frame_is_read(make_site, tmp_path):
    files = {"index.html": doc("Home", HOME + '<a href="/privacy/">Privacy Policy</a>'),
             "privacy/index.html": doc("Privacy", '<h1>Privacy</h1><iframe src="/policy-frame/"></iframe>'),
             "policy-frame/index.html": POLICY}
    pc = run(make_site, files, tmp_path)
    assert pc.discovery_status == "found_linked"
    assert [p.text_chars > 500 for p in pc.pages if p.is_privacy_policy] == [True]


def test_pdf_policy_is_reported_as_unreadable_not_as_missing(make_site, tmp_path):
    files = {"index.html": doc("Home", HOME + '<a href="/privacy.pdf">Privacy Policy</a>'),
             "privacy.pdf": "%PDF-1.4 fake"}
    pc = run(make_site, files, tmp_path)
    assert pc.discovery_status == "uncertain"
    assert any("PDF" in p for p in pc.problems)


def test_text_inside_collapsed_sections_is_read(make_site, tmp_path):
    hidden = ('<div style="display:none">' + "We collect personal data to provide our services and we respect your privacy. " * 10
              + "</div><details><summary>Your rights</summary><p>You have the right to access your personal data.</p></details>")
    files = {"index.html": doc("Home", HOME + '<a href="/privacy/">Privacy Policy</a>'),
             "privacy/index.html": doc("Privacy", "<h1>Privacy Policy</h1>" + hidden)}
    pc = run(make_site, files, tmp_path)
    assert pc.discovery_status == "found_linked"
    text = (tmp_path / pc.pages[0].text_file).read_text(encoding="utf-8")
    assert "right to access your personal data" in text and text.count("\n") >= 2
