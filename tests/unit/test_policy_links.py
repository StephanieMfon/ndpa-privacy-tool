import pytest

from ndpa.capture.policy import classify_link, headings_mention_privacy, is_policy_text, pick_links


@pytest.mark.parametrize("text,href,expected", [
    ("Privacy Policy", "https://x.ng/privacy", {"privacy"}),
    ("Privacy & Cookie Policy", "https://x.ng/p", {"privacy", "cookie"}),
    ("Cookie Policy", "https://x.ng/cookies", {"cookie"}),
    ("Data Protection", "https://x.ng/dp", {"privacy"}),
    ("Read more", "https://x.ng/privacy-notice", {"privacy"}),
    ("Terms of Use", "https://x.ng/terms", {"terms"}),
    ("Legal", "https://x.ng/legal", {"hub"}),
    ("Home", "https://x.ng/", set()),
])
def test_classify_link(text, href, expected):
    assert classify_link(text, href) == expected


def link(text, href):
    return {"text": text, "href": href}


def test_pick_links_dedupes_skips_current_page_and_prefers_text_matches():
    links = [link("Read more", "https://x.ng/privacy-notice"), link("Privacy Policy", "https://x.ng/p"),
             link("Privacy Policy", "https://x.ng/p#top"), link("Privacy", "https://x.ng/here")]
    picked = pick_links(links, "privacy", current_url="https://x.ng/here")
    assert [lk["href"] for lk in picked] == ["https://x.ng/p", "https://x.ng/privacy-notice"]


def test_pick_links_limit():
    links = [link(f"Privacy {i}", f"https://x.ng/{i}") for i in range(10)]
    assert len(pick_links(links, "privacy", limit=2)) == 2


def test_is_policy_text():
    assert is_policy_text("We collect personal data. " * 30)
    assert not is_policy_text("We collect personal data.")      # too short: a placeholder
    assert not is_policy_text("We sell shoes and bags. " * 40)  # long but not about privacy


def test_headings_mention_privacy():
    assert headings_mention_privacy(["Acceptance", "Privacy and personal data"])
    assert not headings_mention_privacy(["Acceptance", "Payment"])
